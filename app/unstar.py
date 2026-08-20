import sys
from app.inbox.lifecycle import unstar_inbox_item
from app.storage.db import Database

try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def run_unstar(inbox_item_id: str) -> None:
    db = Database()
    ok = unstar_inbox_item(inbox_item_id, db)
    if not ok:
        print(f"Error: Inbox item '{inbox_item_id}' not found.")
        sys.exit(1)

    print("=" * 65)
    print("HERMES — ITEM UNSTARRED")
    print("=" * 65)
    print(f"Inbox Item:   {inbox_item_id}")
    print("Status:       Item removed from active starred items.")
    print("Note:         Saved history and user notes preserved.")
    print("=" * 65)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m app.unstar <inbox_item_id>")
        sys.exit(1)
    run_unstar(sys.argv[1])
