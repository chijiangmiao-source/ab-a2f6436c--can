import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// During local development both the UI and /api are served from Vite;
// production builds are served by nginx which proxies the same paths.
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
})
