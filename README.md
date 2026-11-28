# J-1 AI 기반 여행 사진 큐레이션 서비스

여행에서 찍은 수백 장의 사진 중, **여행에 함께하지 못한 친구에게 보여줄 10장**을 고르는 서비스입니다.
서비스가 먼저 초안 10장을 만들면, 사용자는 마음에 드는 컷으로 바꾸거나 초안에서 빠진 순간을 찾아 최종본을 저장합니다.
저장한 큐레이션은 계정별 보관함에서 다시 볼 수 있습니다.

> AI Product Challenge 출품작

## 왜 만드나

여행 사진을 친구에게 보여주려면, 비슷한 연사 중에서 한 장을 고르고 일정 전체에서 장면을 고르게 담아야 합니다. 둘 다 시간이 많이 드는 일입니다.

이 서비스는 자동으로 고르는 것에서 끝나지 않고 **초안을 고치는 과정**에 집중합니다.

- **같은 장면 교체:** 초안의 사진을 같은 장면의 다른 컷으로 바로 바꿉니다.
- **빠진 장면 복구:** 초안에 한 장도 들어가지 않은 묶음('미포함 묶음')만 모아 보여줍니다. 그래서 전체 사진을 처음부터 다시 훑지 않아도 저녁 식사처럼 빠진 순간을 찾아 넣을 수 있습니다.

## 사용 흐름

1. **보관함:** 처음 접속하면 게스트로 들어가고, 같은 브라우저에서 이전에 저장한 큐레이션을 다시 볼 수 있습니다.
2. **앨범 선택:** 사진 폴더 경로를 넣고 불러옵니다. 기본은 추천 모드이고, 처음부터 직접 고르는 모드도 있습니다.
3. **초안 편집:** 같은 묶음의 다른 컷으로 교체하거나, 미포함 묶음과 원본 전체에서 사진을 추가·제외합니다.
4. **최종 확정 및 보관:** 저장 위치와 여행 제목을 정하면 원본을 새 폴더에 촬영순으로 복사하고 보관함에 기록합니다.

지원 형식은 JPG·JPEG·PNG·HEIC·HEIF·WebP입니다(확장자 대소문자 무관). 원본 폴더는 읽기만 하고 수정하지 않습니다.

## 추천 방식

**사전학습된 CLIP 이미지 임베딩, 공개된 미적 점수 모델, EXIF 촬영 시각**을 함께 씁니다. CLIP은 고정하고, 연사 중 한 장 고르기만 외부 사람 선호 데이터(Photo Triage)로 작은 선형 순위 모델을 학습해 씁니다.

1. **시간 구간:** 촬영 시각순으로 직전 사진과 30초, 구간 첫 사진과 120초 안의 사진을 한 구간으로 봅니다.
2. **유사 컷 묶기:** 같은 구간에서 CLIP 유사도가 0.92 이상인 사진을 '한 장만 남겨도 되는 컷'으로 묶습니다. 같은 해변이라도 단체사진과 바다 풍경은 따로 남습니다.
3. **내용·미적 점수:** CLIP으로 사진을 문장('친구들 단체사진', '관광지', '멋진 풍경', '도로', '스크린샷' 등)과 비교해, 보여줄 만한 내용은 올리고 도로·문서·흐린 사진은 내립니다. 사람이 매긴 미적 점수로 학습된 공개 모델(LAION-Aesthetics)로 보기 좋은 사진도 올립니다.
4. **대표 컷:** 묶음마다 사람이 더 좋아할 컷을 대표로 씁니다. 공개된 사람 선호 데이터(Photo Triage)로 학습한 순위 모델이 선명도, 미적 점수, 내용, CLIP 벡터를 함께 보고 고르며, 선명도의 비중이 가장 큽니다. 선명도는 방향별로 재서 한 방향으로만 흔들린 사진도 잡습니다.
5. **10장 고르기:** 날짜별로 자리를 나누고, 많이 찍은 장면, 내용 점수가 높은 장면, 선명한 장면, 보기 좋은 장면을 같은 비중으로 우선하되 이미 고른 사진과 비슷한 장면은 감점합니다(MMR).

자세한 규칙과 평가 방법은 [docs/recommendation.md](docs/recommendation.md)에, 지금까지의 실험 결과와 남은 검증 계획은 [docs/experiments.md](docs/experiments.md)에 있습니다.

## 구성

모든 구성 요소가 한 PC(또는 한 서버)에서 실행됩니다. 모델 서버는 백엔드만 부르고 바깥에 공개하지 않습니다.

```
frontend (React)  ──HTTP──>  backend (Spring)  ──>  DB (보관함, 계정)
                                   │  HTTP, 127.0.0.1:8001
                                   └──>  model server (파이썬: 사진 스캔, 썸네일, CLIP 추천)
```

사진 읽기(HEIC 포함), 촬영 시각, 회전, 추천은 모두 모델 서버가 맡습니다. 백엔드가 모델 서버를 부르는 방법은 [docs/api.md](docs/api.md)에 있습니다.

## 저장소 구조

```
├── frontend/      React 화면
├── backend/       Spring 서버: 게스트, 보관함, 업로드, 최종본 저장
├── model/         추천 모듈과 평가 도구
│   ├── j1_image.py      사진 읽기: 폴더 스캔, 촬영 시각, 정방향 이미지, 썸네일
│   ├── recommend.py     추천: recommend(photos, k)
│   ├── server.py        모델 서버 (HTTP: /scan, /thumb, /recommend)
│   ├── curation.py      개발 앨범 점검 화면
│   ├── pair_check.py    사진 쌍 표시로 유사도 기준값 점검
│   ├── labeler.py       평가용 정답(owner.csv) 수집 페이지
│   ├── evaluate.py      추천 방식 비교 평가
│   ├── draft_review.py  초안 사진 평가 페이지 (수용률, 흔들림)
│   ├── triage_eval.py   Photo Triage 사람 선호 데이터로 대표 컷 고르기 검증과 순위 모델 학습
│   ├── ablation.py      기여도 비교 (점수를 하나씩 끄고 평가)
│   ├── edit_eval.py     편집 실험 분석 (시간 비교, 복구한 장면)
│   ├── triage_ranker.npz  학습한 대표 컷 순위 모델 가중치
│   ├── aesthetic_head.py / aesthetic_vit_b_32.npz  LAION 미적 점수 선형층 (MIT)
│   ├── params.json      추천 규칙 파라미터
│   ├── content_prompts.py / .npz  내용 점수 문장과 그 CLIP 벡터
│   ├── requirements.txt
│   └── tests/
├── notebooks/
│   └── experiments.ipynb  Colab 개발 실험 (처리 시간, 기준값 점검, 정답 페이지, 비교 평가, 초안 평가, 외부 검증)
└── docs/
    ├── api.md             모델 서버 API (백엔드에서 호출하는 방법)
    ├── recommendation.md  추천 규칙과 평가 방법
    ├── experiments.md     실험 기록과 남은 검증
    ├── results/           외부 검증 결과 (수치만)
    └── presentation/      발표 자료 초안 (모델 개선 과정, 평가 결과, 한계와 화면의 역할)
```

## 시작하기

### 추천 모듈

```powershell
cd model
py -m pip install -r requirements.txt
py recommend.py --folder "C:\Photos\test_album" --out result.json
py tests/test_rules.py
```

처음 실행할 때 CLIP 모델(약 89MB)을 내려받습니다.

### 모델 서버

```powershell
cd model
py server.py --root "C:\j1_data\albums" --cache "C:\j1_data\cache"
```

`http://127.0.0.1:8001/docs`에서 엔드포인트를 직접 호출해 볼 수 있습니다. 자세한 내용은 [docs/api.md](docs/api.md)에 있습니다.

### Colab 실험

Google Drive의 사진으로 실험하려면 [notebooks/experiments.ipynb](notebooks/experiments.ipynb)를 Colab에서 엽니다([바로 열기](https://colab.research.google.com/github/kimdonguk03/J1-travel-photo-curation/blob/main/notebooks/experiments.ipynb)). 처리 시간, 기준값 점검, 평가 앨범 정답 페이지, 비교 평가, 초안 평가, 외부 검증을 순서대로 실행할 수 있습니다.

### 백엔드

모델 서버를 먼저 띄운 뒤 `backend`에서 `.\gradlew.bat bootRun`으로 실행합니다(JDK 21 이상). API와 설정은 [backend/README.md](backend/README.md)에 있습니다.

### 화면

[frontend/README.md](frontend/README.md)를 참고하세요.

## 평가

지금까지의 결과와 다음 단계는 [docs/experiments.md](docs/experiments.md)에 정리돼 있습니다.

- **추천 결과:** 평가 앨범 2~3개의 주인이 추천을 보기 전에 중요 장면과 직접 고른 10장을 표시합니다. 이를 기준으로 촬영 순번 균등 추출, 시간만 쓴 묶기, 시간+CLIP 묶기를 비교하고, 초안 사진의 선명도도 함께 봅니다.
- **초안 평가:** 정답을 받은 뒤, 주인이 여러 방식의 초안 사진을 어느 방식인지 모르게 섞어 놓은 화면에서 사진마다 '최종 10장에 넣어도 되는지', '흔들림·흐림이 눈에 띄는지', '미리 정한 중요 장면 중 무엇을 대신 보여줄 수 있는지'를 따로 답합니다.
- **편집 경험:** 참가자 본인의 앨범으로 직접 선택과 추천 편집을 순서를 바꿔 수행합니다. 불러오기부터 확정까지의 시간과 만족도(1~5점)를 개인별로 보고합니다.

## 팀

| 역할 | 맡은 일 |
|---|---|
| 모델·평가·백엔드 | 모델 선정, 전처리·추론, 추천 규칙, 성능 평가, 모델 서버 (`model/`), Spring 서버와 배포 (`backend/`) |
| 프론트엔드 | React 화면, UX (`frontend/`) |

## 데이터와 개인정보

참가자 사진은 저장소에 올리지 않습니다. 사진 파일, 실행 결과·캐시(`j1_out/`), 정답 파일, 서버 비밀값(`.env`), 로컬 DB는 `.gitignore`로 제외합니다. 앨범은 사용 동의를 받은 경우에만 평가에 씁니다.
