import { defineConfig } from 'vite';

export default defineConfig({
  server: {
    allowedHosts: ["https://iridaceous-wilburn-denticulately.ngrok-free.dev"],
    port: 5173,
    proxy: {
      '/ws': {
        target: 'ws://localhost:8000',
        ws: true,
      },
      '/api': {
        target: 'http://localhost:8000',
      },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: true,
  },
});
