// 내 보관함: 저장한 큐레이션 목록과 상세. 사진은 서버에서 지워지므로 파일 이름과 기록만 보여 줍니다.
import { useEffect, useState } from 'react'
import { listCurations } from '../api/client'
import type { Curation } from '../api/types'
import { formatTime } from '../utils/format'

interface Props {
  onBack: () => void
}

export function ArchiveScreen({ onBack }: Props) {
  const [items, setItems] = useState<Curation[] | null>(null)
  const [open, setOpen] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    listCurations().then(setItems).catch((e) => setError(e instanceof Error ? e.message : String(e)))
  }, [])

  return (
    <section className="screen archive">
      <h2 className="screen__title">내 보관함</h2>
      {error && <p className="error">{error}</p>}
      {items === null && !error && <p className="status">불러오는 중…</p>}
      {items?.length === 0 && <p className="empty">아직 저장한 큐레이션이 없습니다.</p>}
      <ul className="archive__list">
        {items?.map((c) => (
          <li key={c.id} className={`archive__item${open === c.id ? ' is-open' : ''}`}>
            <button type="button" className="archive__head" onClick={() => setOpen(open === c.id ? null : c.id)}>
              <span className="archive__title">{c.title}</span>
              <span className="archive__meta">
                {formatTime(c.createdAt)} · {c.finalIds.length}장 · {c.mode === 'recommend' ? '추천 편집' : '직접 고름'}
              </span>
            </button>
            {open === c.id && (
              <ol className="archive__photos">
                {c.photoNames.map((n) => (
                  <li key={n}>{n}</li>
                ))}
              </ol>
            )}
          </li>
        ))}
      </ul>
      <div className="screen__actions">
        <button type="button" className="button" onClick={onBack}>
          처음으로
        </button>
      </div>
    </section>
  )
}
