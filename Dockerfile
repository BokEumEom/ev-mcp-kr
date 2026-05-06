# syntax=docker/dockerfile:1.7

# ----- builder ---------------------------------------------------------------
FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    DEBIAN_FRONTEND=noninteractive \
    UV_LINK_MODE=copy

# Apply latest security patches over the base image, then drop apt caches.
RUN apt-get update && \
    apt-get upgrade -y && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# uv for fast resolves; pin to a known version.
COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /usr/local/bin/uv

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src/ ./src/

# Build a self-contained virtualenv at /opt/venv with only runtime deps.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv venv /opt/venv && \
    UV_PROJECT_ENVIRONMENT=/opt/venv uv pip install --python /opt/venv/bin/python .

# ----- runtime ---------------------------------------------------------------
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    HOST=0.0.0.0 \
    PORT=8000 \
    LOG_LEVEL=INFO \
    DEBIAN_FRONTEND=noninteractive

# Latest security patches in the runtime layer too.
RUN apt-get update && \
    apt-get upgrade -y && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/* && \
    groupadd --system app && \
    useradd --system --gid app --home /home/app --create-home app

COPY --from=builder /opt/venv /opt/venv
COPY src/ /app/src/
COPY scripts/healthcheck.py /app/scripts/healthcheck.py
COPY pyproject.toml README.md /app/

WORKDIR /app
USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "/app/scripts/healthcheck.py"]

# Single-worker by design — see docs/PHASE3.md for the per-worker cache caveat.
CMD ["ev-mcp"]
