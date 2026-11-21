import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  // strictPort: the backend's default CORS allow-list names port 5173; silently moving to
  // another port would make every API call fail with a confusing CORS error.
  // Dev server binds to localhost only. To test from a phone: `npm run dev -- --host`.
  server: { port: 5173, strictPort: true },
  // Same reasoning for `npm run preview` (the production build), so it can be exercised against the real API.
  preview: { port: 5173, strictPort: true },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.js'],
    include: ['src/**/*.test.{js,jsx}'],
  },
});
