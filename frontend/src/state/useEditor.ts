// 초안 편집 상태와 동작. 화면(EditorScreen)은 이 훅이 주는 값과 함수만 씁니다.
import { useCallback, useMemo, useState } from 'react'
import type { Album, Cluster, Mode, Photo, Recommendation } from '../api/types'

export type Tab = 'selected' | 'missing' | 'all'

export interface EditorState {
  mode: Mode
  target: number // 최종 장수 (min(10, 사진 수))
  selected: string[] // 고른 사진 ID (고른 순서)
  isSelected: (photoId: string) => boolean
  canConfirm: boolean // target장을 정확히 골랐을 때
  photo: (photoId: string) => Photo
  clusterOf: (photoId: string) => Cluster | null
  /** 같은 묶음의 다른 컷 (순위순). 직접 고르기 모드에서는 빈 배열. */
  alternatives: (photoId: string) => string[]
  /** 고른 사진이 하나도 없는 묶음 (빠진 장면 복구 탭). 대표 컷 기준. */
  missingClusters: Cluster[]
  allPhotos: Photo[] // 촬영순
  toggle: (photoId: string) => void
  /** 고른 사진 from을 to로 바꿉니다 (같은 장면 교체). 순서를 유지합니다. */
  replace: (from: string, to: string) => void
  reset: () => void
  /** 초안에서 바뀐 정도 (추천 모드). */
  diff: { added: number; removed: number }
}

export function useEditor(album: Album, mode: Mode, rec: Recommendation | null, resume?: string[]): EditorState {
  const target = Math.min(10, album.photos.length)
  const initial = useMemo(() => (mode === 'recommend' && rec ? rec.draftIds : []), [mode, rec])
  const [selected, setSelected] = useState<string[]>(() => resume ?? initial)

  const photos = useMemo(() => new Map(album.photos.map((p) => [p.photoId, p])), [album])
  const allPhotos = useMemo(
    () =>
      [...album.photos].sort((a, b) => {
        if (a.takenAt && b.takenAt) return a.takenAt.localeCompare(b.takenAt)
        if (a.takenAt) return -1
        if (b.takenAt) return 1
        return a.name.localeCompare(b.name)
      }),
    [album],
  )
  const clusterByPhoto = useMemo(() => {
    const m = new Map<string, Cluster>()
    rec?.clusters.forEach((c) => c.photoIds.forEach((pid) => m.set(pid, c)))
    return m
  }, [rec])

  const selectedSet = useMemo(() => new Set(selected), [selected])

  const missingClusters = useMemo(
    () => (rec ? rec.clusters.filter((c) => !c.photoIds.some((pid) => selectedSet.has(pid))) : []),
    [rec, selectedSet],
  )

  const toggle = useCallback(
    (pid: string) => setSelected((cur) => (cur.includes(pid) ? cur.filter((x) => x !== pid) : [...cur, pid])),
    [],
  )
  const replace = useCallback(
    (from: string, to: string) =>
      setSelected((cur) => (cur.includes(to) ? cur : cur.map((x) => (x === from ? to : x)))),
    [],
  )

  const diff = useMemo(() => {
    const init = new Set(initial)
    return {
      added: selected.filter((x) => !init.has(x)).length,
      removed: initial.filter((x) => !selectedSet.has(x)).length,
    }
  }, [initial, selected, selectedSet])

  return {
    mode,
    target,
    selected,
    isSelected: (pid) => selectedSet.has(pid),
    canConfirm: selected.length === target,
    photo: (pid) => photos.get(pid) ?? { photoId: pid, name: pid, takenAt: null },
    clusterOf: (pid) => clusterByPhoto.get(pid) ?? null,
    alternatives: (pid) => (clusterByPhoto.get(pid)?.photoIds ?? []).filter((x) => x !== pid),
    missingClusters,
    allPhotos,
    toggle,
    replace,
    reset: () => setSelected(initial),
    diff,
  }
}
