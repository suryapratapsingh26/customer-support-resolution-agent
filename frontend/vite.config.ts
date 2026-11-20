import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

const backend = process.env.BFF_TARGET || 'http://127.0.0.1:8000'

export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy: { '/api/bff': { target: backend, changeOrigin: true } } },
  test: { environment: 'jsdom', setupFiles: './src/test/setup.ts' },
})
