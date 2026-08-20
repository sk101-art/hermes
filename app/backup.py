import argparse
import os
import sqlite3
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional, Tuple

try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def prune_old_backups(backup_dir: str = "data/backups", retention_days: int = 7) -> List[str]:
    """Deletes backup files older than retention_days, keeping at least the most recent backup."""
    p_dir = Path(backup_dir)
    if not p_dir.exists():
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    backup_files = sorted(
        [f for f in p_dir.glob("hermes_*.db") if f.is_file()],
        key=lambda f: f.stat().st_mtime,
    )

    if len(backup_files) <= 1:
        return []

    pruned = []
    # Keep at least the latest backup even if old
    for f in backup_files[:-1]:
        mtime = datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc)
        if mtime < cutoff:
            try:
                f.unlink()
                pruned.append(str(f))
            except Exception:
                pass
    return pruned


def verify_backup(backup_path: str) -> Tuple[bool, str]:
    """Verifies that the backup database can be opened and passes integrity checks."""
    try:
        conn = sqlite3.connect(backup_path)
        cursor = conn.cursor()
        cursor.execute("PRAGMA quick_check")
        row = cursor.fetchone()
        if not row or row[0] != "ok":
            conn.close()
            return False, f"Integrity check failed: {row}"

        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [r[0] for r in cursor.fetchall()]
        conn.close()

        if "events" not in tables or "story_clusters" not in tables:
            return False, "Missing core tables in backup database"

        return True, "Backup verified ok"
    except Exception as e:
        return False, f"Verification error: {e}"


def create_database_backup(
    db_path: str = "data/tech_intel.db",
    backup_dir: str = "data/backups",
    retention_days: int = 7,
    now: Optional[datetime] = None,
) -> Tuple[bool, Optional[str], str]:
    """
    Creates a consistent SQLite online backup, verifies it, and prunes old backups.
    Returns: (success, backup_filepath, message)
    """
    if now is None:
        now = datetime.now(timezone.utc)

    src_path = Path(db_path)
    if not src_path.exists():
        return False, None, f"Source database '{db_path}' does not exist"

    b_dir = Path(backup_dir)
    b_dir.mkdir(parents=True, exist_ok=True)

    timestamp_str = now.strftime("%Y%m%d_%H%M%S")
    dest_path = b_dir / f"hermes_{timestamp_str}.db"

    try:
        src_conn = sqlite3.connect(str(src_path))
        dest_conn = sqlite3.connect(str(dest_path))

        with dest_conn:
            src_conn.backup(dest_conn, pages=100, sleep=0.01)

        src_conn.close()
        dest_conn.close()

        # Verify backup
        is_ok, v_msg = verify_backup(str(dest_path))
        if not is_ok:
            dest_path.unlink(missing_ok=True)
            return False, None, f"Backup verification failed: {v_msg}"

        # Prune old backups
        pruned = prune_old_backups(backup_dir, retention_days)

        return True, str(dest_path), f"Backup created successfully ({dest_path.name})"
    except Exception as e:
        if dest_path.exists():
            dest_path.unlink(missing_ok=True)
        return False, None, f"Backup creation failed: {e}"


def run_backup_cli():
    parser = argparse.ArgumentParser(description="HERMES SQLite Database Backup Utility")
    parser.add_argument("--db", type=str, default="data/tech_intel.db", help="Path to SQLite DB")
    parser.add_argument("--dir", type=str, default="data/backups", help="Path to backups directory")
    parser.add_argument("--retention", type=int, default=7, help="Backup retention in days")
    args = parser.parse_args()

    print("=" * 65)
    print("HERMES — DATABASE BACKUP")
    print("=" * 65)

    success, path, msg = create_database_backup(
        db_path=args.db,
        backup_dir=args.dir,
        retention_days=args.retention,
    )

    if success:
        print(f"Status:   SUCCESS")
        print(f"File:     {path}")
        print(f"Message:  {msg}")
    else:
        print(f"Status:   FAILED")
        print(f"Error:    {msg}")
        sys.exit(1)
    print("=" * 65)


if __name__ == "__main__":
    run_backup_cli()
