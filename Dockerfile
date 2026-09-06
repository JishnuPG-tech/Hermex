FROM node:24-bookworm-slim AS web-build

WORKDIR /web

RUN corepack enable && corepack prepare pnpm@10.26.1 --activate

COPY package.json pnpm-lock.yaml pnpm-workspace.yaml tsconfig.base.json tsconfig.json ./
COPY artifacts/hermes-web/package.json artifacts/hermes-web/package.json

RUN pnpm install --frozen-lockfile

COPY artifacts/hermes-web artifacts/hermes-web

RUN pnpm --filter @workspace/hermes-web run build

FROM python:3.11-slim-bookworm

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV HERMES_SERVER_WORKDIR=/app
ENV HERMES_MAX_TOOL_ROUNDS=6

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    nginx \
    redis-server \
    sqlite3 \
    git \
    curl \
    ca-certificates \
    procps \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Install Python requirements
RUN pip install --no-cache-dir \
    fastapi \
    "uvicorn[standard]" \
    httpx \
    aiohttp \
    requests \
    beautifulsoup4 \
    pydantic \
    python-multipart \
    pyjwt \
    cryptography \
    edge-tts

# Copy application files
COPY gateway /app/gateway
# The root tree keeps the gateway import stable while reusing the complete
# historical Anthropic and Claude REST bridges. Their imports resolve against
# /app/gateway.
COPY Backend/gateway/__init__.py /app/Backend/gateway/__init__.py
COPY Backend/gateway/anthropic_bridge.py /app/Backend/gateway/anthropic_bridge.py
COPY Backend/gateway/claude_rest_api.py /app/Backend/gateway/claude_rest_api.py
COPY hermes_core /app/hermes_core
COPY ignis /app/ignis
COPY --from=web-build /web/artifacts/hermes-web/dist /app/web
COPY health_doctor.py /app/health_doctor.py
COPY nginx.conf /app/nginx.conf
COPY entrypoint.sh /app/entrypoint.sh
COPY README.md /app/README.md

RUN chmod +x /app/entrypoint.sh

EXPOSE 7860 4096

ENTRYPOINT ["/app/entrypoint.sh"]
