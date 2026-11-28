# backend

Spring 서버입니다. 사진 읽기·썸네일·추천은 같은 PC의 모델 서버(`model/server.py`, `127.0.0.1:8001`)에 HTTP로 맡깁니다. 바깥에 공개할 때는 이 서버 포트만 공개하고 모델 서버는 공개하지 않습니다.

## 맡는 일

- **앨범 불러오기:** 모델 서버 `POST /scan`으로 사진 목록·촬영 시각을 받고 사진 ID를 부여합니다. 목록 썸네일(512px)과 큰 미리보기(1600px)는 모델 서버 `GET /thumb`를 프론트엔드에 전달합니다. 업로드를 받는 배포에서는 업로드 사진을 모델 서버의 `--root` 아래 세션 폴더에 저장한 뒤 그 폴더를 넘깁니다
- **추천:** 추천 모드에서 모델 서버 `POST /recommend` 호출 ([docs/api.md](../docs/api.md))
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

## 모델 서버 연결

백엔드보다 먼저 모델 서버를 띄웁니다.

```powershell
cd model
py -m pip install -r requirements.txt
py server.py --root "C:\j1_data\albums" --cache "C:\j1_data\cache"
```

- 시작할 때 `GET http://127.0.0.1:8001/health`로 떠 있는지 확인합니다.
- 엔드포인트, 요청·응답 예시, Spring `RestClient` 호출 예시, 오류 코드는 [docs/api.md](../docs/api.md)에 있습니다.
- 추천은 첫 실행에 300장 기준 30초~2분이 걸리므로 HTTP 읽기 시간 제한을 넉넉히(예: 5분) 둡니다.
- 큐레이션 기록에는 응답의 `rule_version`을 함께 저장합니다.

## 환경 변수

카카오·구글 Client Secret 같은 비밀값은 `backend/.env`에 두고 저장소에 올리지 않습니다. 필요한 키 이름만 `.env.example`로 공유합니다.
