import sys
from datetime import datetime, timezone

from app.models.schemas import UserFeedback
from app.storage.db import Database

try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def run_dismiss(inbox_id: str) -> None:
    db = Database()
    item = db.get_inbox_item(inbox_id)
    if not item:
        print(f"Error: Inbox item '{inbox_id}' not found.")
        sys.exit(1)

    now = datetime.now(timezone.utc)
    item.state = "archived"
    db.save_inbox_item(item)

    fb_id = f"fb:dismiss:{item.id}:{int(now.timestamp())}"
    feedback = UserFeedback(
        id=fb_id,
        entity_type="inbox_item",
        entity_id=item.id,
        action="dismiss",
        value=item.title,
        created_at=now,
    )
    db.save_user_feedback(feedback)

    print("=" * 65)
    print("HERMES — ITEM DISMISSED")
    print("=" * 65)
    print(f"Inbox ID: {item.id}")
    print(f"Title:    \"{item.title}\"")
    print(f"State:    ARCHIVED")
    print("=" * 65)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m app.dismiss <inbox_id>")
        sys.exit(1)
    run_dismiss(sys.argv[1])
