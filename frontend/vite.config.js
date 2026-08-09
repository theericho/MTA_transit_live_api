import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// In production the built files are copied into the API image and served by
// FastAPI itself, so the browser always talks to one origin and no CORS setup
// is needed. `npm run dev` reproduces that by proxying the API routes to the
// locally running backend.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/v1': 'http://localhost:8000',
      '/health': 'http://localhost:8000',
    },
  },
})
