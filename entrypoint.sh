#!/bin/bash
set -eo pipefail

echo "========================================================"
echo "=== Hermes Agent + Knowledge Space Starting          ==="
echo "========================================================"

# Step 1: Directory Setup on Persistent /data Volume
mkdir -p /data/hermes /data/obsidian/vault /data/backups /tmp/run

export OBSIDIAN_VAULT_DIR="/data/obsidian/vault"
export HERMES_MEMORY_DB="/data/hermes/memory.sqlite"
export PYTHONPATH="/app:${PYTHONPATH}"

# Step 2: Secret & Environment Verification
if [ -z "$UPSTREAM_OMNIROUTE_URL" ]; then
    export UPSTREAM_OMNIROUTE_URL="https://jishnupg-opencode-cli.hf.space/v1"
fi
echo "[BOOT] Upstream LLM Gateway: ${UPSTREAM_OMNIROUTE_URL}"

# Step 3: Start Redis Server
echo "[INIT] Starting Redis server on port 6379..."
redis-server --daemonize yes --port 6379 --bind 127.0.0.1

# Step 4: Start Health Doctor Checkpointer
echo "[INIT] Starting Persistence Health Doctor..."
python3 /app/health_doctor.py > /dev/stdout 2>&1 &
DOCTOR_PID=$!

# Step 5: Start Ignis Obsidian Vault Service (:8080)
echo "[INIT] Starting Ignis Obsidian Vault Server on port 8080..."
python3 /app/ignis/server.py > /dev/stdout 2>&1 &
IGNIS_PID=$!

# Step 6: Start Hermes Agent Core (:8642)
echo "[INIT] Starting Hermes Agent Core on port 8642..."
python3 /app/hermes_core/agent.py > /dev/stdout 2>&1 &
HERMES_PID=$!

# Step 7: Start Telegram Bot Handler (Background if token provided)
if [ -n "$TELEGRAM_BOT_TOKEN" ]; then
    echo "[INIT] Starting Hermes Telegram Bot listener..."
    python3 /app/hermes_core/telegram_bot.py > /dev/stdout 2>&1 &
    TG_PID=$!
fi

# Step 8: Start FastAPI Gateway (:8000)
echo "[INIT] Starting FastAPI Ingress Gateway on port 8000..."
uvicorn gateway.main:app --host 127.0.0.1 --port 8000 --workers 2 > /dev/stdout 2>&1 &
GATEWAY_PID=$!

# Wait briefly for backends to bind
sleep 2

# Step 9: Start Nginx Edge Ingress (:7860) in Foreground
echo "[INIT] Starting Nginx Edge Ingress on port 7860..."
exec /usr/sbin/nginx -c /app/nginx.conf
