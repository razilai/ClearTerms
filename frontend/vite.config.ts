import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Backend API prefixes share paths with SPA routes (/forum/new, /history,
// /analyze). Only proxy programmatic requests; browser navigations
// (Accept: text/html) fall through to index.html so refresh/deep links work.
const backendPrefixes = [
  '/auth',
  '/forum',
  '/analyze',
  '/analyses',
  '/history',
  '/preferences',
  '/messages',
]

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: Object.fromEntries(
      backendPrefixes.map((prefix) => [
        prefix,
        {
          target: 'http://localhost:8000',
          bypass: (req: { headers: { accept?: string } }) =>
            req.headers.accept?.includes('text/html') ? '/index.html' : undefined,
        },
      ]),
    ),
  },
})
