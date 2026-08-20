import sys
from collections import Counter
from datetime import datetime, timezone

from app.inbox.briefing import generate_morning_briefing
from app.inbox.generator import extract_repository_identity
from app.storage.db import Database

try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def run_briefing_audit(target_date: str = None) -> None:
    db = Database()
    if target_date is None:
        target_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    briefing = generate_morning_briefing(db=db, target_date=target_date, refresh=False)

    print("=" * 65)
    print(f"HERMES — MORNING BRIEFING AUDIT ({target_date})")
    print("=" * 65)

    briefing_items = []
    for sec, item_ids in briefing.sections.items():
        for iid in item_ids:
            it = db.get_inbox_item(iid)
            if it:
                briefing_items.append((sec, it))

    total = len(briefing_items)
    print(f"\nTotal Briefing Items: {total}")

    section_counts = Counter(sec for sec, _ in briefing_items)
    print(f"\nSECTION DISTRIBUTION:")
    for sec, count in section_counts.most_common():
        pct = (count / total * 100) if total > 0 else 0
        print(f"  - {sec:<25}: {count:>2} ({pct:>5.1f}%)")

    # Sources & Repos
    sources = Counter()
    repos = Counter()
    scores = []
    projects = Counter()

    for _, it in briefing_items:
        scores.append(it.inbox_score)
        events = db.get_cluster_events(it.story_cluster_id)
        for ev in events:
            sources[ev.source] += 1
        repo = extract_repository_identity(events)
        if repo:
            repos[repo] += 1
        for pid in it.matched_project_ids:
            projects[pid] += 1

    avg_score = (sum(scores) / len(scores)) if scores else 0.0
    min_score = min(scores) if scores else 0.0

    print(f"\nMETRICS & DIVERSITY:")
    print(f"  - Average Inbox Score:    {avg_score:>5.2f}")
    print(f"  - Lowest Included Score:  {min_score:>5.2f}")
    print(f"  - Unique Sources:         {len(sources):>5}")
    print(f"  - Unique Repositories:    {len(repos):>5}")
    print(f"  - Matched Projects:       {len(projects):>5}")

    print(f"\nSOURCE BREAKDOWN:")
    for src, count in sources.most_common():
        print(f"  - {src:<20}: {count:>3}")

    # Warnings
    warnings = []
    for sec, count in section_counts.items():
        if total > 0 and (count / total) > 0.60 and count > 3:
            warnings.append(f"Section '{sec}' represents {count/total*100:.1f}% of briefing (>60% threshold)")

    for src, count in sources.items():
        total_src_events = sum(sources.values())
        if total_src_events > 0 and (count / total_src_events) > 0.60 and total > 5:
            warnings.append(f"Source '{src}' represents {count/total_src_events*100:.1f}% of source events (>60% threshold)")

    for repo, count in repos.items():
        if count > 2:
            warnings.append(f"Repository '{repo}' appears {count} times in briefing")

    print(f"\nAUDIT WARNINGS ({len(warnings)}):")
    if warnings:
        for w in warnings:
            print(f"  [WARN] {w}")
    else:
        print("  None. Briefing is well-balanced and diverse.")

    print("=" * 65)


if __name__ == "__main__":
    run_briefing_audit()
