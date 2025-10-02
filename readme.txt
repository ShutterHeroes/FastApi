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