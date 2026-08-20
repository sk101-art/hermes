import argparse
import sys
from datetime import datetime, timezone
from app.inbox.briefing import generate_morning_briefing
from app.storage.db import Database

try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def run_morning_brief(refresh: bool = False, target_date: str = None) -> None:
    db = Database()
    briefing = generate_morning_briefing(db=db, target_date=target_date, refresh=refresh)
    if briefing.summary_text:
        print(briefing.summary_text)
    else:
        print("No briefing content generated.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="HERMES Morning Intelligence Briefing")
    parser.add_argument("--refresh", action="store_true", help="Force regenerate today's briefing")
    parser.add_argument("--date", type=str, default=None, help="Target briefing date (YYYY-MM-DD)")
    args = parser.parse_args()
    run_morning_brief(refresh=args.refresh, target_date=args.date)
