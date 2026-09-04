FROM python:3.11-slim-bookworm

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    nginx \
    redis-server \
    sqlite3 \
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
    requests \
    beautifulsoup4 \
    pydantic \
    python-multipart \
    pyjwt \
    cryptography \
    edge-tts

# Copy application files
COPY gateway /app/gateway
COPY hermes_core /app/hermes_core
COPY ignis /app/ignis
COPY health_doctor.py /app/health_doctor.py
COPY nginx.conf /app/nginx.conf
COPY entrypoint.sh /app/entrypoint.sh
COPY README.md /app/README.md

RUN chmod +x /app/entrypoint.sh

EXPOSE 7860 4096

ENTRYPOINT ["/app/entrypoint.sh"]
