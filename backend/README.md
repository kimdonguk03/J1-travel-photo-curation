# backend

FastAPI 서버입니다. 시연 PC의 `127.0.0.1`에서만 실행합니다.

## 맡는 일

- **앨범 불러오기:** 폴더 스캔, 사진 ID 부여, 목록 썸네일(512px)과 큰 미리보기(1600px) 제공. 지원 확장자는 `model/j1_image.py`의 `PHOTO_EXTS`(jpg·jpeg·png·heic·heif·webp)를 그대로 씁니다
- **추천:** 추천 모드에서 추천 모듈 호출 ([docs/api.md](../docs/api.md))
- **최종본 저장:** 경로 검사, 장수·중복 검증, 촬영순 번호를 붙인 원본 복사
- **인증:** 로컬 아이디·비밀번호, 카카오·구글 OAuth, 게스트
- **큐레이션 보관함:** SQLite(`app.db`)
- **평가 로그:** 평가 모드의 세션별 기록

## API (계획)

| 메서드 | 경로 | 설명 |
|---|---|---|
| POST | `/api/auth/register`, `/api/auth/login` | 로컬 회원가입·로그인 |
| GET | `/api/auth/oauth/{provider}/url`, `/api/auth/oauth/{provider}/callback` | 카카오·구글 로그인 |
| POST | `/api/auth/guest` | 게스트 세션 |
| GET | `/api/curations`, `/api/curations/{curation_id}` | 보관함 목록·상세 |
| POST | `/api/albums/load` | 앨범 불러오기 (추천/직접 선택) |
| GET | `/api/albums/{album_id}/photos/{photo_id}/thumb`, `.../preview` | 썸네일·미리보기 JPEG |
| POST | `/api/albums/{album_id}/export` | 최종본 저장 |
| POST | `/api/sessions/{session_id}/complete` | 평가 모드 저장 완료 통지 |

## 추천 모듈 불러오기

추천 코드는 저장소 루트의 `model/` 폴더에 있습니다.

```python
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1] / "model"))  # backend/ 바로 아래 파일 기준
from j1_image import scan_folder, read_taken_at, jpeg_bytes
from recommend import recommend
```

## 환경 변수

카카오·구글 Client Secret 같은 비밀값은 `backend/.env`에 두고 저장소에 올리지 않습니다. 필요한 키 이름만 `.env.example`로 공유합니다.
