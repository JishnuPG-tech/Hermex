#!/bin/sh
set -e

log_info() { echo "$(date -u '+%Y-%m-%d %H:%M:%S') [INFO] [HERMES] $1"; }
log_error() { echo "$(date -u '+%Y-%m-%d %H:%M:%S') [ERROR] [HERMES] $1"; }

# ── Config ──────────────────────────────────────────────────────
OMNIROUTE_BASE_URL="${OMNIROUTE_BASE_URL:-http://127.0.0.1:20128/v1}"
OMNIROUTE_API_KEY="${OMNIROUTE_API_KEY:-sk-2e556e0437ee2958-7baf2d-b4133935}"
HERMES_MODEL="${HERMES_MODEL:-auto/smart}"
HERMES_INTERNAL_PORT="${HERMES_INTERNAL_PORT:-8642}"
PUBLIC_PORT="${PUBLIC_PORT:-7860}"
API_SERVER_KEY="${API_SERVER_KEY:-${OMNIROUTE_API_KEY}}"
HERMES_HOME="${HERMES_HOME:-/root/.hermes}"
OMNIROUTE_ACTIVE="/root/.omniroute"
OMNIROUTE_DATA="/data/omniroute"
# Enable internal OmniRoute for instant local routing & zero external latency
SKIP_INTERNAL_OMNIROUTE="${SKIP_INTERNAL_OMNIROUTE:-false}"

export OMNIROUTE_BASE_URL OMNIROUTE_API_KEY API_SERVER_KEY HERMES_INTERNAL_PORT

log_info "OmniRoute backend : ${OMNIROUTE_BASE_URL}"
log_info "Hermes model      : ${HERMES_MODEL}"
log_info "Hermes port       : ${HERMES_INTERNAL_PORT}"
log_info "Public port       : ${PUBLIC_PORT}"

mkdir -p "${HERMES_HOME}" /data/hermes /data/cache /data/vaults "${OMNIROUTE_DATA}" "${OMNIROUTE_ACTIVE}" "${OMNIROUTE_DATA}/backups"

# ── Persistent Secret Key Storage ───────────────────────────────
# Random keys on every boot cause [Encryption] Decryption failed errors.
# Save generated keys to /data so they survive container restarts.
ENCRYPTION_KEY_FILE="${OMNIROUTE_DATA}/.encryption_key"
if [ -f "${ENCRYPTION_KEY_FILE}" ]; then
    ENCRYPTION_KEY=$(cat "${ENCRYPTION_KEY_FILE}")
    log_info "Loaded existing encryption key from ${ENCRYPTION_KEY_FILE}"
else
    ENCRYPTION_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")
    echo "${ENCRYPTION_KEY}" > "${ENCRYPTION_KEY_FILE}"
    chmod 600 "${ENCRYPTION_KEY_FILE}"
    log_info "Generated new encryption key"
fi
export ENCRYPTION_KEY

# ── JWT_SECRET (HMAC-SHA256 for user sessions) ──────────────────
JWT_SECRET_FILE="${OMNIROUTE_DATA}/.jwt_secret"
if [ -f "${JWT_SECRET_FILE}" ]; then
    JWT_SECRET=$(cat "${JWT_SECRET_FILE}")
    log_info "Loaded existing JWT secret"
else
    JWT_SECRET=$(python3 -c "import secrets; print(secrets.token_hex(32))")
    echo "${JWT_SECRET}" > "${JWT_SECRET_FILE}"
    chmod 600 "${JWT_SECRET_FILE}"
    log_info "Generated new JWT secret"
fi
export JWT_SECRET

# ── API_KEY_SECRET (master bearer auth) ─────────────────────────
API_KEY_SECRET_FILE="${OMNIROUTE_DATA}/.api_key_secret"
if [ -f "${API_KEY_SECRET_FILE}" ]; then
    API_KEY_SECRET=$(cat "${API_KEY_SECRET_FILE}")
    log_info "Loaded existing API key secret"
else
    API_KEY_SECRET="${OMNIROUTE_API_KEY}"
    echo "${API_KEY_SECRET}" > "${API_KEY_SECRET_FILE}"
    chmod 600 "${API_KEY_SECRET_FILE}"
    log_info "Set API key secret"
fi
export API_KEY_SECRET

# ── Key-Hash Guard (detect key rotation, archive DB) ────────────
log_info "Running key-hash guard (clean_db.py)..."
python3 /clean_db.py 2>&1 | tee /data/cache/clean_db.log || true

# ── Fix OmniRoute DB (startup migration collision resolver) ─────
log_info "Running OmniRoute DB fix and migration..."
python3 /fix_omniroute.py 2>&1 | tee /data/cache/fix_omniroute.log || true

# ── Restore persistent state (dual-layer SQLite) ────────────────
# Active DB: /root/.omniroute/storage.sqlite (fast local disk)
# Backup DB: /data/omniroute/storage.sqlite (persistent volume)
# Uses PRAGMA wal_checkpoint(PASSIVE) + .backup to avoid POSIX locking issues.
if [ -d /data/hermes ] && [ "$(ls -A /data/hermes 2>/dev/null)" ]; then
    cp -af /data/hermes/. "${HERMES_HOME}/" 2>/dev/null || true
    log_info "Restored Hermes state from /data/hermes"
fi

# ── Bootstrap Hermes config ─────────────────────────────────────
cat > "${HERMES_HOME}/config.yaml" <<EOF
model:
  provider: omniroute
  default: ${HERMES_MODEL}
  direct_model_requests: true
providers:
  omniroute:
    base_url: ${OMNIROUTE_BASE_URL}
    api_key: ${OMNIROUTE_API_KEY}
memory:
  enabled: true
  sqlite_fts5: true
gateway:
  platforms:
    api_server:
      enabled: true
      host: 127.0.0.1
      port: ${HERMES_INTERNAL_PORT}
      key: ${API_SERVER_KEY}
      cors_origins: "*"
EOF

cat > "${HERMES_HOME}/.env" <<EOF
API_SERVER_ENABLED=true
API_SERVER_HOST=127.0.0.1
API_SERVER_PORT=${HERMES_INTERNAL_PORT}
API_SERVER_KEY=${API_SERVER_KEY}
API_SERVER_CORS_ORIGINS=*
HERMES_MODEL=${HERMES_MODEL}
DEFAULT_MODEL=${HERMES_MODEL}
HERMES_API_BASE_URL=${OMNIROUTE_BASE_URL}
HERMES_API_KEY=${OMNIROUTE_API_KEY}
OMNIROUTE_API_KEY=${OMNIROUTE_API_KEY}
JWT_SECRET=${JWT_SECRET}
API_KEY_SECRET=${API_KEY_SECRET}
ENCRYPTION_KEY=${ENCRYPTION_KEY}
EOF

chmod -R 777 "${HERMES_HOME}" /data/hermes 2>/dev/null || true

# ── 30s dual-layer SQLite sync daemon ───────────────────────────
# Active DB runs on high-speed container local disk.
# Background daemon executes PRAGMA wal_checkpoint(PASSIVE) and
# .backup to /data/omniroute/storage.sqlite every 30 seconds.
(
    while true; do
        sleep 30
        mkdir -p /data/hermes /data/vaults "${OMNIROUTE_DATA}" "${OMNIROUTE_DATA}/backups" 2>/dev/null || true

        # Hermes state sync
        rsync -a --update "${HERMES_HOME}/." /data/hermes/ 2>/dev/null \
            || cp -rf "${HERMES_HOME}/." /data/hermes/ 2>/dev/null || true

        # Dual-layer SQLite sync: active -> /data with WAL checkpoint
        if [ -f "${OMNIROUTE_ACTIVE}/storage.sqlite" ]; then
            python3 << 'PYEOF'
import sqlite3
try:
    src = sqlite3.connect('file:/root/.omniroute/storage.sqlite?mode=ro', uri=True, timeout=5)
    src.execute('PRAGMA wal_checkpoint(PASSIVE)')
    dst = sqlite3.connect('/data/omniroute/storage.sqlite', timeout=5)
    src.backup(dst)
    dst.close()
    src.close()
except Exception as e:
    pass
PYEOF
        fi
    done
) &
log_info "30s dual-layer SQLite sync daemon started"

# ── Health Doctor daemon (every 5 minutes) ──────────────────────
python3 /health_doctor.py &
log_info "Health Doctor daemon started (5-minute interval)"

# ── Start Redis 7 ───────────────────────────────────────────────
log_info "Starting Redis 7 on 127.0.0.1:6379"
redis-server --port 6379 --bind 127.0.0.1 --save "" --appendonly no --daemonize yes 2>&1 | tee /data/cache/redis.log || true
REDIS_PID=$(pgrep -f "redis-server" | head -1) || true

i=0
while [ $i -lt 10 ]; do
    if redis-cli -h 127.0.0.1 -p 6379 ping 2>/dev/null | grep -q PONG; then
        log_info "Redis ready after ${i}s"
        break
    fi
    i=$((i + 1))
    sleep 1
done

# ── Start Hermes Agent :8642 ────────────────────────────────────
# Start Hermes agent in internal API server mode (Messaging channels managed via Gateway Webhooks)
export GATEWAY_ALLOW_ALL_USERS=true
(
    unset TELEGRAM_BOT_TOKEN TELEGRAM_ALLOWED_USERS
    hermes gateway run 2>&1 | tee /data/cache/hermes.log
) &
HERMES_PID=$!

i=0
while [ $i -lt 90 ]; do
    if curl -fsS "http://127.0.0.1:${HERMES_INTERNAL_PORT}/health" >/dev/null 2>&1; then
        log_info "Hermes agent healthy after ${i}s"
        break
    fi
    i=$((i + 1))
    sleep 1
done

# ── Start OmniRoute :20128 (unified dashboard + API) ────────────
# Skip internal OmniRoute if SKIP_INTERNAL_OMNIROUTE=true (use external instead)
if [ "$SKIP_INTERNAL_OMNIROUTE" = "true" ]; then
    log_info "Skipping internal OmniRoute (using external: ${OMNIROUTE_BASE_URL})"
    OMNIROUTE_PID=""
else
    # Turbopack standalone build: dashboard + API on single port.
    # Live WebSocket on :20132, Embed WebSocket on :20131.
    log_info "Starting OmniRoute AI Gateway on 127.0.0.1:20128"
    export PORT=20128
    export HOSTNAME="127.0.0.1"
    export DATA_DIR="${OMNIROUTE_ACTIVE}"
    export CLI_COMPAT_CLAUDE=1
    export CLI_COMPAT_ANTIGRAVITY=1
    export CLI_COMPAT_GITHUB=1
    export OMNIROUTE_REQUIRE_API_KEY=false
    export OMNIROUTE_ALLOW_UNAUTHENTICATED=true
    export INITIAL_PASSWORD="${OMNIROUTE_API_KEY}"
    export ENCRYPTION_KEY="${ENCRYPTION_KEY}"
    export JWT_SECRET="${JWT_SECRET}"

    cd /omniroute
    if [ -f "server.js" ]; then
        node server.js > /data/cache/omniroute.log 2>&1 &
    else
        npm run start > /data/cache/omniroute.log 2>&1 &
    fi
    OMNIROUTE_PID=$!

    i=0
    while [ $i -lt 60 ]; do
        if curl -fsS "http://127.0.0.1:20128/api/monitoring/health" >/dev/null 2>&1; then
            log_info "OmniRoute ready after ${i}s"
            break
        fi
        i=$((i + 1))
        sleep 1
    done
fi

# ── Start Ignis (Obsidian) :8080 ───────────────────────────────
if [ -d "/ignis" ]; then
    log_info "Starting Ignis Obsidian on 127.0.0.1:8080"
    cd /ignis
    if [ -f "server.py" ]; then
        python3 server.py > /data/cache/ignis.log 2>&1 &
    else
        node server.js > /data/cache/ignis.log 2>&1 &
    fi
    IGNIS_PID=$!

    i=0
    while [ $i -lt 20 ]; do
        if curl -fsS "http://127.0.0.1:8080/obsidian/health" >/dev/null 2>&1 || curl -fsS "http://127.0.0.1:8080/health" >/dev/null 2>&1; then
            log_info "Ignis ready after ${i}s"
            break
        fi
        i=$((i + 1))
        sleep 1
    done
fi

# ── Start FastAPI Gateway :8000 ─────────────────────────────────
log_info "Starting FastAPI Gateway on 127.0.0.1:8000"
python3 -m uvicorn gateway.main:app \
    --host 127.0.0.1 \
    --port 8000 \
    --workers 1 2>&1 | tee /data/cache/gateway.log &
FASTAPI_PID=$!

i=0
while [ $i -lt 30 ]; do
    if curl -fsS "http://127.0.0.1:8000/" >/dev/null 2>&1; then
        log_info "FastAPI Gateway healthy after ${i}s"
        break
    fi
    i=$((i + 1))
    sleep 1
done

# ── Start Nginx :7860 (public edge with compression) ────────────
log_info "Starting Nginx on port ${PUBLIC_PORT} (gzip compression)"
nginx -g 'daemon off;' -c /nginx.conf &
NGINX_PID=$!

# ── Graceful Shutdown Trap ──────────────────────────────────────
cleanup() {
    log_info "Shutdown signal received. Stopping all services..."
    kill $FASTAPI_PID 2>/dev/null || true
    kill $NGINX_PID 2>/dev/null || true
    kill $IGNIS_PID 2>/dev/null || true
    if [ -n "$OMNIROUTE_PID" ]; then
        kill $OMNIROUTE_PID 2>/dev/null || true
    fi
    kill $HERMES_PID 2>/dev/null || true
    kill $REDIS_PID 2>/dev/null || true

    # Final persistence sync
    rsync -a --update "${HERMES_HOME}/." /data/hermes/ 2>/dev/null || true
    if [ -f "${OMNIROUTE_ACTIVE}/storage.sqlite" ]; then
        sqlite3 "${OMNIROUTE_ACTIVE}/storage.sqlite" "PRAGMA wal_checkpoint(TRUNCATE);" 2>/dev/null || true
        cp -f "${OMNIROUTE_ACTIVE}/storage.sqlite" "${OMNIROUTE_DATA}/storage.sqlite" 2>/dev/null || true
    fi

    log_info "All services stopped. Goodbye."
    exit 0
}

trap cleanup 1 2 15

# ── Supervisor loop (health-check based, not kill -0) ───────────
log_info "All services dispatched. Supervisor active."
while true; do
    sleep 10

    # Nginx: check if port 7860 responds
    if ! curl -fsS "http://127.0.0.1:7860/" >/dev/null 2>&1; then
        log_error "Nginx down, restarting..."
        nginx -g 'daemon off;' -c /nginx.conf &
        NGINX_PID=$!
        sleep 2
    fi

    # FastAPI: check if port 8000 responds
    if ! curl -fsS "http://127.0.0.1:8000/" >/dev/null 2>&1; then
        log_error "FastAPI down, restarting..."
        python3 -m uvicorn gateway.main:app --host 127.0.0.1 --port 8000 --workers 1 &
        FASTAPI_PID=$!
        sleep 2
    fi

    # Hermes: check if port 8642 responds
    if ! curl -fsS "http://127.0.0.1:8642/health" >/dev/null 2>&1; then
        log_error "Hermes down, restarting..."
        hermes gateway run 2>&1 | tee /data/cache/hermes.log &
        HERMES_PID=$!
        sleep 2
    fi

    # OmniRoute: check if port 20128 responds (only if not skipped)
    if [ "$SKIP_INTERNAL_OMNIROUTE" != "true" ]; then
        if ! curl -fsS "http://127.0.0.1:20128/api/monitoring/health" >/dev/null 2>&1; then
            log_error "OmniRoute down, restarting..."
            cd /omniroute && node server.js > /data/cache/omniroute.log 2>&1 &
            OMNIROUTE_PID=$!
            sleep 2
        fi
    fi

    # Ignis: check if port 8080 responds
    if ! curl -fsS "http://127.0.0.1:8080/obsidian/health" >/dev/null 2>&1 && ! curl -fsS "http://127.0.0.1:8080/health" >/dev/null 2>&1; then
        log_error "Ignis down, restarting..."
        cd /ignis
        if [ -f "server.py" ]; then
            python3 server.py > /data/cache/ignis.log 2>&1 &
        else
            node server.js > /data/cache/ignis.log 2>&1 &
        fi
        IGNIS_PID=$!
        sleep 2
    fi

    # Redis: check if port 6379 responds
    if ! redis-cli -h 127.0.0.1 -p 6379 ping 2>/dev/null | grep -q PONG; then
        log_error "Redis down, restarting..."
        redis-server --port 6379 --bind 127.0.0.1 --save "" --appendonly no --daemonize yes 2>/dev/null || true
        sleep 2
    fi
done



