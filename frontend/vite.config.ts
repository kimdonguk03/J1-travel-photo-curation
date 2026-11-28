import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

// /api 요청은 백엔드(Spring, :8080)로 넘깁니다. CORS 설정 없이 같은 주소처럼 씁니다.
const proxy = { '/api': 'http://localhost:8080' }

export default defineConfig(({ mode }) => {
  // localhost가 아닌 주소로 미리보기(npm run preview)에 들어오려면, 그 호스트를
  // frontend/.env.local의 PREVIEW_ALLOWED_HOSTS에 쉼표로 적습니다 (.env.local은 저장소에 올리지 않음).
  const env = loadEnv(mode, '.', '')
  const allowedHosts = (env.PREVIEW_ALLOWED_HOSTS ?? '')
    .split(',')
    .map((h) => h.trim())
    .filter(Boolean)

  return {
    plugins: [react()],
    server: { port: 5173, proxy },
    preview: { port: 4173, proxy, allowedHosts },
  }
})
