import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: './src/test/setup.js',
    css: true,
  },
  server: {
    port: 3000,
    proxy: {
      '/csapi': {
        target: 'http://localhost:8091',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/csapi/, ''),
      },
      '/tasks': {
        target: 'http://localhost:8666',
        changeOrigin: true,
      },
      '/api/reports': {
        target: 'http://localhost:8090',
        changeOrigin: true,
      },
      '/api': {
        target: 'http://localhost:8666',
        changeOrigin: true,
      },
      '/api/graphiti': {
        target: 'http://localhost:8090',
        changeOrigin: true,
      },
      '/api/llm': {
        target: 'http://localhost:8090',
        changeOrigin: true,
      },
      '/api/office': {
        target: 'http://localhost:8090',
        changeOrigin: true,
      },
      '/api/db': {
        target: 'http://localhost:8090',
        changeOrigin: true,
      },
      '/api/wechat': {
        target: 'http://localhost:8090',
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    assetsDir: 'assets',
    sourcemap: true,
    rollupOptions: {
      output: {
        manualChunks: {
          'react-vendor': ['react', 'react-dom', 'react-router-dom'],
          'd3-vendor': ['d3'],
          'redux-vendor': ['@reduxjs/toolkit', 'react-redux'],
        },
      },
    },
  },
});
