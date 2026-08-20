import argparse
import sys
import time
from datetime import datetime, timezone

from app.inbox.generator import generate_daily_inbox
from app.storage.db import Database

try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def run_inbox_generate(lookback: int = 36, ttl: int = 24) -> None:
    start_time = time.time()
    db = Database()

    print("=" * 65)
    print("HERMES — DAILY INBOX GENERATOR")
    print("=" * 65)

    items = generate_daily_inbox(db=db, lookback_hours=lookback, ttl_hours=ttl)

    duration = time.time() - start_time
    unseen_count = sum(1 for it in items if it.state == "unseen")
    starred_count = sum(1 for it in items if it.state == "starred")
    must_know_count = sum(1 for it in items if it.section == "must_know")
    project_rel_count = sum(1 for it in items if it.section == "project_relevant")

    print(f"\nGenerated {len(items)} inbox items for Today:")
    print(f"  - Must Know:             {must_know_count:>4}")
    print(f"  - Project Relevant:      {project_rel_count:>4}")
    print(f"  - Unseen:                {unseen_count:>4}")
    print(f"  - Starred:               {starred_count:>4}")
    print(f"  - Generation Duration: {duration:>6.2f}s")
    print("=" * 65)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="HERMES Daily Inbox Generator")
    parser.add_argument("--lookback", type=int, default=36, help="Lookback window in hours")
    parser.add_argument("--ttl", type=int, default=24, help="Inbox item TTL in hours")
    args = parser.parse_args()
    run_inbox_generate(lookback=args.lookback, ttl=args.ttl)
