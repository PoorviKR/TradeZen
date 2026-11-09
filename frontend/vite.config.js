import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'path';

// https://vitejs.dev/config/
export default defineConfig(({ mode }) => {
  // Load environment variables from the project root and current directory
  const env = {
    ...loadEnv(mode, path.resolve(__dirname, '..'), ''),
    ...loadEnv(mode, process.cwd(), ''),
    ...process.env,
  };

  const host = env.VITE_HOST || '0.0.0.0';
  const port = parseInt(env.VITE_PORT || '5173', 10);
  const backendProtocol = env.BACKEND_PROTOCOL || 'http';
  const backendHost = env.BACKEND_HOST || '127.0.0.1';
  const backendPort = env.BACKEND_PORT || env.PORT || '8000';
  const target = env.VITE_API_URL || `${backendProtocol}://${backendHost}:${backendPort}`;

  return {
    plugins: [react()],
    server: {
      // Listen on 0.0.0.0 to enable access from any device (phone, tablet) on the local Wi-Fi
      host: host,
      port: port,
      // Proxy API requests so frontends on other devices do not need hard-coded backend addresses
      proxy: {
        '/api': {
          target: target,
          changeOrigin: true,
          secure: false,
        },
      },
    },
    preview: {
      host: host,
      port: port,
    },
  };
});

