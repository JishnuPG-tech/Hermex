# ==============================================================================
# Hermes Agent Space — OmniRoute + Ignis + Hermes
# Multi-stage: prebuilt OmniRoute + Python 3.11 + Redis 7 + Nginx + Node.js
# ==============================================================================

# Stage 1: Extract prebuilt OmniRoute production runtime
FROM diegosouzapw/omniroute:main AS omniroute-source

# Stage 2: Final multi-service runtime
# Cache bust: 2026-08-25T16:00:32
FROM python:3.11-slim

ENV HOME=/root
ENV HERMES_HOME=/root/.hermes
ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=1

# Runtime system packages: Redis 7, Nginx + brotli module, SQLite tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    git \
    sqlite3 \
    redis-server \
    nginx \
    rsync \
    procps \
    ffmpeg \
 && rm -rf /var/lib/apt/lists/*

# Copy OmniRoute from upstream image (prebuilt, no npm install)
COPY --from=omniroute-source /app /omniroute
COPY --from=omniroute-source /usr/local/bin/node /usr/local/bin/node
COPY --from=omniroute-source /usr/local/bin/npm /usr/local/bin/npm
COPY --from=omniroute-source /usr/local/bin/npx /usr/local/bin/npx
COPY --from=omniroute-source /usr/local/lib/node_modules /usr/local/lib/node_modules

# Python dependencies
RUN pip3 install --no-cache-dir \
    aiohttp \
    aiofiles \
    python-multipart \
    httpx \
    hermes-agent \
    edge-tts

# Copy Ignis (Obsidian vault server)
COPY ignis/ /ignis/
RUN cd /ignis && npm install --production 2>/dev/null || true

# Copy gateway + config + daemon scripts
COPY gateway /gateway
COPY entrypoint.sh /entrypoint.sh
COPY nginx.conf /nginx.conf
COPY health_doctor.py /health_doctor.py
COPY fix_omniroute.py /fix_omniroute.py
COPY clean_db.py /clean_db.py
RUN chmod +x /entrypoint.sh

# Create all required directories
RUN mkdir -p \
    /root/.cache \
    /root/.omniroute \
    /root/.hermes \
    /data/cache \
    /data/hermes \
    /data/hermes/sessions \
    /data/hermes/memories \
    /data/hermes/skills \
    /data/vaults \
    /data/omniroute \
    /data/omniroute/backups

RUN chmod -R 777 /root/.cache /data/cache /data/hermes /data/vaults /omniroute

ENV PYTHONPATH=/:/gateway
WORKDIR /

EXPOSE 7860

ENTRYPOINT ["/entrypoint.sh"]
# Force rebuild 08/25/2026 15:18:45
# Rebuild 08/25/2026 15:51:27
