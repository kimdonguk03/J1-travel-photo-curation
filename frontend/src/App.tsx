// 화면 흐름: 처음 → 올리기 → 편집 → 확정 → 완료, 그리고 보관함.
import { useEffect, useState } from 'react'
import { closeAlbum, ensureGuest } from './api/client'
import type { Album, Curation, Mode, Recommendation } from './api/types'
import { ArchiveScreen } from './screens/ArchiveScreen'
import { ConfirmScreen } from './screens/ConfirmScreen'
import { DoneScreen } from './screens/DoneScreen'
import { EditorScreen } from './screens/EditorScreen'
import { HomeScreen } from './screens/HomeScreen'
import { UploadScreen } from './screens/UploadScreen'

interface Session {
  album: Album
  mode: Mode
  rec: Recommendation | null
  readyAt: string // 편집 화면이 준비된 시각 (편집 시간 기록용)
}

type View =
  | { name: 'home' }
  | { name: 'upload' }
  | { name: 'editor'; session: Session; resume?: string[] }
  | { name: 'confirm'; session: Session; finalIds: string[]; confirmedAt: string }
  | { name: 'done'; session: Session; curation: Curation }
  | { name: 'archive' }

export default function App() {
  const [view, setView] = useState<View>({ name: 'home' })
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    ensureGuest().catch((e) => setError(e instanceof Error ? e.message : String(e)))
  }, [])

  const home = () => setView({ name: 'home' })

  return (
    <div className="app">
      <header className="app__header">
        <button type="button" className="app__logo" onClick={home}>
          J-1 여행 사진 큐레이션
        </button>
      </header>
      <main className="app__main">
        {error && <p className="error">{error}</p>}
        {view.name === 'home' && (
          <HomeScreen onStart={() => setView({ name: 'upload' })} onArchive={() => setView({ name: 'archive' })} />
        )}
        {view.name === 'upload' && (
          <UploadScreen
            onBack={home}
            onReady={(album, mode, rec, readyAt) => setView({ name: 'editor', session: { album, mode, rec, readyAt } })}
          />
        )}
        {view.name === 'editor' && (
          <EditorScreen
            album={view.session.album}
            mode={view.session.mode}
            rec={view.session.rec}
            resume={view.resume}
            onConfirm={(finalIds) =>
              setView({ name: 'confirm', session: view.session, finalIds, confirmedAt: new Date().toISOString() })
            }
            onCancel={() => {
              if (!window.confirm('편집을 그만두면 올린 사진이 서버에서 지워집니다. 그만둘까요?')) return
              closeAlbum(view.session.album.albumId).catch(() => undefined)
              home()
            }}
          />
        )}
        {view.name === 'confirm' && (
          <ConfirmScreen
            album={view.session.album}
            mode={view.session.mode}
            rec={view.session.rec}
            readyAt={view.session.readyAt}
            finalIds={view.finalIds}
            confirmedAt={view.confirmedAt}
            onBack={() => setView({ name: 'editor', session: view.session, resume: view.finalIds })}
            onSaved={(curation) => setView({ name: 'done', session: view.session, curation })}
          />
        )}
        {view.name === 'done' && (
          <DoneScreen
            album={view.session.album}
            curation={view.curation}
            onHome={home}
            onArchive={() => setView({ name: 'archive' })}
          />
        )}
        {view.name === 'archive' && <ArchiveScreen onBack={home} />}
      </main>
    </div>
  )
}
