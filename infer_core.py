# infer_core.py
import os
import io
import asyncio
from typing import List, Dict, Any, Optional

from PIL import Image
import torch
import httpx
from ultralytics import YOLO

try:
    import boto3
except Exception:
    boto3 = None


class InferenceEngine:
    """
    YOLO 추론 엔진
    - 모델 로드
    - 이미지 로딩(http/https, s3://, file://, 로컬 경로)
    - 단건/다건 추론
    - 결과 표준화(detection/classification)
    """

    def __init__(
        self,
        model_path: str = "best.pt",
        device: Optional[str] = None,
        imgsz: int = 640,
        conf: float = 0.25,
        iou: float = 0.45,
        http_timeout: float = 30.0,
        enable_s3: bool = True,
    ):
        self.model_path = model_path
        self.device = device or ("cuda:0" if torch.cuda.is_available() else "cpu")
        self.imgsz = imgsz
        self.conf = conf
        self.iou = iou

        # 모델 로드
        self.model = YOLO(self.model_path)
        self.model.to(self.device)
        self.model.model.eval()

        # HTTP 클라이언트
        self.http = httpx.AsyncClient(timeout=http_timeout)

        # S3 클라이언트(옵션)
        self.s3 = boto3.client("s3") if (enable_s3 and boto3 is not None) else None

    async def aclose(self):
        try:
            await self.http.aclose()
        except Exception:
            pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.aclose()

    # ---------------- 이미지 로더 ----------------
    async def _load_image(self, src: str) -> Image.Image:
        """
        src: http(s)://, s3://bucket/key, file://path, 혹은 로컬 경로
        """
        # file:// 또는 로컬 경로
        if src.startswith("file://") or (not src.startswith("http") and not src.startswith("s3://")):
            path = src[7:] if src.startswith("file://") else src
            return Image.open(path).convert("RGB")

        # s3://bucket/key
        if src.startswith("s3://"):
            if not self.s3:
                raise RuntimeError("boto3/s3 client is not available. Set enable_s3=True and install boto3.")
            def _get_from_s3() -> bytes:
                bucket_key = src[5:]
                bucket, key = bucket_key.split("/", 1)
                obj = self.s3.get_object(Bucket=bucket, Key=key)
                return obj["Body"].read()
            data = await asyncio.to_thread(_get_from_s3)
            return Image.open(io.BytesIO(data)).convert("RGB")

        # http/https
        resp = await self.http.get(src)
        resp.raise_for_status()
        return Image.open(io.BytesIO(resp.content)).convert("RGB")

    # ---------------- 라벨 헬퍼 ----------------
    def _label_from_names(self, names, cid: Optional[int]) -> Optional[str]:
        """names(dict|list)에 상관없이 안전하게 라벨 문자열을 반환"""
        if cid is None:
            return None
        try:
            cid = int(cid)
        except Exception:
            return str(cid)
        if isinstance(names, dict):
            return names.get(cid, str(cid))
        if isinstance(names, (list, tuple)):
            return names[cid] if 0 <= cid < len(names) else str(cid)
        return str(cid)

    # ---------------- 결과 표준화 ----------------
    def _result_to_dict(self, res) -> Dict[str, Any]:
        names = getattr(self.model.model, "names", {})
        speed = getattr(res, "speed", None)  # {'preprocess':..., 'inference':..., 'postprocess':...} 또는 None

        # ----- classification -----
        probs = getattr(res, "probs", None)
        if probs is not None:
            # top-5 (ID는 preds에서만 사용하고, probs에는 포함하지 않음)
            try:
                top5 = [int(c) for c in getattr(probs, "top5", [])]
            except Exception:
                top5 = []
            try:
                top5conf = [float(s) for s in getattr(probs, "top5conf", [])]
            except Exception:
                top5conf = []

            preds = [
                {
                    "class_id": c,
                    "label": self._label_from_names(names, c),
                    "score": s,
                }
                for c, s in zip(top5, top5conf)
            ]

            return (
                {
                    "task": "classification",
                    "speed_ms": speed,
                    "probs": {
                        # 요청대로 data/top5는 제외
                        "top5conf": top5conf,
                    },
                    "preds": preds,  # 사람이 보기 좋은 Top-5 (라벨 포함)
                }
            )

        # ----- detection -----
        boxes = getattr(res, "boxes", None)
        if boxes is not None and getattr(boxes, "xyxy", None) is not None:
            xyxy = boxes.xyxy.cpu().tolist()
            confs = boxes.conf.cpu().tolist() if boxes.conf is not None else []
            clss  = boxes.cls.cpu().tolist() if boxes.cls is not None else []

            dets: List[Dict[str, Any]] = []
            for i, box in enumerate(xyxy):
                cid   = int(clss[i]) if i < len(clss) else None
                score = float(confs[i]) if i < len(confs) else None
                dets.append(
                    {
                        "bbox_xyxy": box,
                        "score": score,
                        "class_id": cid,
                        "label": self._label_from_names(names, cid),
                    }
                )

            return (
                {
                    "task": "detection",
                    "speed_ms": speed,
                    "detections": dets,
                }
            )

        # ----- unknown -----
        return (
            {
                "task": "unknown",
                "speed_ms": speed,
            }
        )

    # ---------------- 단건/다건 추론 ----------------
    async def infer_one(
        self,
        src: str,
        *,
        conf: Optional[float] = None,
        iou: Optional[float] = None,
        imgsz: Optional[int] = None,
    ) -> Dict[str, Any]:
        img = await self._load_image(src)

        def _predict():
            with torch.inference_mode():
                return self.model.predict(
                    img,
                    conf=self.conf if conf is None else conf,
                    iou=self.iou if iou is None else iou,
                    imgsz=self.imgsz if imgsz is None else imgsz,
                    device=self.device,
                    verbose=False,
                )

        results = await asyncio.to_thread(_predict)
        res0 = results[0]
        return (
            {
                "source": src,
                "result": self._result_to_dict(res0),
            }
        )

    async def infer_many(
        self,
        sources: List[str],
        *,
        conf: Optional[float] = None,
        iou: Optional[float] = None,
        imgsz: Optional[int] = None,
        concurrency: int = 2,
    ) -> List[Dict[str, Any]]:
        sem = asyncio.Semaphore(concurrency)

        async def _wrapped(u: str):
            async with sem:
                try:
                    return await self.infer_one(u, conf=conf, iou=iou, imgsz=imgsz)
                except Exception as e:
                    return {"source": u, "error": str(e)}

        tasks = [asyncio.create_task(_wrapped(u)) for u in sources]
        out: List[Dict[str, Any]] = []
        for t in asyncio.as_completed(tasks):
            out.append(await t)
        return out
