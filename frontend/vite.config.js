import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Where the FastAPI backend lives, as seen FROM the frontend container.
// In docker-compose, services reach each other by service name (http://backend:8000).
// Override with BACKEND_ORIGIN when running `vite` directly on a laptop (e.g. http://localhost:8000).
const BACKEND_ORIGIN = process.env.BACKEND_ORIGIN || 'http://backend:8000'

// One proxy rule per backend path-prefix the browser is allowed to call.
// The browser always talks same-origin (the Vite dev server), so the cookie
// session stays same-origin and no backend URL/secret ever ships to the client.
// `/media` is the M20 business-page gallery. In production Caddy serves those
// files straight off the business_images volume and never reaches Python; in dev
// there is no reverse proxy, so the backend mounts the same path via StaticFiles
// and we forward it here. Without this rule the dev server answers /media/* with
// the SPA fallback (index.html) and every gallery image renders broken.
const proxy = Object.fromEntries(
  ['/healthz', '/api', '/auth', '/webhook', '/media'].map((path) => [
    path,
    { target: BACKEND_ORIGIN, changeOrigin: true },
  ]),
)

export default defineConfig({
  plugins: [react()],
  server: {
    // 0.0.0.0 so the port is reachable from outside the container.
    host: '0.0.0.0',
    port: 5173,
    strictPort: true,
    proxy,
    // A Windows host → Linux container bind mount does NOT deliver inotify file
    // events, so Vite's HMR never notices host edits (the page serves stale code
    // until the container restarts). Poll the filesystem instead so saved changes
    // hot-reload reliably. Slightly more CPU; perfectly fine for local dev.
    watch: { usePolling: true, interval: 300 },
  },
})
