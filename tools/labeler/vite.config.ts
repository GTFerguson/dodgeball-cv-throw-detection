import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import { labelApi, DATA_DIR } from './server/api'

export default defineConfig({
  plugins: [react(), labelApi()],
  publicDir: DATA_DIR,
  build: { copyPublicDir: false },
  server: { port: 5173, fs: { allow: ['..'] } },
  test: { include: ['src/**/*.test.ts'], environment: 'node' },
})
