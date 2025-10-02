# 1) 가상환경 & 설치
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
오류 발생시 pip 업데이트

# 2) 환경변수 (필요 시)
$env:MODEL_PATH="C:\path\to\best.pt"
$env:INBOUND_TOKEN="your_inbound_token"  # 백엔드->나 호출 시 Bearer로 검사
$env:SHARED_SECRET="your_shared_secret"  # 내가 콜백 보낼 때 서명

# 3) 서버 실행 (워커 1개 권장)
uvicorn server:app --host 0.0.0.0 --port 8000

# 4) 결과값 소수점 변경 (5번째까지만 나오도록 했습니다 )
_round_floats(out, 5) 이 함수 숫자 바꾸시면됩니다(반올림 안하면 아래처럼나옵니다...)

응답 결과값입니다.

{
  "request_id": "string",
  "results": [
    {
      "source": "https://shutter-heroes-dev.s3.ap-northeast-2.amazonaws.com/images/0/Yungipicus_kizuki_7007829.jpg",
      "result": {
        "task": "classification",
        "speed_ms": {
          "preprocess": 31.108099999983096,
          "inference": 53.7092999984452,
          "postprocess": 0.10320000001229346
        },
        "probs": {
          "top5conf": [
            0.9884992241859436,
            0.007264364045113325,
            0.0013937553158029914,
            0.0009310373570770025,
            0.0009166912641376257
          ]
        },
        "preds": [
          {
            "class_id": 8,
            "label": "Pica_serica",
            "score": 0.9884992241859436
          },
          {
            "class_id": 6,
            "label": "Passer_montanus",
            "score": 0.007264364045113325
          },
          {
            "class_id": 1,
            "label": "Anas_zonorhyncha",
            "score": 0.0013937553158029914
          },
          {
            "class_id": 5,
            "label": "Larus_crassirostris",
            "score": 0.0009310373570770025
          },
          {
            "class_id": 7,
            "label": "Phoenicurus_auroreus",
            "score": 0.0009166912641376257
          }
        ]
      }
    }
  ]
}