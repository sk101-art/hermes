import sys
from app.inbox.lifecycle import star_inbox_item
from app.storage.db import Database

try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def run_star(inbox_item_id: str) -> None:
    db = Database()
    saved = star_inbox_item(inbox_item_id, db)
    if not saved:
        print(f"Error: Inbox item '{inbox_item_id}' not found.")
        sys.exit(1)

    print("=" * 65)
    print("HERMES — ITEM STARRED & SAVED TO LIBRARY")
    print("=" * 65)
    print(f"Title:         \"{saved.title_snapshot}\"")
    print(f"Saved ID:      {saved.id}")
    print(f"Saved At:      {saved.saved_at.strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print(f"Verification:  {saved.verification_snapshot:.2f}")
    print(f"Maturity:      {saved.maturity_snapshot.upper()}")
    print(f"Risk Snapshot: {saved.risk_snapshot:.2f}")
    if saved.project_ids:
        print(f"Projects:      {', '.join(saved.project_ids)}")
    print("=" * 65)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m app.star <inbox_item_id>")
        sys.exit(1)
    run_star(sys.argv[1])
