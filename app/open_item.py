import sys
from app.inbox.lifecycle import open_inbox_item
from app.storage.db import Database

try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def run_open_item(inbox_item_id: str) -> None:
    db = Database()
    item = open_inbox_item(inbox_item_id, db)
    if not item:
        print(f"Error: Inbox item '{inbox_item_id}' not found.")
        sys.exit(1)

    cluster = db.get_cluster(item.story_cluster_id)
    events = db.get_cluster_events(item.story_cluster_id)
    claims = db.get_claims_by_cluster(item.story_cluster_id)
    assessment = db.get_technology_assessment(item.story_cluster_id)

    print("=" * 70)
    print("HERMES — OPENED INBOX ITEM")
    print("=" * 70)
    print(f"Title:         \"{item.title}\"")
    print(f"Section:       {item.section.upper()}")
    print(f"Inbox Score:   {item.inbox_score:.2f} | Impact: {item.project_impact_score:.2f}")
    print(f"State:         {item.state.upper()} | Starred: {item.is_starred}")
    if item.opened_at:
        print(f"Opened At:     {item.opened_at.strftime('%Y-%m-%d %H:%M:%S UTC')}")

    if assessment:
        print(f"Maturity:      {assessment.maturity_stage.upper()} ({assessment.assessment_score:.2f})")

    if claims:
        print("\nVerified Claims:")
        for c in claims:
            print(f"  - [{c.status.upper()}] \"{c.claim_text}\" (Score: {c.verification_score:.2f})")

    if events:
        print("\nSources & Provenance:")
        for ev in events:
            print(f"  - [{ev.source.upper()}] {ev.title}")
            print(f"    {ev.url}")

    print("=" * 70)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m app.open_item <inbox_item_id>")
        sys.exit(1)
    run_open_item(sys.argv[1])
