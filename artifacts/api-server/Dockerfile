# ============================================================================
# ADM-API — Production Dockerfile
# ============================================================================
#
# Multi-stage build:
#   Stage 1 (builder) — install Python dependencies into a virtualenv.
#   Stage 2 (runtime) — copy virtualenv + source; run as non-root.
#
# Build:
#   docker build -t adm-api:latest .
#
# Run (single container):
#   docker run -p 8080:8080 \
#     -e ADM_ADMIN_KEY=your_secret_admin_key \
#     -v $(pwd)/data:/app/data \
#     adm-api:latest
#
# ============================================================================

# ── Stage 1: dependency builder ───────────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /build

# Install build tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy and install dependencies into isolated venv
COPY requirements.txt .
RUN python -m venv /opt/venv && \
    /opt/venv/bin/pip install --upgrade pip --quiet && \
    /opt/venv/bin/pip install -r requirements.txt --quiet

# ── Stage 2: minimal runtime ──────────────────────────────────────────────────
FROM python:3.11-slim AS runtime

# Security: run as non-root
RUN addgroup --system adm && adduser --system --ingroup adm adm

WORKDIR /app

# Copy virtualenv from builder
COPY --from=builder /opt/venv /opt/venv

# Copy application source
COPY adm_api/        ./adm_api/
COPY gunicorn.conf.py .

# Persistent data directory (mount a volume here in production)
RUN mkdir -p /app/data && chown -R adm:adm /app

USER adm

# Activate virtualenv for all subsequent RUN/CMD
ENV PATH="/opt/venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# BASE_PATH must match the proxy route; defaults to /api
ENV BASE_PATH=/api

# Workers: 4 for production (matches gunicorn.conf.py default)
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/api/healthz')" || exit 1

CMD ["gunicorn", "adm_api.main:app", "--config", "gunicorn.conf.py"]
