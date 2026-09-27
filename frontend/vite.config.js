import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import path from 'path'

// https://vite.dev/config/
export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, 'src'),
      '@locales': path.resolve(__dirname, '../locales')
    }
  },
  server: {
    port: 3000,
    open: true,
    proxy: {
      '/studio-api': {
        target: 'http://127.0.0.1:3888',
        changeOrigin: true
      },
      '/api': {
        target: 'http://127.0.0.1:3888',
        changeOrigin: true,
        secure: false
      }
    }
  }
})
