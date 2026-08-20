import sys
from datetime import datetime, timezone
from app.inbox.lifecycle import cleanup_expired_inbox_items
from app.storage.db import Database

try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def run_inbox_cleanup() -> None:
    db = Database()
    now = datetime.now(timezone.utc)
    expired_cnt = cleanup_expired_inbox_items(db, now=now)

    print("=" * 65)
    print("HERMES — INBOX EXPIRY & CLEANUP")
    print("=" * 65)
    print(f"Timestamp:              {now.strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print(f"Expired Items Updated:  {expired_cnt:>4}")
    print(f"Saved Items Preserved:  All (untouched)")
    print(f"Underlying Intel:       All (preserved in StoryClusters & Claims)")
    print("=" * 65)


if __name__ == "__main__":
    run_inbox_cleanup()
