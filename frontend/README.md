# frontend

React 화면입니다(Vite + React 19 + TypeScript). 기능은 모두 동작하고, 디자인은 기본 상태입니다. **디자인은 `src/styles.css`와 각 화면의 JSX 마크업만 바꾸면 됩니다.** API 호출과 편집 로직은 따로 분리돼 있어 건드리지 않아도 됩니다.

## 실행

Node 20 이상이 필요합니다. 모델 서버와 백엔드를 먼저 띄웁니다([backend/README.md](../backend/README.md)).

```powershell
cd frontend
npm install
npm run dev        # http://localhost:5173 , /api 요청은 백엔드(:8080)로 넘어갑니다
npm run build      # dist/ 에 배포용 파일
npm run lint
```

- 개발 중에는 `vite.config.ts`의 프록시가 `/api`를 백엔드로 넘기므로 CORS 설정이 필요 없습니다.
- 다른 주소의 백엔드를 쓰려면 `.env`에 `VITE_API_BASE=https://백엔드주소`를 두고, 백엔드의 `j1.cors-origins`에 이 화면의 주소를 추가합니다.
- 한 주소로 배포하려면 `npm run build` 결과(`dist/`)를 백엔드의 `src/main/resources/static/`에 넣고 백엔드만 공개합니다.

## 화면 흐름

```
처음 ─> 사진 올리기 ─> 초안 편집 ─> 확정 ─> 완료 (원본 zip, 앨범 닫기)
  └─> 내 보관함
```

| 화면 | 파일 | 하는 일 |
|---|---|---|
| 처음 | `screens/HomeScreen.tsx` | 새 큐레이션, 보관함 |
| 사진 올리기 | `screens/UploadScreen.tsx` | 사진·폴더 고르기, 추천/직접 고르기 모드, 업로드 동의, 진행률, 추천 계산 중 표시 |
| 초안 편집 | `screens/EditorScreen.tsx` | 초안(고른 사진)·빠진 장면·전체 사진 탭, 같은 장면 다른 컷으로 교체, 넣기·빼기, 장수 표시(10/10에서 확정), 초안으로 되돌리기, 크게 보기 |
| 확정 | `screens/ConfirmScreen.tsx` | 여행 제목, 만족도(1~5, 선택), 보관함 저장 |
| 완료 | `screens/DoneScreen.tsx` | 원본 zip 내려받기, 앨범 닫기(서버에서 사진 삭제) |
| 보관함 | `screens/ArchiveScreen.tsx` | 저장한 큐레이션 목록, 사진 이름 목록 |

## 코드 구조

```
src/
├── App.tsx              화면 전환 (상태 하나로 관리, 라우터 없음)
├── styles.css           디자인 전부 (색·글꼴 변수는 맨 위 :root)
├── api/
│   ├── client.ts        백엔드 호출 함수 (화면은 fetch를 직접 쓰지 않음)
│   └── types.ts         요청·응답 타입
├── state/useEditor.ts   편집 로직: 선택, 교체, 빠진 묶음 계산, 초안과의 차이
├── components/          PhotoCard(사진 한 장), Preview(큰 미리보기)
├── screens/             화면 6개
└── utils/format.ts      촬영 시각 표시
```

### 디자인을 입힐 때

- **색·글꼴·모서리·간격:** `styles.css` 맨 위 `:root` 변수부터 바꿉니다.
- **클래스 이름:** 컴포넌트 이름을 따릅니다(`.photo-card`, `.photo-grid`, `.tabs`, `.editor__bar` …). 상태 클래스는 `.is-selected`(고른 사진), `.is-active`(현재 탭·선택한 별점), `.is-complete`(목표 장수 달성), `.is-open`(펼친 보관함 항목)입니다.
- **마크업:** 각 `screens/*.tsx`의 JSX를 자유롭게 바꿔도 됩니다. 버튼의 `onClick`과 `useEditor`가 주는 값(`ed.selected`, `ed.toggle`, `ed.replace`, `ed.missingClusters`, `ed.alternatives` …)만 그대로 연결해 두면 기능은 유지됩니다.
- 썸네일은 `<img src={thumbUrl(albumId, photoId)}>`로 바로 씁니다(목록 512px, 크게 보기 1600px).

## 편집 실험 기록

확정할 때 자동으로 저장되므로 화면에서 따로 할 일은 없습니다.

- **불러오기 시작 시각:** 백엔드가 업로드를 받은 시각
- **화면 준비 시각:** 추천 모드는 추천 응답 시각, 직접 고르기는 업로드 완료 시각
- **확정 시각:** [확정]을 누른 시각
- **그 밖에:** 모드, 초안 사진, 최종 사진, 만족도

관리자는 백엔드의 `/api/admin/curations.csv`로 총시간과 편집 시간을 받습니다.

## 아직 없는 것

- 로컬 계정·카카오·구글 로그인: 지금은 처음 접속할 때 게스트 ID를 받아 브라우저에 저장합니다(`api/client.ts`의 `ensureGuest`).
