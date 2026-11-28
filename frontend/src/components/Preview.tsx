// 큰 미리보기 (1600px). 배경을 누르거나 Esc로 닫습니다.
import { useEffect } from 'react'
import { thumbUrl } from '../api/client'
import type { Photo } from '../api/types'
import { formatTime } from '../utils/format'

interface Props {
  albumId: string
  photo: Photo
  onClose: () => void
}

export function Preview({ albumId, photo, onClose }: Props) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])
  return (
    <div className="preview" role="dialog" aria-modal="true" onClick={onClose}>
      <img className="preview__image" src={thumbUrl(albumId, photo.photoId, 1600)} alt={photo.name} />
      <p className="preview__caption">
        {photo.name} · {formatTime(photo.takenAt)}
      </p>
    </div>
  )
}
