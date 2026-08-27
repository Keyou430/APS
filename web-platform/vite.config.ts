import { defineConfig } from 'vite';

export default defineConfig({
  server: {
    host: '0.0.0.0',
    proxy: {
      '/api': {
        target: process.env.VITE_DEV_API_PROXY_TARGET || 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
    watch: {
      // Exclude backend directory 鈥?APScheduler writes to SQLite WAL every 2s,
      // which would otherwise trigger spurious HMR full-page reloads.
      ignored: ['**/../backend/**', '**/*.db', '**/*.db-*'],
    },
  },
});
