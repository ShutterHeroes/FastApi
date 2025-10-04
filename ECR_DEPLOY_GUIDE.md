# AWS ECR 배포 가이드

## 📋 배포 플로우

```
로컬 빌드 → ECR Push → EC2 Pull → 실행
```

---

## 🏗️ 1. 로컬에서 이미지 빌드

### 최적화 버전 빌드 (권장)
```bash
# Dockerfile.optimized 사용 (1.9GB)
docker build -f Dockerfile.optimized -t yolo-fastapi:latest .

# 버전 태그 (선택)
docker build -f Dockerfile.optimized -t yolo-fastapi:v1.0.0 .
```

### 이미지 확인
```bash
docker images | grep yolo-fastapi
```

---

## 🚀 2. AWS ECR에 Push

### 2-1. ECR 로그인
```bash
# AWS CLI로 ECR 로그인
aws ecr get-login-password --region ap-northeast-2 | \
docker login --username AWS --password-stdin 123456789012.dkr.ecr.ap-northeast-2.amazonaws.com
```

### 2-2. ECR 리포지토리 생성 (최초 1회)
```bash
# ECR 리포지토리 생성
aws ecr create-repository \
  --repository-name yolo-fastapi \
  --region ap-northeast-2

# 출력 예시:
# {
#   "repository": {
#     "repositoryUri": "123456789012.dkr.ecr.ap-northeast-2.amazonaws.com/yolo-fastapi"
#   }
# }
```

### 2-3. 이미지 태그 및 Push
```bash
# ECR 레지스트리 주소 (예시)
ECR_REGISTRY=123456789012.dkr.ecr.ap-northeast-2.amazonaws.com

# 이미지 태그
docker tag yolo-fastapi:latest $ECR_REGISTRY/yolo-fastapi:latest

# ECR에 Push
docker push $ECR_REGISTRY/yolo-fastapi:latest

# 버전 태그도 함께 push (선택)
docker tag yolo-fastapi:latest $ECR_REGISTRY/yolo-fastapi:v1.0.0
docker push $ECR_REGISTRY/yolo-fastapi:v1.0.0
```

### 자동화 스크립트 (build-push.sh)
```bash
#!/bin/bash
set -e

# 설정
ECR_REGISTRY="123456789012.dkr.ecr.ap-northeast-2.amazonaws.com"
IMAGE_NAME="yolo-fastapi"
VERSION=${1:-latest}  # 첫 번째 인자로 버전 지정, 기본값 latest

echo "🔨 Building image: ${IMAGE_NAME}:${VERSION}"
docker build -f Dockerfile.optimized -t ${IMAGE_NAME}:${VERSION} .

echo "🔐 Logging in to ECR..."
aws ecr get-login-password --region ap-northeast-2 | \
docker login --username AWS --password-stdin ${ECR_REGISTRY}

echo "🏷️  Tagging image..."
docker tag ${IMAGE_NAME}:${VERSION} ${ECR_REGISTRY}/${IMAGE_NAME}:${VERSION}

echo "🚀 Pushing to ECR..."
docker push ${ECR_REGISTRY}/${IMAGE_NAME}:${VERSION}

echo "✅ Done! Image pushed to: ${ECR_REGISTRY}/${IMAGE_NAME}:${VERSION}"
```

**사용법:**
```bash
chmod +x build-push.sh
./build-push.sh           # latest 태그
./build-push.sh v1.0.0   # v1.0.0 태그
```

---

## 💻 3. EC2에서 Pull 및 실행

### 3-1. EC2 준비

#### Docker 설치 (Amazon Linux 2)
```bash
sudo yum update -y
sudo yum install -y docker
sudo service docker start
sudo usermod -a -G docker ec2-user
```

#### Docker Compose 설치
```bash
sudo curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
sudo chmod +x /usr/local/bin/docker-compose
docker-compose --version
```

### 3-2. 프로젝트 파일 전송

```bash
# 로컬에서 EC2로 파일 전송
scp -i your-key.pem docker-compose.yml ec2-user@ec2-ip:/home/ec2-user/
scp -i your-key.pem .env.example ec2-user@ec2-ip:/home/ec2-user/

# EC2에서 .env 설정
ssh -i your-key.pem ec2-user@ec2-ip
cd /home/ec2-user
cp .env.example .env
nano .env  # ECR_REGISTRY, IMAGE_TAG 등 설정
```

### 3-3. ECR 로그인 (EC2)

#### IAM 역할 사용 (권장)
```bash
# EC2에 ECR 읽기 권한이 있는 IAM 역할 연결
# IAM 정책: AmazonEC2ContainerRegistryReadOnly

# ECR 로그인
aws ecr get-login-password --region ap-northeast-2 | \
docker login --username AWS --password-stdin 123456789012.dkr.ecr.ap-northeast-2.amazonaws.com
```

#### 수동 인증 (임시)
```bash
# AWS credentials 설정
aws configure
# Access Key, Secret Key, Region 입력

# ECR 로그인
aws ecr get-login-password --region ap-northeast-2 | \
docker login --username AWS --password-stdin 123456789012.dkr.ecr.ap-northeast-2.amazonaws.com
```

### 3-4. 이미지 Pull 및 실행

```bash
# .env 파일 설정 확인
cat .env

# 이미지 pull 및 실행
docker-compose pull
docker-compose up -d

# 로그 확인
docker-compose logs -f

# 헬스체크
curl http://localhost:8000/healthz
```

---

## 🔄 4. 업데이트 배포

### 로컬에서 새 버전 빌드 및 Push
```bash
# 새 버전 빌드
docker build -f Dockerfile.optimized -t yolo-fastapi:v1.1.0 .

# ECR에 Push
docker tag yolo-fastapi:v1.1.0 $ECR_REGISTRY/yolo-fastapi:v1.1.0
docker push $ECR_REGISTRY/yolo-fastapi:v1.1.0

# latest 태그도 업데이트
docker tag yolo-fastapi:v1.1.0 $ECR_REGISTRY/yolo-fastapi:latest
docker push $ECR_REGISTRY/yolo-fastapi:latest
```

### EC2에서 업데이트
```bash
# .env 파일에서 IMAGE_TAG 변경
nano .env
# IMAGE_TAG=v1.1.0 (또는 latest)

# 새 이미지 pull
docker-compose pull

# 재시작 (무중단 배포)
docker-compose up -d

# 이전 이미지 정리 (선택)
docker image prune -a
```

---

## 🛡️ 5. IAM 권한 설정

### ECR Push용 IAM 정책 (로컬/CI/CD)
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "ecr:GetAuthorizationToken",
        "ecr:BatchCheckLayerAvailability",
        "ecr:GetDownloadUrlForLayer",
        "ecr:PutImage",
        "ecr:InitiateLayerUpload",
        "ecr:UploadLayerPart",
        "ecr:CompleteLayerUpload"
      ],
      "Resource": "arn:aws:ecr:ap-northeast-2:123456789012:repository/yolo-fastapi"
    },
    {
      "Effect": "Allow",
      "Action": "ecr:GetAuthorizationToken",
      "Resource": "*"
    }
  ]
}
```

### ECR Pull용 IAM 역할 (EC2)
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "ecr:GetAuthorizationToken",
        "ecr:BatchGetImage",
        "ecr:GetDownloadUrlForLayer"
      ],
      "Resource": "*"
    }
  ]
}
```

**EC2 인스턴스에 역할 연결:**
1. EC2 콘솔 → 인스턴스 선택 → Actions → Security → Modify IAM role
2. 위 정책이 포함된 역할 선택

---

## 📝 .env 파일 예시

### 로컬 개발 (.env)
```env
# 이미지 설정 (빌드용)
ECR_REGISTRY=123456789012.dkr.ecr.ap-northeast-2.amazonaws.com
IMAGE_TAG=latest

# 모델 설정
MODEL_PATH=best.pt
DEVICE=cpu
IMGSZ=640
CONF=0.25
IOU=0.45

# 동시성
MAX_INFLIGHT=2

# 인증 (테스트)
INBOUND_TOKEN=dev-token
SHARED_SECRET=dev-secret

# 기타
POST_TIMEOUT=60
```

### EC2 프로덕션 (.env)
```env
# 이미지 설정 (ECR pull용)
ECR_REGISTRY=123456789012.dkr.ecr.ap-northeast-2.amazonaws.com
IMAGE_TAG=latest

# 모델 설정
MODEL_PATH=best.pt
DEVICE=cpu
IMGSZ=640
CONF=0.25
IOU=0.45

# 동시성 (EC2 스펙에 맞춰 조정)
MAX_INFLIGHT=4

# 인증 (프로덕션)
INBOUND_TOKEN=${PROD_INBOUND_TOKEN}
SHARED_SECRET=${PROD_SHARED_SECRET}

# 기타
POST_TIMEOUT=60
```

---

## 🔧 트러블슈팅

### 문제 1: ECR 로그인 실패
```bash
# AWS CLI 버전 확인
aws --version

# 최신 버전으로 업데이트
pip install --upgrade awscli

# 권한 확인
aws ecr describe-repositories --region ap-northeast-2
```

### 문제 2: EC2에서 이미지 pull 안됨
```bash
# IAM 역할 확인
aws sts get-caller-identity

# ECR 로그인 다시 시도
aws ecr get-login-password --region ap-northeast-2 | \
docker login --username AWS --password-stdin ${ECR_REGISTRY}

# 네트워크 확인
curl https://${ECR_REGISTRY}
```

### 문제 3: 컨테이너 시작 실패
```bash
# 로그 확인
docker-compose logs

# .env 파일 확인
cat .env

# 수동 실행 테스트
docker run --env-file .env -p 8000:8000 ${ECR_REGISTRY}/yolo-fastapi:latest
```

---

## 📊 배포 체크리스트

### 로컬 (빌드 및 Push)
- [ ] Dockerfile.optimized로 이미지 빌드
- [ ] 이미지 크기 확인 (~1.9GB)
- [ ] ECR 로그인
- [ ] 이미지 태그 지정
- [ ] ECR에 Push
- [ ] ECR 콘솔에서 이미지 확인

### EC2 (Pull 및 실행)
- [ ] Docker, Docker Compose 설치
- [ ] IAM 역할 연결 (ECR 읽기 권한)
- [ ] .env 파일 설정
- [ ] ECR 로그인
- [ ] docker-compose pull
- [ ] docker-compose up -d
- [ ] 헬스체크 확인
- [ ] API 테스트

---

**작성일**: 2025-10-04
