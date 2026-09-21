import path from 'node:path'
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { loadEnv } from 'vite'
import { defineConfig } from 'vitest/config'

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  // Ports 8000/8001 on this dev machine belong to another project; this simulator's backend
  // listens on 8100 by default (see .env.example, docs/hld/00-decisions.md D1).
  const apiProxyTarget = env.VITE_API_PROXY_TARGET || 'http://127.0.0.1:8100'

  return {
    plugins: [react(), tailwindcss()],
    resolve: {
      alias: {
        '@': path.resolve(import.meta.dirname, './src'),
      },
    },
    server: {
      proxy: {
        '/api': {
          target: apiProxyTarget,
          changeOrigin: true,
          // Also upgrades the realtime channel at /api/v1/ws/sessions/{id} (HLD §40.1).
          ws: true,
        },
      },
    },
    test: {
      environment: 'jsdom',
      setupFiles: ['./src/test/setup.ts'],
    },
  }
})
