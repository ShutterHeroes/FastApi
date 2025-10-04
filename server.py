# server.py
import os, json, uuid, asyncio, hmac, hashlib
from typing import List, Dict, Any, Optional
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel, Field, AnyHttpUrl

from infer_core import InferenceEngine
from dotenv import load_dotenv
load_dotenv()  # .env 읽기

# # S3 직접 연결 (비활성화 - 공개 URL 사용)
# import boto3
# s3 = boto3.client("s3", region_name=os.getenv("AWS_DEFAULT_REGION", "ap-northeast-2"))
# ---------- 환경 설정 ----------
MODEL_PATH    = os.getenv("MODEL_PATH", "best.pt")
DEVICE        = os.getenv("DEVICE",  None)
IMGSZ         = int(os.getenv("IMGSZ", "640"))
CONF          = float(os.getenv("CONF", "0.25"))
IOU           = float(os.getenv("IOU", "0.45"))
MAX_CONC      = int(os.getenv("MAX_INFLIGHT", "2"))  # 추론 동시성
POST_TIMEOUT  = float(os.getenv("POST_TIMEOUT", "60"))
INBOUND_TOKEN = os.getenv("INBOUND_TOKEN", "")       # (옵션) 백엔드→나 인증
SHARED_SECRET = os.getenv("SHARED_SECRET", "")       # (옵션) 콜백 HMAC 서명
QUEUE_TIMEOUT = float(os.getenv("QUEUE_TIMEOUT", "0"))  # >0 이면 즉시 실패전략에 사용X(예시 단순화)

# ---------- 앱 전역 ----------
app = FastAPI(title="Production Inference API (Callback)")
_engine: Optional[InferenceEngine] = None
_http: Optional[httpx.AsyncClient] = None

# ---------- 모델/HTTP 준비 ----------
@asynccontextmanager
async def lifespan(app: FastAPI):
    global _engine, _http
    _engine = InferenceEngine(
        model_path=MODEL_PATH, device=DEVICE, imgsz=IMGSZ, conf=CONF, iou=IOU
    )
    _http = httpx.AsyncClient(timeout=POST_TIMEOUT)
    yield
    await _http.aclose()
    await _engine.aclose()

app.router.lifespan_context = lifespan

# ---------- 스키마 ----------
class InferIn(BaseModel):
    callback_url: AnyHttpUrl
    urls: List[str]
    request_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    conf: float = CONF
    iou: float = IOU
    imgsz: int = IMGSZ

class Ack(BaseModel):
    request_id: str
    status: str = "accepted"

# ---------- 유틸: 콜백 전송 ----------
async def send_callback(url: str, payload: Dict[str, Any], max_retry: int = 3):
    headers = {"Content-Type": "application/json"}
    if SHARED_SECRET:
        raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        sig = hmac.new(SHARED_SECRET.encode("utf-8"), raw, hashlib.sha256).hexdigest()
        headers["X-Signature"] = f"sha256={sig}"
    for attempt in range(1, max_retry + 1):
        try:
            resp = await _http.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            return
        except Exception:
            if attempt == max_retry:
                raise
            await asyncio.sleep(1.5 * attempt)

# ---------- 엔드포인트 ----------
@app.get("/healthz")
async def healthz():
    return {"ok": True}

@app.post("/infer", response_model=Ack, status_code=202)
async def infer(req: InferIn, authorization: Optional[str] = Header(default=None)):
    # (옵션) 백엔드→나 인증
    if INBOUND_TOKEN:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Missing bearer token")
        if authorization.split(" ", 1)[1].strip() != INBOUND_TOKEN:
            raise HTTPException(status_code=403, detail="Invalid token")

    # 비동기 처리 → 완료 후 콜백
    async def _job():
        results = await _engine.infer_many(
            req.urls, conf=req.conf, iou=req.iou, imgsz=req.imgsz, concurrency=MAX_CONC
        )
        payload = {"request_id": req.request_id, "results": results}
        await send_callback(str(req.callback_url), payload)

    asyncio.create_task(_job())
    return Ack(request_id=req.request_id)
