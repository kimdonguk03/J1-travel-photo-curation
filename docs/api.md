# 추천 모듈 API

서버(FastAPI)에서 사진 읽기와 추천을 호출하는 방법입니다. 코드는 `model/j1_image.py`, `model/recommend.py`에 있습니다.

## 의존성과 불러오기

```powershell
py -m pip install numpy Pillow pillow-heif onnxruntime huggingface-hub
```

```python
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1] / "model"))  # backend/ 바로 아래 파일 기준
from j1_image import scan_folder, read_taken_at, jpeg_bytes
from recommend import recommend
```

## 이미지 함수 (`j1_image.py`)

| 함수 | 용도 | 돌려주는 값 |
|---|---|---|
| `scan_folder(root)` | 앨범 불러오기 | `(photos, video_count, failed)`. photos는 `[{"relpath", "path"}]`이고 상대 경로 구분자는 `/`입니다. 사진 확장자는 `j1_image.PHOTO_EXTS`(jpg·jpeg·png·heic·heif·webp)이고 대소문자를 구분하지 않습니다. MOV·MP4는 동영상 수로만 셉니다 |
| `read_taken_at(path)` | 촬영 시각 | `"2026-10-01T14:03:22.370+09:00"` 형식 문자열, 없으면 `None`. EXIF DateTimeOriginal만 씁니다 |
| `jpeg_bytes(path, 512)` | 목록 썸네일 | 정방향 컬러 JPEG 바이트. EXIF를 넣지 않아 브라우저가 회전을 다시 적용하지 않습니다 |
| `jpeg_bytes(path, 1600)` | 큰 미리보기 | 위와 같고 긴 변 최대 1600px. 작은 사진은 키우지 않습니다 |
| `open_upright(path, max_side)` | 직접 가공 | 정방향 RGB `PIL.Image` |

`open_upright`나 `jpeg_bytes`가 예외를 내는 사진(파일 손상 등)은 읽기 실패로 세고 추천 입력에서 뺍니다. HEIC·HEIF 세로 사진은 디코더가 열면서 한 번만 회전합니다. 갤럭시의 '고효율 사진'은 기종에 따라 `.heic`나 `.heif`로 저장되므로, 확장자 목록을 따로 만들지 말고 `PHOTO_EXTS`를 씁니다.

## `recommend(photos, k)`

```python
from recommend import recommend

photos = [
    {"photo_id": "p0001", "relpath": "DCIM/IMG_0001.HEIC", "path": r"C:\...\IMG_0001.HEIC",
     "taken_at": "2026-10-01T14:03:22.370+09:00"},   # read_taken_at 값, 미상이면 None
    ...
]
result = recommend(photos, k, cache_dir=r"C:\j1_data\cache")   # k = min(10, N)
```

반환값:

```json
{
  "clusters": [{"cluster_id": "c0001", "photo_ids": ["p0004", "p0001", "p0002"], "representative_id": "p0004"}],
  "draft_ids": ["p0004", "p0013", "..."],
  "rule_version": "r2/clip_vision_model_quantized/1a2b3c4d"
}
```

| 필드 | 설명 |
|---|---|
| `clusters` | 모든 사진이 정확히 하나의 묶음에 들어갑니다. `photo_ids`는 묶음 안 순위순이고 첫 번째가 `representative_id`입니다. 촬영 시각 미상 사진은 각자 단독 묶음입니다 |
| `draft_ids` | 중복 없는 k장, 촬영순(미상은 끝) |
| `rule_version` | 규칙 코드·파라미터·모델·내용 점수 문장의 지문. 실험 로그에 함께 기록합니다 |

추천 모드에서만 호출합니다. 직접 선택 모드는 추천 계산 없이 시작합니다.

## 운영 시 참고

- **캐시:** `cache_dir`는 입력 폴더 밖에 둡니다. 원본마다 정방향 512px PNG(장당 약 200KB)와 특징 벡터를 저장하고, 같은 파일은 다시 계산하지 않습니다.
- **처리 시간:**
  - 모델은 프로세스당 한 번 올립니다(약 1.5~2초).
  - 휴대폰 크기 사진의 순차 디코딩은 JPEG 약 55ms, HEIC 약 1초이고, 4개 스레드로 병렬 처리합니다.
  - CLIP 추론은 1장당 약 40~90ms입니다.
  - 300장 기준 첫 실행은 JPEG 약 30초, HEIC 약 2분으로 예상하며, 캐시가 있으면 몇 초입니다.
- **비동기 서버:** CPU를 오래 쓰는 함수라 `await run_in_threadpool(recommend, photos, k, cache_dir=...)`처럼 스레드에서 호출합니다.
- **오프라인 실행:**
  - 처음 한 번은 인터넷이 있을 때 실행해 모델(89.1MB)을 받아 둡니다.
  - 오프라인 환경에서는 받아 둔 파일 경로를 `clip_model`로 직접 넘깁니다.
  - 경로 확인: `py -c "import recommend as R; print(R.get_embedder('clip')[0].model_path)"`
- **디코딩 실패:** 추천 중에 디코딩에 실패한 사진은 초안에서 빼고 묶음 목록 끝에 단독 묶음으로만 넣습니다. 남은 사진이 k장보다 적으면 `ValueError`를 냅니다.

## 명령줄

`model/` 폴더에서 실행합니다.

```powershell
py recommend.py --folder "C:\Photos\test_album" --out result.json
py recommend.py photos.json --out result.json
```

`--folder`는 photo_id를 상대 경로로 씁니다. 두 번째 형식은 위의 `photos` 목록을 JSON 파일로 받습니다.
