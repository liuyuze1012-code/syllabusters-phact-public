// Vite config. In dev, /api and /health are proxied to the local backend (uvicorn on :8000).
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: { proxy: { '/api': 'http://localhost:8000', '/health': 'http://localhost:8000' } },
});
