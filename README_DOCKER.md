# Docker 배포 가이드

## 📦 생성된 파일

Docker 컨테이너화를 위해 다음 파일들이 생성되었습니다:

- `Dockerfile` - CPU 버전 Docker 이미지
- `docker-compose.yml` - 컨테이너 오케스트레이션
- `.env.example` - 환경 변수 템플릿
- `.dockerignore` - Docker 빌드 제외 파일 목록

---

## 🚀 빠른 시작

### 1. 환경 변수 설정

```bash
# .env 파일 생성
cp .env.example .env

# .env 파일 편집 (필요한 값 설정)
# - INBOUND_TOKEN, SHARED_SECRET (인증)
# - AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY (S3 사용 시)
```

### 2. Docker Compose로 실행

```bash
# 빌드 및 실행
docker-compose up -d

# 로그 확인
docker-compose logs -f

# 헬스체크
curl http://localhost:8000/healthz

# 중지
docker-compose down
```

### 3. Docker 명령어로 실행 (수동)

```bash
# 이미지 빌드
docker build -t yolo-fastapi:latest .

# 컨테이너 실행
docker run -d \
  --name yolo-fastapi \
  -p 8000:8000 \
  --env-file .env \
  yolo-fastapi:latest

# 로그 확인
docker logs -f yolo-fastapi

# 중지 및 제거
docker stop yolo-fastapi
docker rm yolo-fastapi
```

---

## 🔧 환경 변수 설정

주요 환경 변수 (`.env` 파일):

```env
# 모델 설정
MODEL_PATH=best.pt
DEVICE=cpu
IMGSZ=640
CONF=0.25
IOU=0.45

# 동시성 제어
MAX_INFLIGHT=2

# 인증 (옵션)
INBOUND_TOKEN=your_secret_token
SHARED_SECRET=your_hmac_secret

# AWS S3 (사용 시)
AWS_DEFAULT_REGION=ap-northeast-2
AWS_ACCESS_KEY_ID=your_key
AWS_SECRET_ACCESS_KEY=your_secret
```

---

## 🐳 GPU 버전 (선택)

GPU를 사용하려면:

### 1. Dockerfile.gpu 생성

```dockerfile
FROM nvidia/cuda:11.8.0-cudnn8-runtime-ubuntu22.04

# Python 설치
RUN apt-get update && apt-get install -y python3.10 python3-pip

# ... (나머지는 Dockerfile과 동일)
```

### 2. docker-compose.yml에서 GPU 서비스 활성화

```yaml
# 주석 해제:
yolo-inference-gpu:
  # ...
  deploy:
    resources:
      reservations:
        devices:
          - driver: nvidia
            count: 1
            capabilities: [gpu]
```

### 3. nvidia-docker 설치 필요

```bash
# NVIDIA Container Toolkit 설치
distribution=$(. /etc/os-release;echo $ID$VERSION_ID)
curl -s -L https://nvidia.github.io/nvidia-docker/gpgkey | sudo apt-key add -
curl -s -L https://nvidia.github.io/nvidia-docker/$distribution/nvidia-docker.list | \
  sudo tee /etc/apt/sources.list.d/nvidia-docker.list

sudo apt-get update
sudo apt-get install -y nvidia-docker2
sudo systemctl restart docker
```

---

## 🌐 다른 프로젝트와 연동

### docker-compose.yml 통합 예시

다른 프로젝트의 `docker-compose.yml`에 추가:

```yaml
version: '3.8'

services:
  # 기존 서비스들...
  backend:
    # ...
    networks:
      - app-network

  # YOLO 추론 서버 추가
  yolo-inference:
    build:
      context: ./FastApi
      dockerfile: Dockerfile
    container_name: yolo-fastapi
    ports:
      - "8000:8000"
    environment:
      - MODEL_PATH=best.pt
      - DEVICE=cpu
      - INBOUND_TOKEN=${YOLO_INBOUND_TOKEN}
      - SHARED_SECRET=${YOLO_SHARED_SECRET}
    networks:
      - app-network
    restart: unless-stopped

networks:
  app-network:
    driver: bridge
```

### 환경 변수 관리

루트 프로젝트의 `.env`에 추가:

```env
# YOLO 서버 설정
YOLO_INBOUND_TOKEN=your_token
YOLO_SHARED_SECRET=your_secret
```

---

## 🧪 테스트

### 1. 헬스체크

```bash
curl http://localhost:8000/healthz
# 응답: {"ok": true}
```

### 2. 추론 테스트 (동기)

로컬 이미지로 테스트하려면 `server_test.py` 사용:

```bash
# server_test.py 실행
docker run -d \
  --name yolo-test \
  -p 8001:8000 \
  --env-file .env \
  -v $(pwd)/test_images:/app/test_images \
  yolo-fastapi:latest \
  uvicorn server_test:app --host 0.0.0.0 --port 8000

# 테스트 요청
curl -X POST http://localhost:8001/infer_sync \
  -H "Content-Type: application/json" \
  -d '{
    "urls": ["file:///app/test_images/sample.jpg"],
    "request_id": "test-123"
  }'
```

### 3. 추론 테스트 (비동기 콜백)

```bash
# 콜백 받을 서버 필요
curl -X POST http://localhost:8000/infer \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer your_token" \
  -d '{
    "callback_url": "https://your-backend.com/callback",
    "urls": ["https://example.com/image.jpg"],
    "request_id": "test-123"
  }'

# 응답: {"request_id": "test-123", "status": "accepted"}
```

---

## 📊 성능 최적화

### 1. Worker 수 조정

```dockerfile
# Dockerfile 마지막 줄 수정
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
```

### 2. MAX_INFLIGHT 조정

```env
# GPU 메모리에 맞춰 조정
MAX_INFLIGHT=4  # GPU가 크면 늘림
```

### 3. 이미지 크기 최적화

```bash
# Multi-stage build로 이미지 크기 축소
# Dockerfile에 추가:
FROM python:3.10-slim as builder
# ... 빌드 단계

FROM python:3.10-slim
COPY --from=builder /usr/local/lib/python3.10/site-packages /usr/local/lib/python3.10/site-packages
```

---

## 🔍 트러블슈팅

### 문제 1: Docker 빌드 실패

```bash
# Docker Desktop 실행 확인
docker --version

# Docker 데몬 시작
# Windows: Docker Desktop 실행
# Linux: sudo systemctl start docker
```

### 문제 2: 모델 파일 없음

```bash
# best.pt 파일이 있는지 확인
ls -lh best.pt

# 또는 볼륨 마운트 사용
docker run -v $(pwd)/best.pt:/app/best.pt yolo-fastapi:latest
```

### 문제 3: GPU 인식 안됨

```bash
# nvidia-docker 설치 확인
docker run --rm --gpus all nvidia/cuda:11.8.0-base-ubuntu22.04 nvidia-smi

# CUDA 버전 확인
nvidia-smi
```

### 문제 4: 메모리 부족

```bash
# docker-compose.yml에 메모리 제한 추가
services:
  yolo-inference:
    # ...
    deploy:
      resources:
        limits:
          memory: 4G
```

---

## 📝 다음 단계

1. ✅ Dockerfile 생성 완료
2. ✅ docker-compose.yml 생성 완료
3. ✅ .env.example 생성 완료
4. ✅ .dockerignore 생성 완료
5. ⏳ Docker 빌드 및 테스트 (Docker Desktop 실행 필요)
6. ⏳ 다른 프로젝트와 통합

---

**작성일**: 2025-10-04
**참고**: PROJECT_GUIDE.md
