import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// /api 요청은 백엔드(Spring, :8080)로 넘깁니다. CORS 설정 없이 같은 주소처럼 씁니다.
const proxy = { '/api': 'http://localhost:8080' }

export default defineConfig({
  plugins: [react()],
  // 개발: npm run dev (http://localhost:5173)
  server: { port: 5173, proxy },
  // 공개 시연: npm run build 후 npm run preview (http://localhost:4173)를 터널로 공개합니다.
  // allowedHosts에 터널 주소를 허용합니다 (Cloudflare quick tunnel, ngrok).
  preview: {
    port: 4173,
    proxy,
    allowedHosts: ['.trycloudflare.com', '.ngrok-free.app'],
  },
})
