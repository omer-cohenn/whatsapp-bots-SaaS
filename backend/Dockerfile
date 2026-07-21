# Bizz_up backend — production image (M0+M1 minimal).
# python:3.12-slim · non-root · gunicorn+uvicorn workers · NO --reload.
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Install pinned deps from the lockfile first (better layer caching).
# --no-deps: the lockfile already contains the full transitive closure.
COPY requirements.lock ./
RUN pip install --no-deps -r requirements.lock

# App code.
COPY app ./app
COPY pyproject.toml ./

# Run as a non-root user.
RUN useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app

# M20 — the mount point for the business_images named volume. It MUST exist in
# the image and be owned by appuser BEFORE the volume is attached: when Docker
# first creates an empty named volume it copies the image directory's contents
# AND its ownership. Without this the volume is created root-owned, and the
# non-root process cannot write a single gallery photo (PermissionError → 500).
RUN mkdir -p /data/business-images \
    && chown -R appuser:appuser /data
USER appuser

EXPOSE 8000

# Gunicorn with uvicorn workers, bound to :8000. No --reload (prod).
# Worker count is overridable via $WEB_CONCURRENCY (default 2).
CMD ["sh", "-c", "gunicorn app.main:app \
    --worker-class uvicorn.workers.UvicornWorker \
    --workers ${WEB_CONCURRENCY:-2} \
    --bind 0.0.0.0:8000 \
    --timeout 30 \
    --graceful-timeout 30 \
    --access-logfile - \
    --error-logfile -"]
