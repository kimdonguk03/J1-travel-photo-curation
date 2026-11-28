// 사진 한 장. 디자인은 styles.css의 .photo-card 계열 클래스로 바꿉니다.
import type { ReactNode } from 'react'
import { thumbUrl } from '../api/client'
import type { Photo } from '../api/types'
import { formatTime } from '../utils/format'

interface Props {
  albumId: string
  photo: Photo
  selected?: boolean
  badge?: string // 예: '대표', '+3컷'
  onClick?: () => void // 사진을 눌렀을 때 (기본: 선택 토글)
  onPreview?: () => void // 크게 보기
  actions?: ReactNode // 카드 아래 버튼들
}

export function PhotoCard({ albumId, photo, selected, badge, onClick, onPreview, actions }: Props) {
  return (
    <figure className={`photo-card${selected ? ' is-selected' : ''}`}>
      <button type="button" className="photo-card__image" onClick={onClick} aria-pressed={selected}>
        <img src={thumbUrl(albumId, photo.photoId)} alt={photo.name} loading="lazy" />
        {selected && <span className="photo-card__check" aria-hidden>✓</span>}
        {badge && <span className="photo-card__badge">{badge}</span>}
      </button>
      <figcaption className="photo-card__caption">
        <span className="photo-card__time">{formatTime(photo.takenAt)}</span>
        {onPreview && (
          <button type="button" className="link-button" onClick={onPreview}>
            크게 보기
          </button>
        )}
      </figcaption>
      {actions && <div className="photo-card__actions">{actions}</div>}
    </figure>
  )
}
