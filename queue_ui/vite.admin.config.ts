import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  base: '/admin/',
  plugins: [react()],
  build: { outDir: 'admin-dist' },
  server: {
    proxy: { '/admin/api': 'http://127.0.0.1:8768' },
  },
})
