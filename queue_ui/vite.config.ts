import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { localePlugin } from './localePlugin'

export default defineConfig({
  base: '/queue/',
  plugins: [localePlugin(), react()],
  server: {
    proxy: { '/queue/api': 'http://127.0.0.1:8767' },
  },
})
