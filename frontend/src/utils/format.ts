/** 촬영 시각(ISO 8601)을 '10/1 09:10' 형식으로. 없으면 안내 문구. */
export function formatTime(iso: string | null): string {
  if (!iso) return '촬영 시각 없음'
  const d = new Date(iso)
  return `${d.getMonth() + 1}/${d.getDate()} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}
