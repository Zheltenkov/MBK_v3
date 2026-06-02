import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// В dev режиме фронт ходит на http://localhost:5173, а /api/ проксируется на бэк.
// В prod nginx внутри контейнера serves SPA и проксирует /api/ → backend сервис.
export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        // Важно для SSE: не буферим.
        configure: (proxy) => {
          proxy.on('proxyRes', (proxyRes) => {
            proxyRes.headers['cache-control'] = 'no-cache';
          });
        },
      },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
  },
});
