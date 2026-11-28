// 앨범 올리기: 사진 고르기 → 동의 → 모드 선택 → 업로드 → (추천 모드면) 추천 계산.
import { useState } from 'react'
import { recommend, uploadAlbum } from '../api/client'
import type { Album, Mode, Recommendation } from '../api/types'

interface Props {
  onReady: (album: Album, mode: Mode, rec: Recommendation | null, readyAt: string) => void
  onBack: () => void
}

type Phase = 'pick' | 'uploading' | 'recommending'

const ACCEPT = 'image/jpeg,image/png,image/webp,image/heic,image/heif,.heic,.heif,.jpg,.jpeg,.png,.webp'

export function UploadScreen({ onReady, onBack }: Props) {
  const [files, setFiles] = useState<File[]>([])
  const [consent, setConsent] = useState(false)
  const [mode, setMode] = useState<Mode>('recommend')
  const [phase, setPhase] = useState<Phase>('pick')
  const [progress, setProgress] = useState(0)
  const [error, setError] = useState<string | null>(null)

  const totalMB = files.reduce((s, f) => s + f.size, 0) / 1024 / 1024
  const canStart = files.length > 0 && consent && phase === 'pick'

  async function start() {
    setError(null)
    try {
      setPhase('uploading')
      const album = await uploadAlbum(files, consent, setProgress)
      if (mode === 'recommend') {
        setPhase('recommending')
        const rec = await recommend(album.albumId)
        onReady(album, mode, rec, rec.readyAt)
      } else {
        onReady(album, mode, null, new Date().toISOString())
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
      setPhase('pick')
    }
  }

  return (
    <section className="screen upload">
      <h2 className="screen__title">여행 사진 올리기</h2>

      <div className="upload__pick">
        <label className="file-input">
          <span className="button">사진 고르기</span>
          <input type="file" multiple accept={ACCEPT} onChange={(e) => setFiles(Array.from(e.target.files ?? []))} />
        </label>
        <label className="file-input">
          <span className="button">폴더째 고르기</span>
          <input
            type="file"
            multiple
            // 비표준 속성이지만 크롬·엣지·사파리에서 폴더 선택을 엽니다
            webkitdirectory=""
            onChange={(e) => setFiles(Array.from(e.target.files ?? []))}
          />
        </label>
        <p className="upload__summary">
          {files.length > 0 ? `${files.length}개 파일 · ${totalMB.toFixed(0)}MB` : '아직 고른 사진이 없습니다.'}
        </p>
        <p className="hint">
          메신저로 받은 사진은 촬영 시각이 지워져 있을 수 있습니다. 휴대폰 갤러리의 원본을 올려 주세요.
        </p>
      </div>

      <fieldset className="upload__mode">
        <legend>시작 방법</legend>
        <label>
          <input type="radio" name="mode" checked={mode === 'recommend'} onChange={() => setMode('recommend')} />
          추천 초안에서 시작
        </label>
        <label>
          <input type="radio" name="mode" checked={mode === 'manual'} onChange={() => setMode('manual')} />
          처음부터 직접 고르기
        </label>
      </fieldset>

      <label className="upload__consent">
        <input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} />
        사진을 서버에 올려 추천 계산에만 쓰고, 앨범을 닫거나 6시간이 지나면 서버에서 지우는 것에 동의합니다.
      </label>

      {phase === 'uploading' && (
        <div className="status">
          <progress value={progress} max={1} /> 올리는 중 {Math.round(progress * 100)}%
        </div>
      )}
      {phase === 'recommending' && (
        <div className="status">
          <span className="spinner" aria-hidden /> 초안을 만드는 중입니다. 사진이 많으면 1~2분 걸릴 수 있어요.
        </div>
      )}
      {error && <p className="error">{error}</p>}

      <div className="screen__actions">
        <button type="button" className="button" onClick={onBack} disabled={phase !== 'pick'}>
          뒤로
        </button>
        <button type="button" className="button button--primary" onClick={start} disabled={!canStart}>
          시작하기
        </button>
      </div>
    </section>
  )
}
