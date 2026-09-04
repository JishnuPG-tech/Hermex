#!/usr/bin/env python3
"""
clean_db.py — Key-Hash Guard + DB Archive on Key Rotation.

On every boot:
1. Reads the current ENCRYPTION_KEY from environment.
2. Hashes it (SHA-256) and compares to stored .key_hash.
3. If the key changed:
   - Archives current DB to /data/omniroute/backups/storage-YYYYMMDD-HHMM.sqlite
   - Archives .key_hash to /data/omniroute/backups/.key_hash.prev
   - Writes new .key_hash
   - Logs the rotation event
4. If key is unchanged: no-op.

Also ensures /data/omniroute/backups/ directory exists.
"""
import hashlib
import os
import shutil
import sqlite3
import logging
from datetime import datetime

logging.basicConfig(
    level=logging.INFO,
    format="[clean_db %(asctime)s] %(levelname)s — %(message)s",
)
log = logging.getLogger("clean_db")

DATA_DIR = "/data/omniroute"
ACTIVE_DB = "/root/.omniroute/storage.sqlite"
BACKUP_DIR = os.path.join(DATA_DIR, "backups")
KEY_HASH_FILE = os.path.join(DATA_DIR, ".key_hash")


def ensure_dirs():
    """Create required directories."""
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(BACKUP_DIR, exist_ok=True)
    log.info(f"Ensured directories: {DATA_DIR}, {BACKUP_DIR}")


def hash_key(key: str) -> str:
    """SHA-256 hex digest of the encryption key."""
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def read_stored_hash() -> str | None:
    """Read the previously stored key hash, or None."""
    try:
        if os.path.exists(KEY_HASH_FILE):
            with open(KEY_HASH_FILE, "r") as f:
                return f.read().strip()
    except Exception as e:
        log.warning(f"Failed to read key hash: {e}")
    return None


def write_key_hash(key_hash: str):
    """Persist the new key hash."""
    with open(KEY_HASH_FILE, "w") as f:
        f.write(key_hash)
    log.info(f"Wrote key hash to {KEY_HASH_FILE}")


def archive_current_db():
    """Archive current DB to /data/omniroute/backups/ with timestamp."""
    if not os.path.exists(ACTIVE_DB) or os.path.getsize(ACTIVE_DB) == 0:
        log.info("No active DB to archive")
        return

    now = datetime.now().strftime("%Y%m%d-%H%M")
    archive_path = os.path.join(BACKUP_DIR, f"storage-{now}.sqlite")

    try:
        src = sqlite3.connect(f"file:{ACTIVE_DB}?mode=ro", uri=True, timeout=10)
        dst = sqlite3.connect(archive_path, timeout=10)
        src.backup(dst)
        dst.close()
        src.close()
        log.info(f"Archived DB → {archive_path}")
    except Exception as e:
        log.warning(f"DB archive failed (non-fatal): {e}")

    # Also archive .key_hash.prev
    prev_hash_file = os.path.join(BACKUP_DIR, ".key_hash.prev")
    if os.path.exists(KEY_HASH_FILE):
        try:
            shutil.copy2(KEY_HASH_FILE, prev_hash_file)
            log.info(f"Archived previous key hash → {prev_hash_file}")
        except Exception as e:
            log.warning(f"Hash archive failed (non-fatal): {e}")


def main():
    log.info("=== Key-Hash Guard ===")
    ensure_dirs()

    # Read key from environment
    key = os.getenv("ENCRYPTION_KEY", "")
    if not key:
        log.warning("ENCRYPTION_KEY not set; skipping key-hash guard")
        return

    current_hash = hash_key(key)
    stored_hash = read_stored_hash()

    if stored_hash is None:
        log.info("No stored key hash found — first boot. Writing initial hash.")
        write_key_hash(current_hash)
        return

    if current_hash == stored_hash:
        log.info("Key hash unchanged — no rotation detected.")
        return

    # Key rotation detected!
    log.info(f"KEY ROTATION DETECTED: stored={stored_hash[:16]}... current={current_hash[:16]}...")
    log.info("Archiving current DB before rotation...")
    archive_current_db()
    write_key_hash(current_hash)
    log.info("Key rotation complete.")


if __name__ == "__main__":
    main()
