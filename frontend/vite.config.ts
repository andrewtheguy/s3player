import path from 'node:path'
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  build: {
    // Cargo's build.rs points this at its OUT_DIR for release builds; a
    // standalone `bun run build` writes frontend/dist.
    outDir: process.env.S3PLAYER_FRONTEND_OUT_DIR ?? 'dist',
    // Vite won't empty an outDir outside the project root by default; stale
    // content-hashed assets must not linger in Cargo's directory.
    emptyOutDir: true,
  },
  server: {
    proxy: {
      '/api': 'http://127.0.0.1:8000',
      '/login': 'http://127.0.0.1:8000',
    },
  },
})
