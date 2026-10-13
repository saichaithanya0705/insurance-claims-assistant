import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The production build is emitted into the Python package so a single
// `uv run uvicorn claims.api.main:app` serves both the API and this UI.
export default defineConfig({
  plugins: [react()],
  build: {
    outDir: '../src/claims/static/app',
    emptyOutDir: true,
  },
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://127.0.0.1:8000',
    },
  },
})
