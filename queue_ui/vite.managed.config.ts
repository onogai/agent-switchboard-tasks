import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { localePlugin } from './localePlugin'

export default defineConfig({
  base: '/admin/addon-ui/tasks/',
  plugins: [localePlugin(), react()],
  build: { outDir: 'managed-dist' },
})
