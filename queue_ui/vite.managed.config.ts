import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  base: '/admin/queue/',
  plugins: [react()],
  build: { outDir: 'managed-dist' },
})
