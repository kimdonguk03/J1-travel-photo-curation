// 저장 완료: 원본 내려받기, 앨범 닫기(서버에서 사진 삭제).
import { useState } from 'react'
import { closeAlbum, downloadUrl } from '../api/client'
import type { Album, Curation } from '../api/types'
import { PhotoCard } from '../components/PhotoCard'

interface Props {
  album: Album
  curation: Curation
  onHome: () => void
  onArchive: () => void
}

export function DoneScreen({ album, curation, onHome, onArchive }: Props) {
  const [closed, setClosed] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const byId = new Map(album.photos.map((p) => [p.photoId, p]))

  async function close(next: () => void) {
    setError(null)
    try {
      if (!closed) await closeAlbum(album.albumId)
      setClosed(true)
      next()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  return (
    <section className="screen done">
      <h2 className="screen__title">“{curation.title}” 저장 완료</h2>
      <div className="photo-grid highlight">
        {curation.finalIds.map((pid) => {
          const p = byId.get(pid)
          return p && !closed ? <PhotoCard key={pid} albumId={album.albumId} photo={p} /> : null
        })}
      </div>
      {!closed && (
        <a className="button button--primary" href={downloadUrl(album.albumId, curation.finalIds)} download>
          원본 {curation.finalIds.length}장 내려받기 (zip)
        </a>
      )}
      <p className="hint">내려받은 뒤 앨범을 닫으면 올린 사진이 서버에서 바로 지워집니다. 닫지 않아도 6시간 뒤 지워집니다.</p>
      {error && <p className="error">{error}</p>}
      <div className="screen__actions">
        <button type="button" className="button" onClick={() => close(onArchive)}>
          앨범 닫고 보관함으로
        </button>
        <button type="button" className="button" onClick={() => close(onHome)}>
          앨범 닫고 처음으로
        </button>
      </div>
    </section>
  )
}
