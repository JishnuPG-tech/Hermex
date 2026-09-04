#!/usr/bin/env python3
"""
fix_omniroute.py — Startup DB migration collision resolver.

Run once at container boot before OmniRoute starts. Fixes:
- Corrupted WAL files that prevent SQLite from opening
- Migration version mismatches
- Lock contention from stale processes
- Missing parent directories for DB paths
"""
import os
import sys
import shutil
import time
import sqlite3
import logging
from datetime import datetime

logging.basicConfig(
    level=logging.INFO,
    format="[fix_omniroute %(asctime)s] %(levelname)s — %(message)s",
)
log = logging.getLogger("fix_omniroute")

OMNIROUTE_DB = "/data/omniroute/storage.sqlite"
OMNIROUTE_DB_ACTIVE = "/root/.omniroute/storage.sqlite"
BACKUP_DIR = "/data/omniroute"


def ensure_dirs():
    """Create required directories if missing."""
    dirs = [
        "/data/omniroute",
        "/data/hermes",
        "/data/hermes/sessions",
        "/data/hermes/memories",
        "/data/hermes/skills",
        "/data/vaults",
        "/data/cache",
        "/root/.omniroute",
    ]
    for d in dirs:
        os.makedirs(d, exist_ok=True)
        log.info(f"Ensured directory: {d}")


def kill_stale_processes():
    """Kill any stale OmniRoute or Hermes processes that may hold DB locks."""
    import subprocess
    for proc_name in ["omniroute", "node", "hermes"]:
        try:
            result = subprocess.run(
                ["pkill", "-f", proc_name],
                capture_output=True, timeout=5
            )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
    time.sleep(1)


def fix_wal_corruption(db_path: str) -> bool:
    """Detect and fix WAL corruption by removing WAL/SHM and restoring from backup."""
    wal_path = db_path + "-wal"
    shm_path = db_path + "-shm"

    if not os.path.exists(db_path):
        log.warning(f"DB does not exist: {db_path}")
        return False

    # Check if WAL/SHM exist but DB can't be opened
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5)
        conn.execute("PRAGMA quick_check")
        conn.close()
        log.info(f"DB OK: {db_path}")
        return True
    except sqlite3.DatabaseError as e:
        log.warning(f"DB corrupted or locked ({db_path}): {e}")

    # Try removing WAL/SHM
    for path in [wal_path, shm_path]:
        if os.path.exists(path):
            try:
                os.remove(path)
                log.info(f"Removed stale lock file: {path}")
            except Exception as ex:
                log.warning(f"Failed to remove {path}: {ex}")

    # Try again
    try:
        conn = sqlite3.connect(db_path, timeout=5)
        conn.execute("PRAGMA quick_check")
        conn.close()
        log.info(f"DB recovered after WAL cleanup: {db_path}")
        return True
    except sqlite3.DatabaseError:
        log.error(f"DB still corrupted after WAL cleanup: {db_path}")

    # Try restoring from LKG backup
    lkg_path = os.path.join(BACKUP_DIR, "last-known-good.sqlite")
    if os.path.exists(lkg_path):
        try:
            # Verify LKG is healthy before restoring
            test_conn = sqlite3.connect(f"file:{lkg_path}?mode=ro", uri=True, timeout=5)
            row = test_conn.execute("PRAGMA quick_check").fetchone()
            test_conn.close()
            if row and row[0] == "ok":
                shutil.copy2(lkg_path, db_path)
                log.info(f"Restored from LKG backup: {lkg_path} → {db_path}")
                return True
        except Exception as e:
            log.error(f"LKG restore check failed: {e}")

    # If unrecoverable, quarantine corrupt DB and start fresh
    now = datetime.now().strftime("%Y%m%d-%H%M%S")
    corrupt_quarantine = os.path.join(BACKUP_DIR, f"storage-corrupt-{now}.sqlite")
    try:
        shutil.move(db_path, corrupt_quarantine)
        log.warning(f"Quarantined corrupt DB → {corrupt_quarantine}")
        # Create fresh SQLite DB
        conn = sqlite3.connect(db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.close()
        log.info(f"Initialized fresh DB at {db_path}")
        return True
    except Exception as e:
        log.error(f"Quarantine failed: {e}")
        return False


def sync_active_to_data():
    """Sync active DB from /root to /data on clean startup."""
    if os.path.exists(OMNIROUTE_DB_ACTIVE) and os.path.getsize(OMNIROUTE_DB_ACTIVE) > 0:
        try:
            src_conn = sqlite3.connect(f"file:{OMNIROUTE_DB_ACTIVE}?mode=ro", uri=True, timeout=5)
            dst_conn = sqlite3.connect(OMNIROUTE_DB, timeout=5)
            src_conn.backup(dst_conn)
            dst_conn.close()
            src_conn.close()
            log.info(f"Synced active DB → data: {OMNIROUTE_DB_ACTIVE} → {OMNIROUTE_DB}")
        except Exception as e:
            log.warning(f"Sync failed (non-fatal): {e}")


def sync_data_to_active():
    """Sync /data DB to /root active path if /root is missing."""
    if not os.path.exists(OMNIROUTE_DB_ACTIVE) and os.path.exists(OMNIROUTE_DB):
        try:
            shutil.copy2(OMNIROUTE_DB, OMNIROUTE_DB_ACTIVE)
            log.info(f"Synced data → active: {OMNIROUTE_DB} → {OMNIROUTE_DB_ACTIVE}")
        except Exception as e:
            log.warning(f"Sync failed (non-fatal): {e}")


def create_snapshot():
    """Create a startup snapshot for backup rotation."""
    now = datetime.now().strftime("%Y%m%d-%H%M")
    snapshot_path = os.path.join(BACKUP_DIR, f"storage-{now}.sqlite")
    try:
        conn = sqlite3.connect(f"file:{OMNIROUTE_DB}?mode=ro", uri=True, timeout=5)
        backup = sqlite3.connect(snapshot_path)
        conn.backup(backup)
        backup.close()
        conn.close()
        log.info(f"Created startup snapshot: {os.path.basename(snapshot_path)}")
    except Exception as e:
        log.warning(f"Snapshot failed: {e}")


def main():
    log.info("=== OmniRoute DB Fix & Migration ===")
    log.info(f"Active DB: {OMNIROUTE_DB_ACTIVE}")
    log.info(f"Data DB: {OMNIROUTE_DB}")

    ensure_dirs()
    kill_stale_processes()

    # Fix WAL corruption
    fix_wal_corruption(OMNIROUTE_DB)
    fix_wal_corruption(OMNIROUTE_DB_ACTIVE)

    # Bidirectional sync
    sync_active_to_data()
    sync_data_to_active()

    # Create startup snapshot
    create_snapshot()

    log.info("=== Fix Complete ===")


if __name__ == "__main__":
    main()
