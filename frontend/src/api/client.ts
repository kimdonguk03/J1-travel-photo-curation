// 백엔드 호출. 화면 코드는 fetch를 직접 쓰지 않고 이 함수들만 씁니다.
import type { Album, CreateCuration, Curation, Recommendation } from './types'

// 같은 주소에서 내보내면 비워 둡니다. 다른 주소의 백엔드를 쓰려면 .env에 VITE_API_BASE=https://... 를 둡니다.
const BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? ''
const USER_KEY = 'j1.userId'

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers)
  const user = getUserId()
  if (user) headers.set('X-J1-User', user)
  if (init.body && typeof init.body === 'string') headers.set('Content-Type', 'application/json')
  let res: Response
  try {
    res = await fetch(BASE + path, { ...init, headers })
  } catch {
    throw new ApiError(0, '서버에 연결할 수 없습니다. 백엔드가 실행 중인지 확인하세요.')
  }
  if (!res.ok) throw new ApiError(res.status, await errorMessage(res))
  if (res.status === 204) return undefined as T
  return (await res.json()) as T
}

async function errorMessage(res: Response): Promise<string> {
  try {
    const body = await res.json()
    if (body && typeof body.detail === 'string') return body.detail
  } catch {
    /* 본문이 JSON이 아님 */
  }
  return `요청이 실패했습니다 (${res.status}).`
}

// ---------------------------------------------------------------- 사용자

export function getUserId(): string | null {
  try {
    return localStorage.getItem(USER_KEY)
  } catch {
    return null
  }
}

/** 게스트 ID가 없으면 발급받아 저장합니다. */
export async function ensureGuest(): Promise<string> {
  const existing = getUserId()
  if (existing) return existing
  const { userId } = await request<{ userId: string }>('/api/auth/guest', { method: 'POST' })
  try {
    localStorage.setItem(USER_KEY, userId)
  } catch {
    /* 저장할 수 없으면 이번 방문에서만 씀 */
  }
  return userId
}

// ---------------------------------------------------------------- 앨범

/** 사진 업로드. onProgress(0~1)로 진행률을 알려 줍니다. 원본 그대로 올려야 촬영 시각이 남습니다. */
export function uploadAlbum(files: File[], consent: boolean, onProgress?: (ratio: number) => void): Promise<Album> {
  return new Promise((resolve, reject) => {
    const form = new FormData()
    files.forEach((f) => form.append('files', f, f.name))
    const xhr = new XMLHttpRequest()
    xhr.open('POST', `${BASE}/api/albums/upload?consent=${consent}`)
    const user = getUserId()
    if (user) xhr.setRequestHeader('X-J1-User', user)
    xhr.upload.onprogress = (e) => e.lengthComputable && onProgress?.(e.loaded / e.total)
    xhr.onload = () => {
      let body: unknown = null
      try {
        body = JSON.parse(xhr.responseText)
      } catch {
        /* 본문 없음 */
      }
      if (xhr.status >= 200 && xhr.status < 300) resolve(body as Album)
      else {
        const detail = (body as { detail?: string } | null)?.detail
        reject(new ApiError(xhr.status, detail ?? `업로드가 실패했습니다 (${xhr.status}).`))
      }
    }
    xhr.onerror = () => reject(new ApiError(0, '업로드 중 연결이 끊겼습니다.'))
    xhr.send(form)
  })
}

/** 추천 초안. 300장 기준 처음에는 30초~2분이 걸립니다. */
export function recommend(albumId: string, k?: number): Promise<Recommendation> {
  return request(`/api/albums/${albumId}/recommend`, { method: 'POST', body: JSON.stringify(k ? { k } : {}) })
}

/** img src로 바로 쓰는 썸네일 주소. size: 목록 512, 큰 미리보기 1600. */
export function thumbUrl(albumId: string, photoId: string, size: 512 | 1600 = 512): string {
  return `${BASE}/api/albums/${albumId}/photos/${photoId}/thumb?size=${size}`
}

/** 고른 원본 zip 내려받기 주소 (a href로 씀). */
export function downloadUrl(albumId: string, photoIds: string[]): string {
  return `${BASE}/api/albums/${albumId}/download?photoIds=${photoIds.join(',')}`
}

/** 앨범 닫기. 업로드한 사진이 서버에서 지워집니다. */
export function closeAlbum(albumId: string): Promise<void> {
  return request(`/api/albums/${albumId}`, { method: 'DELETE' })
}

// ---------------------------------------------------------------- 큐레이션

export function createCuration(body: CreateCuration): Promise<Curation> {
  return request('/api/curations', { method: 'POST', body: JSON.stringify(body) })
}

export function listCurations(): Promise<Curation[]> {
  return request('/api/curations')
}

export function getCuration(id: number): Promise<Curation> {
  return request(`/api/curations/${id}`)
}
