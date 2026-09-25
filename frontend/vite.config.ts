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
  // I4 E27 (docs/hld/71-i4-wave4.md §71.4): behind the TLS edge (infra/edge/Caddyfile) the browser's
  // own Host header reaches this server. Vite accepts localhost and any IP address by default;
  // a hostname (the classroom server's name) must be listed — comma-separated, `.example.lan`
  // allows every subdomain. Empty keeps Vite's default. HMR needs nothing extra: the client
  // dials wss://<the page's host:port>/, which the edge forwards here.
  const allowedHosts = (env.VITE_ALLOWED_HOSTS ?? '')
    .split(',')
    .map((host) => host.trim())
    .filter((host) => host.length > 0)

  return {
    plugins: [react(), tailwindcss()],
    resolve: {
      alias: {
        '@': path.resolve(import.meta.dirname, './src'),
      },
    },
    server: {
      ...(allowedHosts.length > 0 ? { allowedHosts } : {}),
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
