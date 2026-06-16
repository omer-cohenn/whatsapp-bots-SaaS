# frontend/ — React + Tailwind 🎨

**Owner agent:** Frontend · **Built in:** M0+M1 (scaffold) → M3–M7 (features). See [`../docs/spec/mvp-checklist.md`](../docs/spec/mvp-checklist.md).

The owner app (dashboard, AI bot builder, try-me, QR onboarding), the public pages (booking later,
Terms/Privacy), and (later) the back-office admin UI. **Accessible (WCAG / נגישות) and RTL Hebrew from
day one.**

## Status: M0+M1 minimal scaffold ✅
A bootable Vite + React 18 + Tailwind app — **RTL Hebrew** (`dir="rtl"`, `lang="he"`, Heebo font) — showing:
- a placeholder hero (**"Bizz_up — בקרוב 🚀"**),
- a **"בריאות המערכת" (Stack health)** panel that calls the backend `GET /healthz` *through the Vite dev
  proxy* and shows ✅/❌/⚪ for backend + its Postgres/Redis checks.

No features yet (no auth/bot/leads) — just the bootable, accessible, RTL-correct shell.

## How Omer opens it
- **Via the stack (normal):** from the repo root run the compose stack, then open **http://localhost:5173**.
  The dev server runs inside the `frontend` container on `0.0.0.0:5173` and proxies `/healthz` to
  `http://backend:8000` (the compose service name).
- **Standalone (this folder, no Docker):**
  ```bash
  npm install            # already pinned via package-lock.json
  npm run dev            # http://localhost:5173
  ```
  To point the health proxy at a backend running on your laptop instead of the compose name:
  ```bash
  BACKEND_ORIGIN=http://localhost:8000 npm run dev
  ```

**What he should see:** the RTL Hebrew hero, and the Stack-health card. If the backend is up, the three
rows (שרת / Postgres / Redis) turn **✅ תקין**; if it's down, **❌ תקלה** with a plain-language hint.

## Current layout
```
frontend/
├── index.html              # RTL Hebrew shell (dir=rtl, lang=he, Heebo via Google Fonts)
├── src/
│   ├── main.jsx            # React 18 entry
│   ├── App.jsx             # app shell: skip-link, header, hero, <StackHealth/>, footer
│   ├── index.css           # Tailwind + a11y base (focus rings, reduced-motion, skip-link)
│   ├── components/
│   │   └── StackHealth.jsx # the "בריאות המערכת" panel (aria-live, refresh)
│   └── lib/
│       └── health.js       # fetch /healthz (via proxy), tolerant of response shape
├── vite.config.js          # dev proxy /healthz,/api,/auth,/webhook → BACKEND_ORIGIN (default http://backend:8000)
├── tailwind.config.js      # Heebo default font + consolidated brand/WhatsApp-green theme
├── postcss.config.js
├── package.json            # pinned deps (React 18.3, Vite 5.4, Tailwind 3.4)
├── package-lock.json       # lockfile (reproducible installs)
├── Dockerfile              # node:20-slim, runs `vite --host 0.0.0.0 --port 5173`
├── .dockerignore
└── .env.example            # BACKEND_ORIGIN (optional proxy override) — NO secrets in the browser
```

> Rules baked in: **no secrets in the browser** (it talks only to the backend, same-origin via the
> proxy — it never sees the gateway token or WhatsApp creds); RTL + a11y from the first commit (not
> retrofitted); pinned deps. Future feature work honors the API contract in
> [`../docs/system-map/frontend-map.md`](../docs/system-map/frontend-map.md) (with the B8/B9 fixes).
