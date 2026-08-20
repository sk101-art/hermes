import sys
from app.inbox.lifecycle import add_saved_item_tag
from app.storage.db import Database

try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def run_saved_tag(saved_id: str, tag: str) -> None:
    db = Database()
    ok = add_saved_item_tag(saved_id, tag, db)
    if not ok:
        print(f"Error: Saved item '{saved_id}' not found.")
        sys.exit(1)

    saved = db.get_saved_item(saved_id)
    print("=" * 65)
    print("HERMES — SAVED ITEM TAG ADDED")
    print("=" * 65)
    print(f"Saved ID: {saved_id}")
    print(f"Tags:     {', '.join(saved.tags) if saved else tag}")
    print("=" * 65)


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python -m app.saved_tag <saved_item_id> <tag>")
        sys.exit(1)
    run_saved_tag(sys.argv[1], sys.argv[2])
