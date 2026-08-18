import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    // Backend calls are namespaced under /api by src/api/client.ts so that no
    // API route can shadow an SPA route (/forum, /history and /analyze used to
    // be both). The backend itself is unprefixed, so strip /api on the way out;
    // frontend/nginx.conf does the same in docker. Everything else falls
    // through to index.html, which is what makes refresh and deep links work.
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
})
