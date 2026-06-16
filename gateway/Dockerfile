# Bizz_up WhatsApp gateway — M0+M1 minimal image.
# Pinned base; deps installed from the lockfile for reproducible builds.
FROM node:20-slim

# Tini for clean signal handling (Baileys keeps sockets open).
ENV NODE_ENV=production
WORKDIR /app

# Install deps first for layer caching. Use the lockfile (npm ci) so the build
# is reproducible and pinned. --omit=dev: no devDependencies in the image.
COPY package.json package-lock.json ./
RUN npm ci --omit=dev

# App source.
COPY src ./src

# The spike persists Baileys creds here (gitignored on the host; a writable
# dir in the container). Real design encrypts these in the DB (M6).
RUN mkdir -p /app/auth
ENV GATEWAY_AUTH_DIR=/app/auth

EXPOSE 3000

# Healthcheck hits /healthz (no QR / no secret). Compose also gates on this.
HEALTHCHECK --interval=10s --timeout=3s --start-period=15s --retries=5 \
  CMD node -e "fetch('http://localhost:3000/healthz').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"

CMD ["node", "src/index.js"]
