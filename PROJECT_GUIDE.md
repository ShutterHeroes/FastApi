# YOLO FastAPI 추론 서버 프로젝트 가이드

## 📋 프로젝트 개요

이 프로젝트는 **YOLO 모델(best.pt)**을 FastAPI로 서빙하여 이미지 분류(Classification) 추론을 제공하는 서버입니다.
Docker 컨테이너로 배포하며, 다른 프로젝트에서 docker-compose를 통해 함께 구동됩니다.

---

## 🏗️ 프로젝트 구조

```
FastApi/
├── best.pt                # YOLO 학습된 모델 파일 (Classification)
├── infer_core.py          # YOLO 추론 엔진 핵심 로직
├── server.py              # Production용 FastAPI 서버 (비동기 콜백)
├── server_test.py         # 로컬 테스트용 FastAPI 서버 (동기 응답)
├── main.py                # 통합 FastAPI 서버 (콜백 + 동기 + 로컬 테스트)
├── requirements.txt       # Python 의존성
├── readme.txt             # 응답 결과 예시
├── Dockerfile             # (생성 필요) Docker 이미지 빌드
└── docker-compose.yml     # (생성 필요) 컨테이너 오케스트레이션
```

---

## 📝 코드 설명

### 1. **infer_core.py** - 추론 엔진 핵심
- **역할**: YOLO 모델 로드 및 추론 실행
- **주요 기능**:
  - `InferenceEngine` 클래스: YOLO 모델 초기화 및 관리
  - 이미지 로딩: `http(s)://`, `s3://`, `file://`, 로컬 경로 지원
  - `infer_one()`: 단일 이미지 추론
  - `infer_many()`: 여러 이미지 병렬 추론 (세마포어로 동시성 제어)
  - 결과 표준화: Classification/Detection 자동 구분

**핵심 코드**:
```python
class InferenceEngine:
    def __init__(self, model_path="best.pt", device=None, ...):
        self.model = YOLO(model_path)
        self.model.to(device)
        self.model.model.eval()

    async def infer_one(self, src: str, ...):
        # 이미지 로드 → YOLO 추론 → 결과 반환
        img = await self._load_image(src)
        results = await asyncio.to_thread(self.model.predict, img, ...)
        return {"source": src, "result": self._result_to_dict(results[0])}
```

---

### 2. **server.py** - Production 서버 (비동기 콜백)
- **역할**: 추론 요청을 받아 백그라운드에서 처리 후 콜백 URL로 결과 전송
- **주요 엔드포인트**:
  - `POST /infer`: 추론 요청 (202 Accepted 반환)
  - `GET /healthz`: 헬스체크

**플로우**:
1. 클라이언트가 `/infer`로 요청 (이미지 URLs + callback_url)
2. 즉시 `202 Accepted` 응답 (request_id 포함)
3. 백그라운드 태스크로 추론 실행
4. 완료 후 `callback_url`로 결과 POST (HMAC 서명 포함 가능)

**핵심 코드**:
```python
@app.post("/infer", status_code=202)
async def infer(req: InferIn, ...):
    async def _job():
        results = await _engine.infer_many(req.urls, ...)
        payload = {"request_id": req.request_id, "results": results}
        await send_callback(str(req.callback_url), payload)

    asyncio.create_task(_job())  # 백그라운드 실행
    return {"request_id": req.request_id, "status": "accepted"}
```

---

### 3. **server_test.py** - 로컬 테스트 서버 (동기 응답)
- **역할**: 즉시 추론 결과를 반환하는 동기식 API (테스트/디버깅 용도)
- **주요 엔드포인트**:
  - `POST /infer_sync`: 추론 요청 후 결과 즉시 반환

**차이점**:
- `server.py`: 비동기 콜백 (프로덕션)
- `server_test.py`: 동기 응답 (로컬 테스트)

---

### 4. **main.py** - 통합 서버
- **역할**: server.py + server_test.py 기능 통합 + 로컬 콜백 수신 엔드포인트
- **추가 엔드포인트**:
  - `POST /infer`: 비동기 콜백 방식
  - `POST /infer_sync`: 동기 응답 방식
  - `POST /callback`: 자기 자신에게 콜백 받을 수 있는 테스트 엔드포인트
  - `GET /last/{request_id}`: 마지막 콜백 결과 조회

**로컬 테스트 방법**:
```bash
# 1. /infer로 요청 (callback_url을 자기 자신의 /callback으로 설정)
# 2. /last/{request_id}로 결과 확인
```

---

## 🔧 환경 변수 (.env)

프로젝트는 `.env` 파일로 설정을 관리합니다:

```env
# 모델 설정
MODEL_PATH=best.pt
DEVICE=cuda:0                # 또는 cpu
IMGSZ=640
CONF=0.25
IOU=0.45

# 동시성 제어
MAX_INFLIGHT=2               # 동시 추론 최대 개수

# 인증 (옵션)
INBOUND_TOKEN=your_secret    # 클라이언트 → 서버 인증
SHARED_SECRET=hmac_secret    # 서버 → 콜백 HMAC 서명

# AWS (S3 사용 시)
AWS_DEFAULT_REGION=ap-northeast-2
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
```

---

## 🐳 Docker 컨테이너화 계획

### Dockerfile 생성 요구사항

```dockerfile
# 1. Base Image
#    - Python 3.10+ slim 이미지 사용
#    - CUDA 필요 시: nvidia/cuda:11.8.0-cudnn8-runtime-ubuntu22.04 기반

# 2. 시스템 의존성 설치
#    - libgl1-mesa-glx, libglib2.0-0 (OpenCV용)
#    - git (ultralytics 의존성)

# 3. Python 의존성 설치
#    - requirements.txt 복사 및 pip install

# 4. 모델 및 소스 복사
#    - best.pt, infer_core.py, server.py 등

# 5. 포트 노출
#    - EXPOSE 8000

# 6. 실행 명령
#    - CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000"]
```

**권장 구조**:
- **CPU 버전**: `python:3.10-slim` 기반
- **GPU 버전**: `nvidia/cuda:11.8.0-cudnn8-runtime` 기반 + PyTorch GPU 버전

---

### docker-compose.yml 생성 요구사항

```yaml
version: '3.8'

services:
  yolo-inference:
    build:
      context: .
      dockerfile: Dockerfile
    container_name: yolo-fastapi
    ports:
      - "8000:8000"
    environment:
      - MODEL_PATH=best.pt
      - DEVICE=cpu  # GPU 사용 시 cuda:0
      - MAX_INFLIGHT=2
      - INBOUND_TOKEN=${INBOUND_TOKEN}
      - SHARED_SECRET=${SHARED_SECRET}
    volumes:
      - ./best.pt:/app/best.pt  # 모델 파일 마운트 (옵션)
    restart: unless-stopped
    # GPU 사용 시 추가:
    # deploy:
    #   resources:
    #     reservations:
    #       devices:
    #         - driver: nvidia
    #           count: 1
    #           capabilities: [gpu]
```

**주요 고려사항**:
- 다른 서비스와 함께 구동 시 네트워크 설정 (`networks` 섹션)
- 환경 변수는 `.env` 파일로 관리
- GPU 사용 시 `nvidia-docker` 설정 필요

---

## 📊 API 응답 형식

### Classification 결과 (현재 모델)

```json
{
  "request_id": "uuid",
  "results": [
    {
      "source": "https://example.com/image.jpg",
      "result": {
        "task": "classification",
        "speed_ms": {
          "preprocess": 31.1,
          "inference": 53.7,
          "postprocess": 0.1
        },
        "probs": {
          "top5conf": [0.9885, 0.0073, 0.0014, 0.0009, 0.0009]
        },
        "preds": [
          {
            "class_id": 8,
            "label": "Pica_serica",
            "score": 0.9885
          },
          // ... top 5
        ]
      }
    }
  ]
}
```

### Detection 결과 (Detection 모델 사용 시)

```json
{
  "task": "detection",
  "detections": [
    {
      "bbox_xyxy": [x1, y1, x2, y2],
      "score": 0.95,
      "class_id": 0,
      "label": "person"
    }
  ]
}
```

---

## 🚀 실행 방법

### 로컬 실행
```bash
# 1. 의존성 설치
pip install -r requirements.txt

# 2. 환경 변수 설정
cp .env.example .env  # (생성 필요)

# 3. 서버 실행
uvicorn server:app --reload          # Production 서버
uvicorn server_test:app --reload     # 테스트 서버
uvicorn main:app --reload            # 통합 서버
```

### Docker 실행
```bash
# 1. 이미지 빌드
docker build -t yolo-fastapi .

# 2. 컨테이너 실행
docker run -p 8000:8000 --env-file .env yolo-fastapi

# 3. docker-compose 실행
docker-compose up -d
```

---

## ✅ TODO: Docker 배포를 위한 추가 작업

### 1. Dockerfile 생성
- [ ] CPU 버전 Dockerfile 작성
- [ ] GPU 버전 Dockerfile 작성 (선택)
- [ ] Multi-stage build로 이미지 크기 최적화
- [ ] .dockerignore 파일 생성 (.git, .idea, __pycache__ 제외)

### 2. docker-compose.yml 생성
- [ ] 기본 서비스 정의 (yolo-inference)
- [ ] 환경 변수 설정 (.env 연동)
- [ ] 볼륨 마운트 설정 (모델 파일)
- [ ] 네트워크 설정 (다른 서비스와 통신)
- [ ] 헬스체크 설정 (healthz 엔드포인트 활용)

### 3. .env.example 생성
- [ ] 모든 환경 변수 템플릿 작성
- [ ] 주석으로 설명 추가

### 4. 추가 최적화
- [ ] 모델 파일 크기 고려 (.dockerignore 또는 볼륨 마운트)
- [ ] Gunicorn/Uvicorn worker 수 설정
- [ ] 로깅 설정 (JSON 로그, 볼륨 마운트)
- [ ] CORS 설정 (필요 시)

---

## 🔍 주요 특징

### 1. **비동기 처리**
- FastAPI의 async/await 활용
- asyncio로 이미지 로딩/추론 병렬 처리
- 세마포어로 GPU 메모리 오버플로우 방지

### 2. **유연한 이미지 소스**
- HTTP/HTTPS URL
- S3 presigned URL
- S3 직접 경로 (`s3://bucket/key`)
- 로컬 파일 경로 (`file://` 또는 절대 경로)

### 3. **보안**
- Bearer 토큰 인증 (INBOUND_TOKEN)
- HMAC-SHA256 서명으로 콜백 무결성 보장

### 4. **확장성**
- 동시 추론 개수 제어 (MAX_INFLIGHT)
- 여러 인스턴스로 수평 확장 가능
- Docker 컨테이너로 배포 간편

---

## 🛠️ Claude가 작업할 때 체크리스트

### Dockerfile 생성 시
1. ✅ Python 버전 확인 (3.10+)
2. ✅ CUDA 버전 확인 (GPU 사용 시)
3. ✅ best.pt 파일 복사 또는 볼륨 마운트
4. ✅ requirements.txt 의존성 설치
5. ✅ uvicorn 실행 명령어 정확히 작성
6. ✅ 포트 8000 노출

### docker-compose.yml 생성 시
1. ✅ 서비스 이름 명확히 정의
2. ✅ 환경 변수 .env 연동
3. ✅ 볼륨 마운트 (모델 파일, 로그 등)
4. ✅ 네트워크 설정 (다른 서비스와 통신)
5. ✅ 재시작 정책 (`restart: unless-stopped`)
6. ✅ 헬스체크 설정 (`/healthz` 활용)

### 통합 테스트
1. ✅ `docker build` 성공 확인
2. ✅ `docker-compose up` 실행 확인
3. ✅ `/healthz` 헬스체크 응답 확인
4. ✅ `/infer_sync` 추론 테스트 (로컬 이미지)
5. ✅ 로그 출력 확인 (에러 없이 실행)

---

## 📌 참고 사항

### 현재 모델 특성
- **Task**: Classification (분류)
- **Input**: 단일 이미지
- **Output**: Top-5 클래스 + 확률 (probs.top5conf, preds)
- **클래스**: 조류 종 분류 (Pica_serica, Anas_zonorhyncha 등)

### 의존성 (requirements.txt)
```
fastapi
uvicorn[standard]
httpx
pydantic>=2
Pillow
ultralytics
boto3
torch
python-multipart
opencv-python
```

### 포트 설정
- **기본 포트**: 8000
- **다른 서비스와 충돌 시**: docker-compose에서 포트 매핑 변경

---

## 🎯 Claude 작업 가이드

이 문서를 바탕으로 다음 순서로 작업하세요:

1. **Dockerfile 생성**
   - CPU 버전 우선 작성
   - GPU 필요 시 별도 Dockerfile.gpu 생성

2. **docker-compose.yml 생성**
   - 기본 서비스 정의
   - 환경 변수 .env 연동
   - 네트워크 설정 추가

3. **.env.example 생성**
   - 모든 환경 변수 템플릿
   - 주석으로 설명 추가

4. **.dockerignore 생성**
   - 불필요한 파일 제외 (.git, .idea, __pycache__)

5. **README.md 업데이트** (선택)
   - Docker 실행 방법 추가
   - API 사용 예시 추가

---

**작성자**: Claude
**작성일**: 2025-10-04
**버전**: 1.0
