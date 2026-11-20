import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { localePlugin } from './localePlugin'

export default defineConfig({
  base: '/admin/queue/',
  plugins: [localePlugin(), react()],
  build: { outDir: 'managed-dist' },
})
