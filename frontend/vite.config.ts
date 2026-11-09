import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig(({ mode }) => ({
  plugins: [react()],
  server: {
    // '/api/' (with the slash) so /api-config.js is served from public/ instead of the backend.
    // Demo mode answers /api/ in the browser, so it needs no backend proxy.
    proxy: mode === 'demo' ? undefined : {
      '/api/': 'http://localhost:8000',
    },
  },
}))
