import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// The frontend talks to the FastAPI backend at a same-origin `/api` path and lets Vite
// proxy it in development. That keeps the browser free of any absolute backend URL, so
// there is nothing to configure per machine and no place a key could be embedded — the
// only secret in this system lives in the backend's .env and never crosses the wire.
//
// NETSAGE_API_TARGET exists so the acceptance test can run its own backend on a spare port
// without disturbing a development server already on 8000. It is a dev-server address and
// nothing else; it is read at config time, never bundled, and never reaches the browser.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: process.env.NETSAGE_API_TARGET || 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
})
