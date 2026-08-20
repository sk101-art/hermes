import sys
from datetime import datetime, timezone

from app.models.schemas import UserFeedback
from app.storage.db import Database

try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def run_feedback(inbox_id: str, action: str) -> None:
    db = Database()
    item = db.get_inbox_item(inbox_id)
    if not item:
        print(f"Error: Inbox item '{inbox_id}' not found.")
        sys.exit(1)

    if action not in ("useful", "not_useful"):
        print(f"Error: Feedback action must be 'useful' or 'not_useful'. Got: '{action}'")
        sys.exit(1)

    now = datetime.now(timezone.utc)
    fb_id = f"fb:{action}:{item.id}:{int(now.timestamp())}"
    feedback = UserFeedback(
        id=fb_id,
        entity_type="inbox_item",
        entity_id=item.id,
        action=action,
        value=item.title,
        created_at=now,
    )
    db.save_user_feedback(feedback)

    print("=" * 65)
    print(f"HERMES — USER FEEDBACK RECORDED ({action.upper()})")
    print("=" * 65)
    print(f"Inbox ID: {item.id}")
    print(f"Title:    \"{item.title}\"")
    print(f"Action:   {action}")
    print("=" * 65)


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python -m app.feedback <inbox_id> useful|not_useful")
        sys.exit(1)
    run_feedback(sys.argv[1], sys.argv[2].lower())
