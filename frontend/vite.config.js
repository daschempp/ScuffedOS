import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Scuffed OS frontend. In dev, /api is proxied to the FastAPI backend on :8000
// so the app can call same-origin endpoints (no CORS dance during development).
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
  // Vitest (frontend unit/component tests). jsdom + Testing Library; the setup
  // file registers jest-dom matchers and auto-cleans the DOM between tests.
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: './src/test/setup.js',
    css: false,
    include: ['src/**/*.test.{js,jsx}'],
  },
})
