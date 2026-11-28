// 초안 편집: 고른 사진 / 빠진 장면 / 전체 사진 탭, 같은 장면 다른 컷으로 교체, 추가·빼기, 확정.
import { useState } from 'react'
import type { Album, Mode, Photo, Recommendation } from '../api/types'
import { PhotoCard } from '../components/PhotoCard'
import { Preview } from '../components/Preview'
import { useEditor, type Tab } from '../state/useEditor'

interface Props {
  album: Album
  mode: Mode
  rec: Recommendation | null
  resume?: string[] // 확정 화면에서 돌아왔을 때 이어서 편집할 선택
  onConfirm: (finalIds: string[]) => void
  onCancel: () => void
}

export function EditorScreen({ album, mode, rec, resume, onConfirm, onCancel }: Props) {
  const ed = useEditor(album, mode, rec, resume)
  const [tab, setTab] = useState<Tab>(mode === 'recommend' ? 'selected' : 'all')
  const [swapFor, setSwapFor] = useState<string | null>(null) // 다른 컷을 펼친 사진
  const [preview, setPreview] = useState<Photo | null>(null)
  const id = album.albumId

  const tabs: { key: Tab; label: string; count: number }[] = [
    { key: 'selected', label: mode === 'recommend' ? '초안' : '고른 사진', count: ed.selected.length },
    ...(mode === 'recommend' ? [{ key: 'missing' as Tab, label: '빠진 장면', count: ed.missingClusters.length }] : []),
    { key: 'all', label: '전체 사진', count: ed.allPhotos.length },
  ]

  const alternativesRow = (pid: string) => (
    <div className="alternatives">
      <p className="alternatives__title">같은 장면의 다른 컷 (누르면 바꿉니다)</p>
      <div className="photo-grid photo-grid--small">
        {ed.alternatives(pid).map((alt) => (
          <PhotoCard
            key={alt}
            albumId={id}
            photo={ed.photo(alt)}
            selected={ed.isSelected(alt)}
            onClick={() => {
              if (ed.isSelected(pid)) ed.replace(pid, alt)
              else ed.toggle(alt)
              setSwapFor(null)
            }}
            onPreview={() => setPreview(ed.photo(alt))}
          />
        ))}
      </div>
    </div>
  )

  return (
    <section className="screen editor">
      <header className="editor__bar">
        <div className={`counter${ed.canConfirm ? ' is-complete' : ''}`}>
          {ed.selected.length} / {ed.target}장
        </div>
        {mode === 'recommend' && (ed.diff.added > 0 || ed.diff.removed > 0) && (
          <span className="editor__diff">
            초안에서 {ed.diff.removed}장 빼고 {ed.diff.added}장 넣음
            <button type="button" className="link-button" onClick={ed.reset}>
              초안으로 되돌리기
            </button>
          </span>
        )}
        <div className="editor__actions">
          <button type="button" className="button" onClick={onCancel}>
            그만두기
          </button>
          <button
            type="button"
            className="button button--primary"
            disabled={!ed.canConfirm}
            title={ed.canConfirm ? '' : `${ed.target}장을 고르면 확정할 수 있어요`}
            onClick={() => onConfirm(ed.selected)}
          >
            확정
          </button>
        </div>
      </header>

      <nav className="tabs" role="tablist">
        {tabs.map((t) => (
          <button
            key={t.key}
            type="button"
            role="tab"
            aria-selected={tab === t.key}
            className={`tabs__tab${tab === t.key ? ' is-active' : ''}`}
            onClick={() => setTab(t.key)}
          >
            {t.label} <span className="tabs__count">{t.count}</span>
          </button>
        ))}
      </nav>

      {tab === 'selected' && (
        <div className="photo-grid">
          {ed.selected.length === 0 && <p className="empty">아직 고른 사진이 없습니다. 전체 사진 탭에서 골라 주세요.</p>}
          {ed.selected.map((pid) => {
            const alts = ed.alternatives(pid)
            return (
              <div key={pid} className="photo-grid__item">
                <PhotoCard
                  albumId={id}
                  photo={ed.photo(pid)}
                  selected
                  onClick={() => setPreview(ed.photo(pid))}
                  actions={
                    <>
                      {alts.length > 0 && (
                        <button type="button" className="button button--small" onClick={() => setSwapFor(swapFor === pid ? null : pid)}>
                          다른 컷 {alts.length}
                        </button>
                      )}
                      <button type="button" className="button button--small" onClick={() => ed.toggle(pid)}>
                        빼기
                      </button>
                    </>
                  }
                />
                {swapFor === pid && alternativesRow(pid)}
              </div>
            )
          })}
        </div>
      )}

      {tab === 'missing' && (
        <div className="photo-grid">
          {ed.missingClusters.length === 0 && <p className="empty">모든 장면이 한 장 이상 들어 있습니다.</p>}
          {ed.missingClusters.map((c) => {
            const rep = c.representativeId
            return (
              <div key={c.clusterId} className="photo-grid__item">
                <PhotoCard
                  albumId={id}
                  photo={ed.photo(rep)}
                  badge={c.photoIds.length > 1 ? `${c.photoIds.length}컷` : undefined}
                  onClick={() => ed.toggle(rep)}
                  onPreview={() => setPreview(ed.photo(rep))}
                  actions={
                    <>
                      <button type="button" className="button button--small" onClick={() => ed.toggle(rep)}>
                        넣기
                      </button>
                      {c.photoIds.length > 1 && (
                        <button type="button" className="button button--small" onClick={() => setSwapFor(swapFor === rep ? null : rep)}>
                          다른 컷 보기
                        </button>
                      )}
                    </>
                  }
                />
                {swapFor === rep && alternativesRow(rep)}
              </div>
            )
          })}
        </div>
      )}

      {tab === 'all' && (
        <div className="photo-grid">
          {ed.allPhotos.map((p) => (
            <PhotoCard
              key={p.photoId}
              albumId={id}
              photo={p}
              selected={ed.isSelected(p.photoId)}
              onClick={() => ed.toggle(p.photoId)}
              onPreview={() => setPreview(p)}
            />
          ))}
        </div>
      )}

      {preview && <Preview albumId={id} photo={preview} onClose={() => setPreview(null)} />}
    </section>
  )
}
