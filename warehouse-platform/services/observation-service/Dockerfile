# ─────────────────────────────────────────────────────────────────────────────
# Observation Service — Multi-stage Dockerfile
# Python 3.12-slim with OpenCV support
# ─────────────────────────────────────────────────────────────────────────────

# ── Stage 1: Build dependencies ───────────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /build

# System deps needed to compile some Python packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

RUN pip install --upgrade pip \
    && pip install --no-cache-dir --prefix=/install -r requirements.txt

# ── Stage 2: Runtime image ────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

LABEL maintainer="warehouse-platform" \
      service="observation-service" \
      version="1.0.0"

# Install runtime system libraries needed by OpenCV & asyncpg
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender1 \
    libgomp1 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create a non-root user
RUN groupadd -r appuser && useradd -r -g appuser -s /sbin/nologin appuser

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy application source
COPY app/ app/

# Ownership
RUN chown -R appuser:appuser /app

USER appuser

# Healthcheck via the /health endpoint
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:${PORT:-8003}/health || exit 1

EXPOSE ${PORT:-8003}

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8003} --workers 1 --loop uvloop --http httptools --no-access-log"]
