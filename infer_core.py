import io
import asyncio
from typing import List, Dict, Any, Optional

from PIL import Image
import torch
import httpx
from ultralytics import YOLO


class InferenceEngine:
    """
    YOLO 추론 엔진
    - 모델 로드
    - 이미지 로딩(http/https, file://, 로컬 경로)
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

    async def aclose(self):
        try:
            await self.http.aclose()
        except Exception:
            pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.aclose()

    # ---------------- 공용 유틸: float 반올림 ----------------
    @staticmethod
    def _round_floats(obj: Any, nd: int = 5) -> Any:
        """obj 안의 모든 float을 소수점 nd 자리로 반올림해서 반환"""
        if isinstance(obj, float):
            return round(obj, nd)
        if isinstance(obj, list):
            return [InferenceEngine._round_floats(x, nd) for x in obj]
        if isinstance(obj, tuple):
            return [InferenceEngine._round_floats(x, nd) for x in obj]  # tuple도 list로 직렬화
        if isinstance(obj, dict):
            return {k: InferenceEngine._round_floats(v, nd) for k, v in obj.items()}
        return obj

    # ---------------- 이미지 로더 ----------------
    async def _load_image(self, src: str) -> Image.Image:
        """
        src: http(s)://, file://path, 혹은 로컬 경로
        """
        # file:// 또는 로컬 경로
        if src.startswith("file://") or (not src.startswith("http")):
            path = src[7:] if src.startswith("file://") else src
            return Image.open(path).convert("RGB")

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
            # top-5 (ID는 preds에서만 사용)
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

            out = {
                "task": "classification",
                "speed_ms": speed,
                "probs": {
                    # 요청대로 data/top5는 제외, top5conf만 남김
                    "top5conf": top5conf,
                },
                "preds": preds,  # 사람이 보기 좋은 Top-5 (라벨 포함)
            }
            return self._round_floats(out, 5)

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
                        "bbox_xyxy": box,  # 나중에 일괄 반올림
                        "score": score,
                        "class_id": cid,
                        "label": self._label_from_names(names, cid),
                    }
                )

            out = {
                "task": "detection",
                "speed_ms": speed,
                "detections": dets,
            }
            return self._round_floats(out, 5)

        # ----- unknown -----
        out = {
            "task": "unknown",
            "speed_ms": speed,
        }
        return self._round_floats(out, 5)

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
        return {
            "source": src,
            "result": self._result_to_dict(res0),
        }

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
