import { fileURLToPath } from 'node:url'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// Draft frontend — see ../SPEC.md (§13.E: dev proxy /ws (ws:true), /tts, /replay -> :8000)
// §14.B: second entry (watch.html -> AudienceView, the Convex-backed
// audience page) + `base: './'` so the built assets resolve relatively —
// required for GitHub Pages, which serves the site from a subpath rather
// than the domain root.
export default defineConfig({
  base: './',
  plugins: [react(), tailwindcss()],
  build: {
    rollupOptions: {
      input: {
        main: fileURLToPath(new URL('./index.html', import.meta.url)),
        watch: fileURLToPath(new URL('./watch.html', import.meta.url)),
      },
    },
  },
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
      '/drafts': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
})
