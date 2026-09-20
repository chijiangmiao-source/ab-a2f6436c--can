import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// In development the Vite dev server proxies API calls to FastAPI;
// in production nginx does the same proxying, so the app always uses
// same-origin relative URLs.
export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    port: 5173,
    proxy: {
      '/api': 'http://localhost:8000',
      '/health': 'http://localhost:8000',
    },
  },
  build: {
    outDir: 'dist',
  },
})
