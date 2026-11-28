# 모델 서버 API

백엔드(Spring)는 사진 읽기, 썸네일, 추천을 **모델 서버**(`model/server.py`, 파이썬)에 HTTP로 맡깁니다. 두 서버는 같은 PC에서 돌고, 모델 서버는 바깥에 공개하지 않습니다.

```
프론트엔드 (React)  ──>  백엔드 (Spring: 로그인, 보관함, 업로드, 최종본 저장, 기록)
                              │  HTTP, 127.0.0.1:8001
                              └──>  모델 서버 (사진 스캔, 썸네일, 추천)
```

사진 처리를 모델 서버가 맡는 이유는 두 가지입니다. 아이폰·갤럭시의 HEIC를 자바 기본 라이브러리로 읽기 어렵고, 촬영 시각(EXIF)과 회전 처리가 추천 규칙과 정확히 같아야 하기 때문입니다.

## 실행

```powershell
cd model
py -m pip install -r requirements.txt
py server.py --root "C:\j1_data\albums" --cache "C:\j1_data\cache"
```

- 기본 주소는 `http://127.0.0.1:8001`입니다. `--port`로 바꿀 수 있습니다.
- `http://127.0.0.1:8001/docs`에서 모든 엔드포인트를 브라우저로 직접 호출해 볼 수 있습니다(자동 생성 문서).
- **`--root`:** 사진을 읽어도 되는 폴더입니다. 이 폴더와 그 하위 밖의 경로는 403으로 거부합니다. 여러 번 줄 수 있습니다. 업로드를 받는 배포에서는 업로드 저장 폴더를 `--root`로 주세요.
- **`--cache`:** 특징 캐시 폴더입니다. 사진 폴더 밖에 둡니다. 원본마다 정방향 512px PNG(장당 약 200KB)와 특징 벡터를 저장하고, 같은 파일은 다시 계산하지 않습니다.
- 처음 실행할 때 CLIP 모델(약 89MB)을 내려받습니다. 오프라인 PC에서는 받아 둔 파일을 `--clip-model`로 넘깁니다.
- 시작할 때 모델을 올리고(약 2초) `rule_version`을 출력합니다.

## 엔드포인트

### `GET /health`

백엔드가 시작할 때 한 번 불러 모델 서버가 떠 있는지 확인합니다.

```json
{"status": "ok", "model_loaded": true, "embedder": "clip",
 "rule_version": "r4/clip_vision_model_quantized/f183ab07",
 "photo_exts": [".heic", ".heif", ".jpeg", ".jpg", ".png", ".webp"], "roots": ["C:\\j1_data\\albums"]}
```

### `POST /scan`

앨범 폴더를 읽어 사진 목록을 돌려줍니다. 하위 폴더도 읽고, 숨김 파일은 뺍니다. 동영상(MOV·MP4)은 개수만 셉니다.

요청:
```json
{"folder": "C:\\j1_data\\albums\\jeju_trip"}
```

응답:
```json
{
  "photos": [
    {"photo_id": "DCIM/IMG_0001.HEIC", "relpath": "DCIM/IMG_0001.HEIC",
     "path": "C:\\j1_data\\albums\\jeju_trip\\DCIM\\IMG_0001.HEIC",
     "taken_at": "2026-10-01T14:03:22.370+09:00"}
  ],
  "video_count": 2,
  "failed": [{"relpath": "broken.jpg", "reason": "열기 실패: UnidentifiedImageError"}]
}
```

| 필드 | 설명 |
|---|---|
| `photo_id` | 상대 경로를 그대로 씁니다. 백엔드가 자체 ID를 쓰려면 `/recommend`에 `photos`로 넘길 때 바꿔도 됩니다(앨범 안에서 겹치지만 않으면 됨) |
| `taken_at` | EXIF 촬영 시각(ISO 8601). 없으면 `null`이고, 이런 사진은 추천에서 단독 묶음이 됩니다 |
| `failed` | 헤더를 열 수 없는 파일. 읽기 실패로 화면에 안내합니다 |

### `GET /thumb?path=...&size=512`

정방향 컬러 JPEG를 돌려줍니다(`image/jpeg`). HEIC도 JPEG로 바꿔 줍니다. EXIF를 넣지 않아 브라우저가 회전을 다시 적용하지 않습니다.

| 파라미터 | 설명 |
|---|---|
| `path` | `/scan`이 돌려준 `path` |
| `size` | 긴 변 픽셀. 목록 썸네일 512, 큰 미리보기 1600 (64~1600). 작은 사진은 키우지 않습니다 |

백엔드는 이 응답을 프론트엔드에 그대로 전달하면 됩니다. 사진 절대 경로를 브라우저에 노출하지 않도록, 프론트엔드에는 `photo_id`로 요청받고 백엔드가 경로로 바꿔 부르는 것을 권합니다.

### `POST /recommend`

추천 초안과 묶음을 돌려줍니다. `folder`와 `photos` 중 하나를 줍니다.

요청 (폴더째):
```json
{"folder": "C:\\j1_data\\albums\\jeju_trip", "k": 10}
```

요청 (이미 스캔한 목록):
```json
{"photos": [ /scan의 photos 그대로 ], "k": 10}
```

응답:
```json
{
  "clusters": [{"cluster_id": "c0001", "photo_ids": ["p0004", "p0001", "p0002"], "representative_id": "p0004"}],
  "draft_ids": ["p0004", "p0013", "..."],
  "rule_version": "r4/clip_vision_model_quantized/f183ab07"
}
```

| 필드 | 설명 |
|---|---|
| `k` | 초안 장수. 생략하면 min(10, 읽을 수 있는 사진 수) |
| `clusters` | 모든 사진이 정확히 하나의 묶음에 들어갑니다. `photo_ids`는 묶음 안 순위순이고 첫 번째가 대표 컷입니다. '같은 장면 교체'는 이 목록을, '미포함 묶음'은 `draft_ids`에 사진이 하나도 없는 묶음을 쓰면 됩니다 |
| `draft_ids` | 중복 없는 k장, 촬영순(시각 미상은 끝) |
| `rule_version` | 추천 규칙·파라미터·모델의 지문. 큐레이션 기록과 평가 로그에 함께 저장합니다 |

추천 모드에서만 호출합니다. 직접 선택 모드는 추천 없이 `/scan`과 `/thumb`만 씁니다.

### 오류

응답 본문은 `{"detail": "안내 문구"}`입니다. 문구는 한국어라 화면에 그대로 보여 줘도 됩니다.

| 코드 | 경우 |
|---|---|
| 400 | 폴더·사진 파일이 아님, `folder`와 `photos`를 둘 다 주거나 둘 다 안 줌, `photo_id` 중복, 읽을 수 있는 사진이 k장보다 적음 |
| 403 | `--root` 밖의 경로 |
| 404 | 폴더·파일이 없음 |
| 422 | 요청 형식이 틀림, 또는 썸네일을 만들 수 없는 손상 파일 |

## 처리 시간과 호출 방식

- 휴대폰 사진 디코딩은 JPEG 약 55ms, HEIC 약 1초이고 4개 스레드로 병렬 처리합니다. CLIP 추론은 1장당 약 40~90ms입니다.
- 300장 기준 첫 추천은 JPEG 약 30초, HEIC 약 2분입니다. 캐시가 있으면 몇 초입니다.
- 모델 서버는 추천을 한 번에 하나씩 처리합니다. 백엔드의 HTTP 클라이언트 읽기 시간 제한을 넉넉히(예: 5분) 두고, 화면에는 진행 중 표시를 보여 주세요.

Spring에서 호출하는 예 (`RestClient`, Spring Boot 3.2 이상):

```java
RestClient model = RestClient.builder()
        .baseUrl("http://127.0.0.1:8001")
        .requestFactory(new SimpleClientHttpRequestFactory() {{ setReadTimeout(300_000); }})
        .build();

Map<String, Object> scan = model.post().uri("/scan")
        .body(Map.of("folder", albumDir)).retrieve().body(new ParameterizedTypeReference<>() {});

Map<String, Object> rec = model.post().uri("/recommend")
        .body(Map.of("photos", scan.get("photos"), "k", 10)).retrieve().body(new ParameterizedTypeReference<>() {});

byte[] jpeg = model.get().uri(u -> u.path("/thumb").queryParam("path", photoPath).queryParam("size", 512).build())
        .retrieve().body(byte[].class);
```

명령줄로 확인하는 예:

```powershell
curl.exe http://127.0.0.1:8001/health
curl.exe -X POST http://127.0.0.1:8001/recommend -H "Content-Type: application/json" -d "{\"folder\": \"C:\\\\j1_data\\\\albums\\\\jeju_trip\", \"k\": 10}"
```

## 업로드를 받는 배포

다른 사람이 웹으로 써 보게 하려면 사진을 폴더 경로가 아니라 업로드로 받습니다.

1. 백엔드가 업로드한 사진을 `--root` 아래의 세션별 임시 폴더(예: `C:\j1_data\uploads\<세션 ID>\`)에 원래 파일 이름으로 저장합니다. 촬영 시각을 읽으려면 원본 파일(EXIF 포함)을 그대로 받아야 합니다. 브라우저에서 줄여 올리면 EXIF가 지워질 수 있습니다.
2. 그 폴더로 `/scan`, `/recommend`를 부릅니다.
3. 최종본을 내려준 뒤 임시 폴더를 지웁니다. 캐시 폴더에는 512px 축소본이 남으므로 같이 정리합니다.
4. 사진이 서버로 올라온다는 점과 처리 후 지운다는 점을 화면에 안내하고 동의를 받습니다.
5. 바깥에는 백엔드 포트만 공개합니다(예: 터널). 모델 서버(8001)는 공개하지 않습니다.

## 파이썬에서 직접 쓰기

백엔드 없이 실험할 때는 모듈을 직접 불러도 됩니다.

```python
from recommend import photos_from_folder, recommend
photos, video_count, failed = photos_from_folder(r"C:\Photos\jeju_trip")
result = recommend(photos, 10, cache_dir=r"C:\j1_data\cache")
```

명령줄:

```powershell
py recommend.py --folder "C:\Photos\test_album" --out result.json
```
