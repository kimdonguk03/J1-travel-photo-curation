# backend

Spring Boot 서버입니다. 사진 읽기·썸네일·추천은 같은 PC의 모델 서버(`model/server.py`, `127.0.0.1:8001`)에 HTTP로 맡기고, 이 서버는 업로드, 사진 ID 관리, 큐레이션 보관함, 편집 실험 기록을 맡습니다. 바깥에 공개할 때는 이 서버 포트만 공개하고 모델 서버는 공개하지 않습니다.

```
프론트엔드 ──> backend (Spring, :8080) ──> 모델 서버 (파이썬, 127.0.0.1:8001)
                     └──> DB (H2 파일, ./data/j1db)
```

## 실행

JDK 21 이상이 필요합니다(Gradle은 `gradlew`가 받아 옵니다).

```powershell
# 1) 모델 서버 (--root는 아래 j1.upload-root와 같은 폴더)
cd model
py -m pip install -r requirements.txt
py server.py --root "..\backend\data\uploads" --cache "C:\j1_data\cache"

# 2) 백엔드 (다른 터미널)
cd backend
.\gradlew.bat bootRun
```

- 빌드와 테스트: `.\gradlew.bat build` → `build\libs\curation-0.1.0.jar` (`java -jar`로 실행)
- `JAVA_HOME`이 잘못 잡혀 있으면 `$env:JAVA_HOME = "C:\Program Files\Java\jdk-25.0.2"`처럼 실제 JDK 폴더로 지정합니다.
- 업로드 폴더(`data/uploads`)와 DB(`data/j1db`)는 `.gitignore`로 저장소에 올리지 않습니다.

### Ubuntu (WSL 또는 서버)

```bash
sudo apt update && sudo apt install -y git python3-venv openjdk-21-jdk-headless libheif1
git clone https://github.com/kimdonguk03/J1-travel-photo-curation.git ~/j1 && cd ~/j1

# 모델 서버
python3 -m venv .venv && . .venv/bin/activate
pip install -r model/requirements.txt
mkdir -p ~/j1-data/uploads ~/j1-data/cache
(cd model && python server.py --root ~/j1-data/uploads --cache ~/j1-data/cache) &

# 백엔드 (다른 터미널)
cd ~/j1/backend
./gradlew bootRun --args="--j1.upload-root=$HOME/j1-data/uploads"
```

- 사진과 캐시는 Linux 쪽 폴더(`~/j1-data`)에 둡니다. WSL에서 `/mnt/c/...`(Windows 디스크)에 두면 파일 읽기가 크게 느려집니다.
- WSL에서 띄운 서버는 Windows 브라우저에서도 `http://localhost:8080`으로 열립니다.
- 계속 켜 두는 서버라면 두 프로세스를 systemd 서비스로 등록하면 재부팅 후에도 자동으로 뜹니다.

## 코드 구조

```
src/main/java/com/j1/curation/
├── CurationApplication.java
├── config/      J1Properties (j1.* 설정), WebConfig (CORS), ApiExceptionHandler (오류를 {"detail": ...}로)
├── model/       ModelClient (모델 서버 호출), ModelDtos (모델 서버 JSON), ModelServerException
├── album/       AlbumController·AlbumService: 업로드, 서버 폴더 열기, 썸네일, 추천, zip 내려받기, 세션 정리
└── curation/    Curation (엔티티), CurationRepository, CurationController: 게스트, 보관함, 실험 기록 CSV
```

- 앨범 세션은 메모리에 둡니다(서버를 다시 켜면 다시 불러와야 함). 사진은 `p0001` 같은 ID로만 주고받고, 서버 경로는 프론트엔드에 내보내지 않습니다.
- 업로드한 사진은 마지막 사용 후 `j1.upload-ttl`(기본 6시간)이 지나면 30분마다 도는 정리 작업이 지웁니다. 앨범을 닫으면(`DELETE`) 바로 지웁니다.

## API

모든 오류 응답은 `{"detail": "한국어 안내"}`이고 화면에 그대로 보여도 됩니다.

| 메서드 | 경로 | 설명 |
|---|---|---|
| POST | `/api/auth/guest` | 게스트 ID 발급 `{"userId": "guest-…"}`. 이후 `X-J1-User` 헤더로 보냅니다 |
| POST | `/api/albums/upload?consent=true` | `multipart/form-data`, `files` 여러 개. 원본 그대로 올립니다(촬영 시각 EXIF 유지). 사진이 아닌 파일은 건너뜁니다 |
| POST | `/api/albums/load` | `{"folder": "C:\\..."}` 서버 PC 폴더 열기. `j1.allow-local-folder=true`일 때만 (시연 PC 전용) |
| GET | `/api/albums/{albumId}` | 사진 목록 |
| GET | `/api/albums/{albumId}/photos/{photoId}/thumb?size=512` | 정방향 JPEG (목록 512, 큰 미리보기 1600). `<img src>`로 바로 씁니다 |
| POST | `/api/albums/{albumId}/recommend` | 본문 생략 또는 `{"k": 10}`. 추천 모드에서만 부릅니다 |
| GET | `/api/albums/{albumId}/download?photoIds=p0001,p0005` | 고른 원본 zip (촬영순 번호를 파일 이름 앞에 붙임) |
| DELETE | `/api/albums/{albumId}` | 앨범 닫기. 업로드한 사진을 서버에서 지웁니다 |
| POST | `/api/curations` | 큐레이션 확정 (헤더 `X-J1-User`) |
| GET | `/api/curations`, `/api/curations/{id}` | 내 보관함 |
| GET | `/api/admin/curations.csv` | 편집 실험 기록 CSV. 헤더 `X-J1-Admin`에 환경 변수 `J1_ADMIN_TOKEN` 값을 보냅니다 |

### 응답 예

`POST /api/albums/upload`
```json
{"albumId": "60fa3816-…", "videoCount": 0, "failed": [], "loadedAt": "2026-11-28T08:07:01Z",
 "photos": [{"photoId": "p0001", "name": "IMG_0001.jpg", "takenAt": "2026-10-01T09:10:00.000+09:00"}]}
```

`POST /api/albums/{albumId}/recommend`
```json
{"albumId": "60fa3816-…", "draftIds": ["p0002", "p0004", "…"],
 "clusters": [{"clusterId": "c0001", "photoIds": ["p0002", "p0001"], "representativeId": "p0002"}],
 "missingClusterIds": ["c0007", "c0011"], "ruleVersion": "r4/clip_vision_model_quantized/f183ab07",
 "readyAt": "2026-11-28T08:07:03Z"}
```

- **같은 장면 교체:** 초안 사진이 든 묶음의 `photoIds`(순위순)를 보여 줍니다.
- **빠진 장면 복구:** `missingClusterIds`의 묶음만 모아 보여 줍니다.
- 추천은 300장 기준 첫 실행에 30초~2분이 걸리므로 화면에 진행 중 표시를 둡니다.

`POST /api/curations`
```json
{"title": "제주 여행", "albumId": "60fa3816-…", "mode": "recommend",
 "finalIds": ["p0002", "p0004", "…"], "readyAt": "2026-11-28T08:07:03Z",
 "confirmedAt": "2026-11-28T08:10:41Z", "satisfaction": 4}
```

- `mode`는 `recommend`(추천 편집) 또는 `manual`(직접 고르기)입니다.
- 서버가 앨범 세션에서 불러오기 시작 시각, 추천 초안, `rule_version`, 원래 파일 이름을 채웁니다. 초안 사진과 최종 사진이 함께 저장되므로, 편집 실험의 "복구한 장면"을 나중에 계산할 수 있습니다.
- `readyAt`은 편집 화면이 준비된 시각입니다. 추천 모드는 추천 응답의 `readyAt`, 직접 고르기는 목록을 다 그린 시각을 보냅니다. `confirmedAt`을 생략하면 서버 시각을 씁니다.

## 설정 (`application.properties`)

| 키 | 기본값 | 설명 |
|---|---|---|
| `j1.model-server-url` | `http://127.0.0.1:8001` | 모델 서버 주소 |
| `j1.model-timeout` | `5m` | 모델 서버 응답 대기 |
| `j1.upload-root` | `./data/uploads` | 업로드 폴더. 모델 서버 `--root`와 같아야 합니다 |
| `j1.upload-ttl` | `6h` | 업로드 사진 보관 시간 |
| `j1.allow-local-folder` | `false` | 서버 폴더로 불러오기 (시연 PC에서만 켬. 모델 서버 `--root`에도 그 폴더를 추가) |
| `j1.cors-origins` | `http://localhost:5173` 등 | 프론트엔드 개발 서버 주소 |
| `j1.admin-token` | 환경 변수 `J1_ADMIN_TOKEN` | 실험 기록 CSV용. 저장소에 값을 넣지 않습니다 |

DB는 파일 H2입니다. 다른 DB로 바꾸려면 `spring.datasource.*`와 의존성만 바꾸면 됩니다.

## 업로드한 사진 처리

- 업로드 화면에 "사진은 추천 계산에만 쓰고 서버에서 지운다"는 안내와 동의 체크를 두고, 동의했을 때만 `consent=true`로 올립니다.
- 업로드 사진은 앨범을 닫거나 `j1.upload-ttl`이 지나면 지워집니다. 모델 서버의 특징 캐시(`--cache`)에는 512px 축소본이 남으니 주기적으로 지웁니다.
- 모델 서버(8001)는 이 서버만 부르도록 같은 PC 안에 두고 바깥에 열지 않습니다.

## 아직 없는 것

- 로컬 계정·카카오·구글 로그인: 지금은 게스트 ID(`X-J1-User`)로만 구분합니다. 로그인을 붙이면 `CurationController.owner()`가 사용자 ID를 돌려주게 바꾸면 됩니다.
- 서버 PC 폴더로 최종본 저장: 업로드 배포에서는 zip 내려받기로 대신합니다.
