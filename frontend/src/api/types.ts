// 백엔드(Spring) API의 요청·응답 형식. backend/README.md의 API 절과 같습니다.

export type Mode = 'recommend' | 'manual'

export interface Photo {
  photoId: string // p0001 형식
  name: string // 앨범 안 상대 경로 (원래 파일 이름)
  takenAt: string | null // 촬영 시각 ISO 8601, 없으면 null
}

export interface Album {
  albumId: string
  photos: Photo[]
  videoCount: number
  failed: { name: string; reason: string }[]
  loadedAt: string
}

export interface Cluster {
  clusterId: string
  photoIds: string[] // 묶음 안 순위순, 첫 번째가 대표 컷
  representativeId: string
}

export interface Recommendation {
  albumId: string
  draftIds: string[]
  clusters: Cluster[]
  missingClusterIds: string[] // 초안에 한 장도 없는 묶음
  ruleVersion: string
  readyAt: string
}

export interface CreateCuration {
  title: string
  albumId: string
  mode: Mode
  finalIds: string[]
  draftIds?: string[]
  readyAt?: string
  confirmedAt?: string
  satisfaction?: number
}

export interface Curation {
  id: number
  title: string
  mode: Mode
  finalIds: string[]
  photoNames: string[]
  draftIds: string[]
  ruleVersion: string | null
  loadedAt: string | null
  readyAt: string | null
  confirmedAt: string | null
  satisfaction: number | null
  createdAt: string
}
