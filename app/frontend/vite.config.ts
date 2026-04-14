import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

// В dev axios ходит на window.location.origin (5173). Без прокси API не доходит до FastAPI (8000).
// Переопределение: VITE_DEV_PROXY_TARGET=http://127.0.0.1:8000 в .env
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const backend = env.VITE_DEV_PROXY_TARGET || 'http://127.0.0.1:8000'

  return {
    plugins: [react()],
    server: {
      host: '0.0.0.0',
      port: 5173,
      strictPort: false,
      proxy: {
        '/auth': { target: backend, changeOrigin: true },
        '/rooms': { target: backend, changeOrigin: true },
        '/messages': { target: backend, changeOrigin: true },
        '/friends': { target: backend, changeOrigin: true },
        '/ws': { target: backend, ws: true },
      },
    },
  }
})
