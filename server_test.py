# server_test.py
import os, uuid, asyncio
from typing import List, Dict, Any, Optional
from contextlib import asynccontextmanager
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field
from infer_core import InferenceEngine

MODEL_PATH = os.getenv("MODEL_PATH", "best.pt")
DEVICE     = os.getenv("DEVICE",  None)  # 예: "cpu" 또는 "cuda:0"
IMGSZ      = int(os.getenv("IMGSZ", "640"))
CONF       = float(os.getenv("CONF", "0.25"))
IOU        = float(os.getenv("IOU", "0.45"))
MAX_CONC   = int(os.getenv("MAX_INFLIGHT", "2"))
INBOUND_TOKEN = os.getenv("INBOUND_TOKEN", "")  # (옵션) Bearer 토큰 검사

app = FastAPI(title="Local Test Inference API")
_engine: Optional[InferenceEngine] = None

class InferSyncIn(BaseModel):
    urls: List[str] = Field(..., description="이미지 URL 배열 (http/https/s3/file/로컬 경로)")
    request_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    conf: float = CONF
    iou: float = IOU
    imgsz: int = IMGSZ

class InferSyncOut(BaseModel):
    request_id: str
    results: List[Dict[str, Any]]

@asynccontextmanager
async def lifespan(app: FastAPI):
    global _engine
    _engine = InferenceEngine(
        model_path=MODEL_PATH, device=DEVICE, imgsz=IMGSZ, conf=CONF, iou=IOU
    )
    yield
    await _engine.aclose()

app.router.lifespan_context = lifespan

@app.get("/healthz")
async def healthz():
    return {"ok": True}

@app.post("/infer_sync", response_model=InferSyncOut)
async def infer_sync(req: InferSyncIn, authorization: Optional[str] = Header(default=None)):
    # (옵션) 토큰 검사
    if INBOUND_TOKEN:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Missing bearer token")
        if authorization.split(" ", 1)[1].strip() != INBOUND_TOKEN:
            raise HTTPException(status_code=403, detail="Invalid token")

    results = await _engine.infer_many(
        req.urls, conf=req.conf, iou=req.iou, imgsz=req.imgsz, concurrency=MAX_CONC
    )
    return {"request_id": req.request_id, "results": results}
