# Bizz_up frontend — M0+M1 minimal DEV image.
# Runs the Vite dev server inside compose (port 5173, host 0.0.0.0).
# Production build → static dist/ comes later (M8); this image is for local dev.
# Pinned base; deps installed from the lockfile for reproducible builds.
FROM node:20-slim

WORKDIR /app

# Install deps first for layer caching. Use `npm install` (not `npm ci`) so the
# correct LINUX platform optional deps — e.g. the @rollup/rollup-linux-x64-gnu
# native binary — are resolved for this image, avoiding the known npm
# optional-deps bug when the lockfile was generated on another OS (Windows).
COPY package.json package-lock.json ./
RUN npm install --no-audit --no-fund

# App source + configs.
COPY index.html ./
COPY vite.config.js postcss.config.js tailwind.config.js ./
COPY src ./src

EXPOSE 5173

# Healthcheck hits the Vite dev server root (no backend dependency, no secret).
# Compose can also gate on this so the stack waits until the UI is serving.
HEALTHCHECK --interval=10s --timeout=3s --start-period=20s --retries=5 \
  CMD node -e "fetch('http://localhost:5173/').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"

# host 0.0.0.0 so the port is reachable from the host machine.
CMD ["npx", "vite", "--host", "0.0.0.0", "--port", "5173"]
