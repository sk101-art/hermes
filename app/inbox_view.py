import argparse
import sys
from collections import defaultdict
from app.inbox.lifecycle import mark_inbox_items_seen
from app.storage.db import Database

try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def run_inbox_view(
    unseen_only: bool = False,
    starred_only: bool = False,
    project_filter: str = None,
    section_filter: str = None,
    include_expired: bool = False,
) -> None:
    db = Database()
    items = db.get_active_inbox_items(include_expired=include_expired, limit=100)

    # Filter logic
    if unseen_only:
        items = [it for it in items if it.state == "unseen"]
    if starred_only:
        items = [it for it in items if it.is_starred]
    if project_filter:
        p_clean = project_filter.lower().strip()
        items = [
            it
            for it in items
            if any(p_clean in pid.lower() for pid in it.matched_project_ids)
        ]
    if section_filter:
        s_clean = section_filter.lower().strip()
        items = [it for it in items if s_clean in it.section.lower()]

    all_active = db.get_active_inbox_items(include_expired=False)
    unseen_cnt = sum(1 for it in all_active if it.state == "unseen")
    seen_cnt = sum(1 for it in all_active if it.state in ("seen", "opened"))
    starred_cnt = sum(1 for it in all_active if it.is_starred)

    print("=" * 70)
    print("HERMES — TODAY'S INTELLIGENCE INBOX")
    print(f"UNSEEN: {unseen_cnt} | SEEN/OPENED: {seen_cnt} | STARRED: {starred_cnt}")
    print("=" * 70)

    if not items:
        print("\nInbox is empty. Run 'python -m app.inbox_generate' to populate today's inbox.")
        print("=" * 70)
        return

    # Group by section
    grouped = defaultdict(list)
    for it in items:
        grouped[it.section].append(it)

    displayed_unseen_ids = []

    section_order = [
        "must_know",
        "project_relevant",
        "ai_ml",
        "systems_compilers",
        "storage_databases",
        "developer_tooling",
        "research",
        "corrections_updates",
        "watchlist",
    ]

    for sec in section_order:
        sec_items = grouped.get(sec, [])
        if not sec_items:
            continue

        sec_title = sec.replace("_", " ").upper()
        print(f"\n--- {sec_title} ({len(sec_items)}) ---")

        for idx, it in enumerate(sec_items, 1):
            if it.state == "unseen":
                displayed_unseen_ids.append(it.id)

            cluster = db.get_cluster(it.story_cluster_id)
            claims = db.get_claims_by_cluster(it.story_cluster_id)
            assessment = db.get_technology_assessment(it.story_cluster_id)
            mat_str = assessment.maturity_stage.upper() if assessment and assessment.maturity_stage else "NOT ASSESSED"

            star_icon = "[STARRED]" if it.is_starred else f"[{it.state.upper()}]"
            print(f"\n{idx:02d} [{it.inbox_score:.2f}] {star_icon} \"{it.title}\"")
            print(f"    Maturity:     {mat_str} | Impact Score: {it.project_impact_score:.2f}")

            if it.matched_project_ids:
                print(f"    Relevant to:  {', '.join(it.matched_project_ids)}")

            if claims:
                strongest = claims[0]
                print(f"    Verification: {strongest.status.upper()} (Score: {strongest.verification_score:.2f})")

            if it.reason_codes:
                print(f"    Why:          {', '.join(it.reason_codes[:4])}")

            print(f"    ID:           {it.id}")

    print("\n" + "=" * 70)

    # Mark displayed items as seen
    if displayed_unseen_ids:
        mark_inbox_items_seen(displayed_unseen_ids, db)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="HERMES Intelligence Inbox")
    parser.add_argument("--unseen", action="store_true", help="Filter unseen items only")
    parser.add_argument("--starred", action="store_true", help="Filter starred items only")
    parser.add_argument("--project", type=str, default=None, help="Filter by relevant project name")
    parser.add_argument("--section", type=str, default=None, help="Filter by section name")
    parser.add_argument("--all", action="store_true", help="Include expired items")
    args = parser.parse_args()

    run_inbox_view(
        unseen_only=args.unseen,
        starred_only=args.starred,
        project_filter=args.project,
        section_filter=args.section,
        include_expired=args.all,
    )
