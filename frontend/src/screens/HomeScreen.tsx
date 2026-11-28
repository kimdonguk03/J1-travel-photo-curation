// 시작 화면: 새 큐레이션 / 보관함.
interface Props {
  onStart: () => void
  onArchive: () => void
}

export function HomeScreen({ onStart, onArchive }: Props) {
  return (
    <section className="screen home">
      <h1 className="home__title">여행 사진, 친구에게 보여줄 10장</h1>
      <p className="home__lead">
        여행 사진을 올리면 비슷한 연사는 한 장으로 정리하고, 일정 전체에서 장면을 고르게 담은 초안 10장을 만들어 드립니다.
        마음에 드는 컷으로 바꾸고, 빠진 순간을 되찾아 완성하세요.
      </p>
      <div className="home__actions">
        <button type="button" className="button button--primary" onClick={onStart}>
          새 큐레이션 만들기
        </button>
        <button type="button" className="button" onClick={onArchive}>
          내 보관함
        </button>
      </div>
    </section>
  )
}
