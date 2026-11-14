# ==============================================================================
# Danqing (丹青) Zero-Cost Cloud Deployment Dockerfile
# Compatible out-of-the-box with Render Free Tier ($0/month, no credit card,
# DANQING_LOW_MEMORY=1, PORT=10000) as well as standard self-hosted Docker.
# ==============================================================================

# Stage 1: Build Frontend SPA
FROM node:22-slim AS frontend-builder
WORKDIR /build/web/frontend
RUN corepack enable
COPY web/frontend/package.json web/frontend/pnpm-lock.yaml* ./
RUN pnpm install --frozen-lockfile || pnpm install
COPY web/frontend/ ./
RUN pnpm build

# Stage 2: Stateless Zero-Retention Python Runtime (Non-Root UID 1000)
FROM python:3.11-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=7860

RUN useradd -m -u 1000 danqing
WORKDIR /app

COPY pyproject.toml README.md* ./
COPY core/ ./core/
RUN pip install --upgrade pip && pip install .

COPY web/backend/ ./web/backend/
COPY bench/figures/ ./bench/figures/
COPY --from=frontend-builder /build/web/frontend/dist ./web/frontend/dist

RUN chown -R danqing:danqing /app
USER danqing

EXPOSE 7860
CMD ["sh", "-c", "uvicorn web.backend.app:app --host 0.0.0.0 --port ${PORT:-7860} --no-access-log"]
