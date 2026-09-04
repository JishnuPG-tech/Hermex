import time
import shutil
import sqlite3
from pathlib import Path

DATA_DIR = Path("/data")
HERMES_DIR = Path("/data/hermes")
VAULT_DIR = Path("/data/obsidian/vault")
BACKUP_DIR = Path("/data/backups")

HERMES_DIR.mkdir(parents=True, exist_ok=True)
VAULT_DIR.mkdir(parents=True, exist_ok=True)
BACKUP_DIR.mkdir(parents=True, exist_ok=True)

def checkpoint_sqlite():
    db_file = HERMES_DIR / "memory.sqlite"
    if db_file.exists():
        try:
            conn = sqlite3.connect(db_file)
            conn.execute("PRAGMA wal_checkpoint(PASSIVE);")
            cur = conn.cursor()
            cur.execute("PRAGMA quick_check;")
            res = cur.fetchone()
            conn.close()
            
            # Periodic backup
            backup_dest = BACKUP_DIR / "memory_latest.sqlite"
            shutil.copy2(db_file, backup_dest)
        except Exception as e:
            print(f"[HEALTH_DOCTOR] Checkpoint notice: {e}")

def main():
    print("[HEALTH_DOCTOR] Supervisor daemon started (interval: 30s).")
    while True:
        try:
            checkpoint_sqlite()
        except Exception as e:
            print(f"[HEALTH_DOCTOR] Error: {e}")
        time.sleep(30)

if __name__ == "__main__":
    main()
