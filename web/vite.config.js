import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// Draft frontend — see ../SPEC.md (§13.E: dev proxy /ws (ws:true), /tts, /replay -> :8000)
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      '/ws': {
        target: 'ws://localhost:8000',
        ws: true,
      },
      '/tts': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      '/replay': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
})
