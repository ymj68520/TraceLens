import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';

// 构建时 caniuse-lite 数据会随时间变旧并打出 "browsers data is 11 months
// old" 提示。该提示只关乎数据新鲜度，不影响产物正确性；在此统一压制，
// 让 run.sh / Makefile 等所有构建入口都不再刷这条噪音。
// 需要真正更新数据时执行：npx update-browserslist-db@latest
process.env.BROWSERSLIST_IGNORE_OLD_DATA = '1';

export default defineConfig(({ mode }) => {
  const env = {
    ...loadEnv(mode, process.cwd(), ''),
    ...loadEnv(mode, '..', ''),
  };
  const cppTarget = env.VITE_CPP_PROXY_TARGET
    || env.CPP_BACKEND_URL
    || `http://${env.HTTP_SERVER_HOST || '127.0.0.1'}:${env.HTTP_SERVER_PORT || '8080'}`;
  const pythonTarget = env.VITE_PYTHON_PROXY_TARGET
    || env.PYTHON_SERVICE_URL
    || `http://${env.PYTHON_HTTP_HOST || '127.0.0.1'}:${env.PYTHON_HTTP_PORT || '8090'}`;
  const csTarget = env.VITE_CS_PROXY_TARGET
    || env.CS_SERVICE_URL
    || `http://${env.CS_HOST || env.HOST || '127.0.0.1'}:${env.CS_PORT || env.PORT || '8091'}`;

  // Vite's development proxy is another outbound client. An isolated test
  // must never inherit a root .env or silently proxy to old host services.
  if (env.TRACELENS_TEST_MODE === 'ISOLATED_TEST' && mode === 'development') {
    if (!process.env.TRACELENS_TEST_INSTANCE_ID || process.env.TRACELENS_TEST_INSTANCE_ID.length < 16) {
      throw new Error('isolated Vite proxy requires a synthetic instance identity');
    }
    for (const [name, target] of Object.entries({
      VITE_CPP_PROXY_TARGET: env.VITE_CPP_PROXY_TARGET,
      VITE_PYTHON_PROXY_TARGET: env.VITE_PYTHON_PROXY_TARGET,
      VITE_CS_PROXY_TARGET: env.VITE_CS_PROXY_TARGET,
    })) {
      if (!process.env[name] || process.env[name] !== target) {
        throw new Error(`${name} must be supplied by the isolated test launcher`);
      }
      let parsed;
      try { parsed = new URL(target); } catch { throw new Error(`${name} requires an explicit synthetic origin`); }
      if (parsed.protocol !== 'http:' || parsed.hostname !== '127.0.0.1' || !parsed.port ||
          ['8666', '8090', '8091'].includes(parsed.port) || parsed.username || parsed.password ||
          parsed.pathname !== '/' || parsed.search || parsed.hash) {
        throw new Error(`${name} must be a non-production numeric loopback origin`);
      }
    }
  }

  return {
    plugins: [react()],
    define: {
      'import.meta.env.VITE_FIELD_RELEASE_ID': JSON.stringify(env.VITE_FIELD_RELEASE_ID || 'UNFROZEN_WORKTREE'),
      // 证据判定新行内容 API 的本地令牌：同源演示部署没有注入
      // x-tracelens-field-token 的入口代理，由构建期把服务端 .env 的令牌
      // 带进 bundle 供 pythonApi 自动附加。现场（FIELD_AUTH）部署不受影响
      // ——那条路径走全局认证，不看这个头。
      'import.meta.env.VITE_FIELD_API_TOKEN': JSON.stringify(env.TRACELENS_FIELD_API_TOKEN || ''),
      // Make root .env service ports available to browser code without
      // exposing the complete server environment to the client bundle.
      'import.meta.env.VITE_CPP_PORT': JSON.stringify(env.VITE_CPP_PORT || env.HTTP_SERVER_PORT || ''),
      'import.meta.env.VITE_PYTHON_PORT': JSON.stringify(env.VITE_PYTHON_PORT || env.PYTHON_HTTP_PORT || '8090'),
      'import.meta.env.VITE_CS_PORT': JSON.stringify(env.VITE_CS_PORT || env.CS_PORT || env.PORT || '8091'),
      'import.meta.env.VITE_CPP_API_URL': JSON.stringify(env.VITE_CPP_API_URL || ''),
      'import.meta.env.VITE_PYTHON_API_URL': JSON.stringify(env.VITE_PYTHON_API_URL || ''),
      'import.meta.env.VITE_CS_API_URL': JSON.stringify(env.VITE_CS_API_URL || ''),
    },
    test: {
      environment: 'jsdom',
      globals: true,
      setupFiles: './src/test/setup.js',
      css: true,
    },
    server: {
      host: env.WEB_DEV_HOST || '127.0.0.1',
      port: Number(env.VITE_DEV_SERVER_PORT || env.WEB_DEV_PORT || 3000),
      proxy: {
        '/python': {
          target: pythonTarget,
          changeOrigin: true,
          rewrite: (path) => path.replace(/^\/python/, ''),
        },
        '/csapi': {
          target: csTarget,
          changeOrigin: true,
          rewrite: (path) => path.replace(/^\/csapi/, ''),
        },
        '/tasks': { target: cppTarget, changeOrigin: true },
        '/api/reports': { target: pythonTarget, changeOrigin: true },
        '/api/graphiti': { target: pythonTarget, changeOrigin: true },
        '/api/llm': { target: pythonTarget, changeOrigin: true },
        '/api/office': { target: pythonTarget, changeOrigin: true },
        '/api/db': { target: pythonTarget, changeOrigin: true },
        '/api/wechat': { target: pythonTarget, changeOrigin: true },
        '/api/investigation': { target: pythonTarget, changeOrigin: true },
        '/api': { target: cppTarget, changeOrigin: true },
      },
    },
    build: {
      outDir: 'dist',
      assetsDir: 'assets',
      sourcemap: env.VITE_FIELD_RELEASE_BUILD === '1' ? false : true,
      // 按库拆包后主包约 710 KB，仍高于 Vite 默认的 500 KB 阈值。该阈值是
      // 提醒而非硬限制：此处留出余量设 750，只在主包再次明显膨胀时才报警。
      chunkSizeWarningLimit: 750,
      rollupOptions: {
        output: {
          // 按库拆包：主包从 1527 KB 降到 ~710 KB。项目代码 25 个页面都是
          // routes.jsx 静态导入，只靠 manualChunks 无法再往下压；要到 500 KB
          // 以下得把路由全量改成 React.lazy（会引入首屏加载态，属行为变更）。
          manualChunks: {
            'react-vendor': ['react', 'react-dom', 'react-router-dom'],
            'd3-vendor': ['d3'],
            'redux-vendor': ['@reduxjs/toolkit', 'react-redux'],
            'charts-vendor': ['recharts'],
            'motion-vendor': ['framer-motion'],
            'graph-vendor': ['react-force-graph-2d'],
            'doc-vendor': ['docx-preview', 'jszip'],
            'virtual-vendor': ['react-virtuoso'],
            'http-vendor': ['axios'],
            'icons-vendor': ['lucide-react'],
          },
        },
      },
    },
  };
});
