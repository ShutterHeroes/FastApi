import os, io, json, uuid, asyncio, hmac, hashlib
from typing import List, Optional, Dict, Any
from contextlib import asynccontextmanager

import torch
from PIL import Image
import httpx
import boto3
from fastapi import FastAPI, Body, Header, HTTPException
from pydantic import BaseModel, AnyHttpUrl, Field
from ultralytics import YOLO
from dotenv import load_dotenv
load_dotenv()  # .env 읽기
import boto3
# -----------------------
# 환경설정
# -----------------------
MODEL_PATH = os.getenv("MODEL_PATH", "best.pt")
DEVICE = os.getenv("DEVICE", "cuda:0" if torch.cuda.is_available() else "cpu")
MAX_INFLIGHT = int(os.getenv("MAX_INFLIGHT", "2"))   # 동시 추론 제한
IMGSZ = int(os.getenv("IMGSZ", "640"))
CONF = float(os.getenv("CONF", "0.25"))
IOU  = float(os.getenv("IOU", "0.45"))

INBOUND_TOKEN = os.getenv("INBOUND_TOKEN", "")  # 백엔드->나 인증용 Bearer
SHARED_SECRET = os.getenv("SHARED_SECRET", "")  # 내가 콜백 보낼 때 HMAC서명용

# -----------------------
# 앱/전역 객체
# -----------------------
app = FastAPI()
_model: YOLO | None = None
_http: httpx.AsyncClient | None = None
_s3 = None
_sem = asyncio.Semaphore(MAX_INFLIGHT)

# -----------------------
# 수명주기: 모델/HTTP 클라 준비
# -----------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    global _model, _http, _s3
    _model = YOLO(MODEL_PATH)
    _model.to(DEVICE)
    _model.model.eval()
    _http = httpx.AsyncClient(timeout=30)
    _s3 = boto3.client("s3")
    yield
    await _http.aclose()

app.router.lifespan_context = lifespan

# -----------------------
# Pydantic 스키마
# -----------------------
class InferIn(BaseModel):
    callback_url: AnyHttpUrl = Field(..., description="처리 후 결과를 보낼 URL (백엔드)")
    urls: List[str] = Field(..., description="이미지 URL 목록 (presigned S3 또는 http(s))")
    request_id: Optional[str] = Field(default_factory=lambda: str(uuid.uuid4()))
    conf: Optional[float] = CONF
    iou: Optional[float]  = IOU
    imgsz: Optional[int]  = IMGSZ

class InferAck(BaseModel):
    request_id: str
    status: str = "accepted"

# -----------------------
# 유틸: 이미지 로더
# -----------------------
async def load_image(link: str) -> Image.Image:
    if link.startswith("s3://"):
        # s3://bucket/key
        def _get_from_s3() -> bytes:
            bucket_key = link[5:]
            bucket, key = bucket_key.split("/", 1)
            obj = _s3.get_object(Bucket=bucket, Key=key)
            return obj["Body"].read()
        data = await asyncio.to_thread(_get_from_s3)
        return Image.open(io.BytesIO(data)).convert("RGB")
    else:
        assert _http is not None
        r = await _http.get(link)
        r.raise_for_status()
        return Image.open(io.BytesIO(r.content)).convert("RGB")

# -----------------------
# 유틸: YOLO 결과 to dict
# -----------------------
def yolo_to_dict(res, names: Dict[int, str]) -> Dict[str, Any]:
    out: Dict[str, Any] = {"detections": []}
    boxes = getattr(res, "boxes", None)
    if boxes is not None and boxes.xyxy is not None:
        xyxy = boxes.xyxy.cpu().tolist()
        conf = boxes.conf.cpu().tolist() if boxes.conf is not None else []
        cls  = boxes.cls.cpu().tolist()  if boxes.cls  is not None else []
        for i, b in enumerate(xyxy):
            cid = int(cls[i]) if i < len(cls) else None
            score = float(conf[i]) if i < len(conf) else None
            out["detections"].append({
                "bbox_xyxy": b,
                "score": score,
                "class_id": cid,
                "label": names.get(cid, str(cid))
            })
    return out

# -----------------------
# 추론 (세마포어로 동시성 제어)
# -----------------------
async def infer_one(url: str, conf: float, iou: float, imgsz: int) -> Dict[str, Any]:
    async with _sem:
        img = await load_image(url)
        def _predict():
            with torch.inference_mode():
                return _model.predict(img, conf=conf, iou=iou, imgsz=imgsz, device=DEVICE, verbose=False)
        results = await asyncio.to_thread(_predict)
        res0 = results[0]
        names = getattr(_model.model, "names", {})
        return {"url": url, "result": yolo_to_dict(res0, names)}

# -----------------------
# 콜백 전송(서명 포함, 재시도)
# -----------------------
async def post_callback(callback_url: str, payload: Dict[str, Any], max_retry: int = 3):
    headers = {"Content-Type": "application/json"}
    if SHARED_SECRET:
        raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        sig = hmac.new(SHARED_SECRET.encode("utf-8"), raw, hashlib.sha256).hexdigest()
        headers["X-Signature"] = f"sha256={sig}"

    assert _http is not None
    for attempt in range(1, max_retry + 1):
        try:
            resp = await _http.post(callback_url, json=payload, headers=headers, timeout=60)
            resp.raise_for_status()
            return
        except Exception:
            if attempt == max_retry:
                raise
            await asyncio.sleep(1.5 * attempt)

# -----------------------
# 처리 파이프라인
# -----------------------
async def process_and_callback(req: InferIn):
    coros = [infer_one(u, req.conf, req.iou, req.imgsz) for u in req.urls]
    results: List[Dict[str, Any]] = []
    for coro in asyncio.as_completed(coros):
        try:
            r = await coro
            results.append(r)
        except Exception as e:
            results.append({"error": str(e)})

    payload = {
        "request_id": req.request_id,
        "results": results
    }
    await post_callback(str(req.callback_url), payload)

# -----------------------
# 엔드포인트
# -----------------------
@app.get("/healthz")
async def healthz():
    return {"ok": True}

@app.post("/infer", response_model=InferAck, status_code=202)
async def infer(req: InferIn, authorization: Optional[str] = Header(default=None)):
    # (선택) 백엔드->나 인증
    if INBOUND_TOKEN:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Missing bearer token")
        token = authorization.split(" ", 1)[1].strip()
        if token != INBOUND_TOKEN:
            raise HTTPException(status_code=403, detail="Invalid token")

    # 비동기 태스크로 처리 후 콜백
    asyncio.create_task(process_and_callback(req))
    return InferAck(request_id=req.request_id)

# 로컬테스트용 

# --- 기존 load_image 대체 ---
async def load_image(link: str) -> Image.Image:
    # file:// 또는 로컬 경로
    if link.startswith("file://") or os.path.isfile(link):
        path = link[7:] if link.startswith("file://") else link
        return Image.open(path).convert("RGB")

    if link.startswith("s3://"):
        def _get_from_s3() -> bytes:
            bucket_key = link[5:]
            bucket, key = bucket_key.split("/", 1)
            obj = _s3.get_object(Bucket=bucket, Key=key)
            return obj["Body"].read()
        data = await asyncio.to_thread(_get_from_s3)
        return Image.open(io.BytesIO(data)).convert("RGB")

    # http(s)
    assert _http is not None
    r = await _http.get(link)
    r.raise_for_status()
    return Image.open(io.BytesIO(r.content)).convert("RGB")

class InferSyncOut(BaseModel):
    request_id: str
    results: List[Dict[str, Any]]

# 엔드포인트

@app.post("/infer_sync", response_model=InferSyncOut)
async def infer_sync(req: InferIn, authorization: Optional[str] = Header(default=None)):
    # (선택) 토큰 검사 유지
    if INBOUND_TOKEN:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Missing bearer token")
        token = authorization.split(" ", 1)[1].strip()
        if token != INBOUND_TOKEN:
            raise HTTPException(status_code=403, detail="Invalid token")

    coros = [infer_one(u, req.conf, req.iou, req.imgsz) for u in req.urls]
    done = []
    for c in asyncio.as_completed(coros):
        try:
            done.append(await c)
        except Exception as e:
            done.append({"error": str(e)})
    return {"request_id": req.request_id, "results": done}


# 자기 자신에게 콜백 

_LAST: Dict[str, Dict[str, Any]] = {}  # request_id -> payload 저장

@app.post("/callback")
async def local_callback(body: Dict[str, Any], x_signature: Optional[str] = Header(default=None)):
    # (옵션) 서명 검증
    if SHARED_SECRET and x_signature:
        raw = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        sig = hmac.new(SHARED_SECRET.encode(), raw, hashlib.sha256).hexdigest()
        if x_signature != f"sha256={sig}":
            raise HTTPException(status_code=400, detail="Bad signature")
    req_id = str(body.get("request_id", ""))
    _LAST[req_id] = body
    return {"ok": True}

@app.get("/last/{request_id}")
async def get_last(request_id: str):
    return _LAST.get(request_id, {"error": "not found"})
