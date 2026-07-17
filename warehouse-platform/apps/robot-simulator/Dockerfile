# ============================================================
#  Robot Fleet Simulator — Multi-stage Dockerfile
#  Python 3.12 slim
# ============================================================

# ── Stage 1: Build / dependency resolution ──────────────────
FROM python:3.12-slim AS builder

# Install build essentials needed for native extensions
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        gcc \
        libffi-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

# Copy dependency manifest first to leverage Docker layer caching
COPY requirements.txt .

# Install into an isolated prefix so we can COPY it cheaply
RUN pip install --upgrade pip \
    && pip install --prefix=/install --no-cache-dir -r requirements.txt


# ── Stage 2: Lean runtime image ─────────────────────────────
FROM python:3.12-slim AS runtime

# Security: run as non-root
RUN groupadd -r robot && useradd -r -g robot robot

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# App directory
WORKDIR /app

# Copy application source
COPY . .

# SQLite databases will be written here (per-robot)
RUN mkdir -p /app/data && chown -R robot:robot /app/data

# Metadata labels (OCI image spec)
LABEL org.opencontainers.image.title="warehouse-robot-simulator" \
      org.opencontainers.image.description="Autonomous warehouse robot fleet simulator" \
      org.opencontainers.image.version="1.0.0"

USER robot

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app

ENTRYPOINT ["python", "-m", "main"]
