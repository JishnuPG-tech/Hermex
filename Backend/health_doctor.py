#!/usr/bin/env python3
"""
health_doctor.py — SQLite health monitor + backup rotation daemon.

Runs every 5 minutes. Checks:
- PRAGMA quick_check on all SQLite files
- /data disk capacity (warns if >85%)
- Purges database snapshots older than 5 days
- Creates last-known-good.sqlite backup on clean check
"""
import os
import sys
import time
import shutil
import glob
import logging
from datetime import datetime, timedelta

logging.basicConfig(
    level=logging.INFO,
    format="[health_doctor %(asctime)s] %(levelname)s — %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("/data/cache/health_doctor.log", mode="a", encoding="utf-8"),
    ],
)
log = logging.getLogger("health_doctor")

# ── Paths ───────────────────────────────────────────────────────
DATA_DIR = "/data"
OMNIROUTE_DB = "/data/omniroute/storage.sqlite"
HERMES_DB = "/data/hermes/sessions/conversations.db"
BACKUP_DIR = "/data/omniroute/backups"
DB_BACKUP_DIR = "/data/omniroute"
SNAPSHOT_PATTERN = "storage-*.sqlite"
LKG_FILE = "last-known-good.sqlite"
BACKUP_RETENTION_DAYS = 5
CHECK_INTERVAL = 300  # 5 minutes
DISK_WARN_THRESHOLD = 85  # percent


def check_sqlite_health(db_path: str) -> dict:
    """Run PRAGMA quick_check on a SQLite database."""
    import sqlite3
    result = {"path": db_path, "exists": os.path.exists(db_path), "healthy": True, "details": "Not initialized yet (OK)"}

    if not result["exists"]:
        return result

    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5)
        cursor = conn.execute("PRAGMA quick_check")
        row = cursor.fetchone()
        result["healthy"] = row[0] == "ok"
        result["details"] = row[0] if row else "empty result"

        # Additional info
        cursor = conn.execute("PRAGMA page_count")
        page_count = cursor.fetchone()[0]
        cursor = conn.execute("PRAGMA page_size")
        page_size = cursor.fetchone()[0]
        result["size_bytes"] = page_count * page_size
        result["size_mb"] = round((page_count * page_size) / (1024 * 1024), 2)

        # WAL checkpoint
        try:
            conn.execute("PRAGMA wal_checkpoint(PASSIVE)")
        except Exception:
            pass

        conn.close()
    except sqlite3.DatabaseError as e:
        result["details"] = f"Database error: {e}"
    except Exception as e:
        result["details"] = f"Unexpected error: {e}"

    return result


def check_disk_usage() -> dict:
    """Check disk usage on the data volume."""
    result = {"path": DATA_DIR, "percent_used": 0, "free_gb": 0, "total_gb": 0}
    try:
        usage = shutil.disk_usage(DATA_DIR)
        result["total_gb"] = round(usage.total / (1024**3), 2)
        result["free_gb"] = round(usage.free / (1024**3), 2)
        result["percent_used"] = round((usage.used / usage.total) * 100, 1)
    except Exception as e:
        log.warning(f"Disk check failed: {e}")
    return result


def ensure_dirs():
    """Create required directories."""
    os.makedirs(BACKUP_DIR, exist_ok=True)
    os.makedirs(DB_BACKUP_DIR, exist_ok=True)
    os.makedirs("/data/cache", exist_ok=True)


def rotate_snapshots():
    """Purge old backup snapshots and create last-known-good."""
    now = datetime.now()
    cutoff = now - timedelta(days=BACKUP_RETENTION_DAYS)

    # Delete old snapshots
    deleted = 0
    for f in glob.glob(os.path.join(BACKUP_DIR, SNAPSHOT_PATTERN)):
        try:
            mtime = datetime.fromtimestamp(os.path.getmtime(f))
            if mtime < cutoff:
                os.remove(f)
                deleted += 1
                log.info(f"Purged old snapshot: {os.path.basename(f)}")
        except Exception as e:
            log.warning(f"Failed to delete {f}: {e}")

    # Create last-known-good backup ONLY if current DB is healthy
    if os.path.exists(OMNIROUTE_DB) and check_sqlite_health(OMNIROUTE_DB).get("healthy", False):
        lkg_path = os.path.join(DB_BACKUP_DIR, LKG_FILE)
        try:
            shutil.copy2(OMNIROUTE_DB, lkg_path)
            log.info(f"Updated last-known-good backup: {lkg_path}")
        except Exception as e:
            log.warning(f"Failed to create LKG backup: {e}")

    return deleted


def create_snapshot():
    """Create a timestamped snapshot of the active DB."""
    if not os.path.exists(OMNIROUTE_DB):
        return
    now = datetime.now().strftime("%Y%m%d-%H%M")
    snapshot_path = os.path.join(BACKUP_DIR, f"storage-{now}.sqlite")
    try:
        import sqlite3
        conn = sqlite3.connect(f"file:{OMNIROUTE_DB}?mode=ro", uri=True, timeout=5)
        backup = sqlite3.connect(snapshot_path)
        conn.backup(backup)
        backup.close()
        conn.close()
        log.info(f"Created snapshot: {os.path.basename(snapshot_path)}")
    except Exception as e:
        log.warning(f"Snapshot failed: {e}")


def run_check_cycle():
    """Single health check cycle."""
    ensure_dirs()
    log.info("=== Health Check Cycle ===")

    # Check SQLite databases
    for db_path in [OMNIROUTE_DB, HERMES_DB]:
        result = check_sqlite_health(db_path)
        status = "HEALTHY" if result["healthy"] else "UNHEALTHY"
        log.info(f"  {result['path']}: {status} — {result['details']} "
                 f"({result.get('size_mb', '?')} MB)")

    # Check disk
    disk = check_disk_usage()
    log.info(f"  Disk: {disk['percent_used']}% used, {disk['free_gb']} GB free")
    if disk["percent_used"] >= DISK_WARN_THRESHOLD:
        log.warning(f"  ⚠ DISK WARNING: {disk['percent_used']}% used "
                    f"(threshold: {DISK_WARN_THRESHOLD}%)")

    # Rotate snapshots
    deleted = rotate_snapshots()
    if deleted:
        log.info(f"  Purged {deleted} old snapshots")


def main():
    """Daemon loop."""
    log.info("Health Doctor starting (interval: 5 minutes)")
    while True:
        try:
            run_check_cycle()
        except Exception as e:
            log.error(f"Check cycle failed: {e}")
        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
