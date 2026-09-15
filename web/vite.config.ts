import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'node:path';

export default defineConfig(({ mode }) => {
  const env = {
    ...loadEnv(mode, process.cwd(), ''),
    ...loadEnv(mode, '..', ''),
  };
  const cppTarget =
    env.VITE_CPP_PROXY_TARGET ||
    `http://localhost:${env.HTTP_SERVER_PORT || '8080'}`;

  return {
    plugins: [react()],
    resolve: {
      alias: { '@': path.resolve(__dirname, 'src') },
    },
    test: {
      environment: 'jsdom',
      globals: true,
      setupFiles: './src/test/setup.ts',
      css: true,
    },
    server: {
      port: 3000,
      watch: {
        // C++ build artifact trees (tests/, libs/, CMakeFiles, object files)
        // hold tens of thousands of files that exhaust the inotify watch
        // limit and crash the dev server.
        ignored: [
          '**/tests/**',
          '**/libs/**',
          '**/dist/**',
          '**/build/**',
          '**/CMakeFiles/**',
          '**/*.{o,a,so}',
        ],
      },
      proxy: {
        '/csapi': {
          target: 'http://localhost:8091',
          changeOrigin: true,
          rewrite: (p) => p.replace(/^\/csapi/, ''),
        },
        // NOTE: no '/tasks' proxy entry — it would shadow the SPA route of the
        // same name in dev. All frontend API calls go through '/api/tasks'.
        '/api/reports': { target: 'http://localhost:8090', changeOrigin: true },
        '/api/graphiti': { target: 'http://localhost:8090', changeOrigin: true },
        '/api/llm': { target: 'http://localhost:8090', changeOrigin: true },
        '/api/office': { target: 'http://localhost:8090', changeOrigin: true },
        '/api/db': { target: 'http://localhost:8090', changeOrigin: true },
        '/api/wechat': { target: 'http://localhost:8090', changeOrigin: true },
        '/api/investigation': { target: 'http://localhost:8090', changeOrigin: true },
        '/api': { target: cppTarget, changeOrigin: true },
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
  };
});
