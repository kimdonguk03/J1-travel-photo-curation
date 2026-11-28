// 확정: 여행 제목과 만족도(선택)를 받고 보관함에 저장합니다.
import { useState } from 'react'
import { createCuration } from '../api/client'
import type { Album, Curation, Mode, Recommendation } from '../api/types'
import { PhotoCard } from '../components/PhotoCard'

interface Props {
  album: Album
  mode: Mode
  rec: Recommendation | null
  readyAt: string
  finalIds: string[]
  confirmedAt: string
  onSaved: (curation: Curation) => void
  onBack: () => void
}

export function ConfirmScreen({ album, mode, rec, readyAt, finalIds, confirmedAt, onSaved, onBack }: Props) {
  const [title, setTitle] = useState('')
  const [satisfaction, setSatisfaction] = useState<number | null>(null)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const byId = new Map(album.photos.map((p) => [p.photoId, p]))

  async function save() {
    setSaving(true)
    setError(null)
    try {
      const c = await createCuration({
        title: title.trim(),
        albumId: album.albumId,
        mode,
        finalIds,
        draftIds: rec?.draftIds,
        readyAt,
        confirmedAt,
        satisfaction: satisfaction ?? undefined,
      })
      onSaved(c)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
      setSaving(false)
    }
  }

  return (
    <section className="screen confirm">
      <h2 className="screen__title">이 {finalIds.length}장으로 확정할까요?</h2>
      <div className="photo-grid photo-grid--small">
        {finalIds.map((pid) => {
          const p = byId.get(pid)
          return p ? <PhotoCard key={pid} albumId={album.albumId} photo={p} /> : null
        })}
      </div>

      <label className="field">
        <span className="field__label">여행 제목</span>
        <input className="field__input" value={title} maxLength={200} onChange={(e) => setTitle(e.target.value)} placeholder="예: 2026 제주 가족여행" />
      </label>

      <fieldset className="rating">
        <legend>결과가 얼마나 마음에 드나요? (선택)</legend>
        {[1, 2, 3, 4, 5].map((n) => (
          <label key={n} className={`rating__item${satisfaction === n ? ' is-active' : ''}`}>
            <input type="radio" name="satisfaction" checked={satisfaction === n} onChange={() => setSatisfaction(n)} />
            {n}
          </label>
        ))}
      </fieldset>

      {error && <p className="error">{error}</p>}
      <div className="screen__actions">
        <button type="button" className="button" onClick={onBack} disabled={saving}>
          다시 고르기
        </button>
        <button type="button" className="button button--primary" onClick={save} disabled={saving || !title.trim()}>
          {saving ? '저장 중…' : '보관함에 저장'}
        </button>
      </div>
    </section>
  )
}
