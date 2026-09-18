import path from 'node:path'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import projectsApi from './plugins/projects-api.ts'

// https://vite.dev/config/
// Dedicated port 5199 (strict): Vite's default 5173 collides with a separate
// tool the user runs there, and an auto-incremented port breaks the cold
// 2-command launch + browser-QA assumptions. strictPort fails loudly instead
// of silently drifting to 5200. Keep this in sync with package.json + README.
export default defineConfig({
  plugins: [react(), tailwindcss(), projectsApi()],
  server: {
    port: 5199,
    strictPort: true,
  },
  preview: {
    port: 5199,
    strictPort: true,
  },
  resolve: {
    alias: {
      '@': path.resolve(import.meta.dirname, './src'),
    },
  },
})
