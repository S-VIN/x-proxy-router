/// <reference types="vitest/config" />
import { svelte } from '@sveltejs/vite-plugin-svelte';
import { defineConfig } from 'vite';

// The Python server listens here and serves the built client itself (server/main.py).
const SERVER = 'http://127.0.0.1:20800';

export default defineConfig({
  plugins: [svelte()],
  server: {
    // The dev page talks to the real server through the same origin, like the built one.
    proxy: { '/ws': { target: SERVER, ws: true } },
  },
  build: { target: 'es2022' },
  test: { include: ['src/**/*.test.ts'] },
});
