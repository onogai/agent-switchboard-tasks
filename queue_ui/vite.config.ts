import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  base: '/queue/',
  plugins: [react()],
  server: {
    proxy: { '/queue/api': 'http://127.0.0.1:8767' },
  },
})
