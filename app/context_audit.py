import sys
from collections import Counter
from app.storage.db import Database

try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def run_context_audit() -> None:
    db = Database()
    projects = db.get_all_projects(active_only=True)
    all_matches = db.get_all_project_matches()

    total_files = 0
    all_deps = set()
    for p in projects:
        files = db.get_project_files(p.id)
        total_files += len(files)
        profile = db.get_project_profile(p.id)
        if profile:
            all_deps.update(profile.dependencies.keys())

    cursor = db.conn.cursor()
    cursor.execute("SELECT COUNT(*) as count FROM project_embeddings")
    emb_count = cursor.fetchone()["count"]

    match_types = Counter(m.match_type for m in all_matches)
    recommendations = Counter(m.recommendation for m in all_matches)
    high_impact = sum(1 for m in all_matches if m.impact_score >= 0.70)

    print("=" * 70)
    print("HERMES — PROJECT CONTEXT & MATCHING AUDIT")
    print("=" * 70)

    print(f"\nCONTEXT INVENTORY:")
    print(f"  - Active Projects:              {len(projects):>5}")
    print(f"  - Files Indexed:                {total_files:>5}")
    print(f"  - Unique Dependencies Detected: {len(all_deps):>5}")
    print(f"  - Project Embeddings Stored:    {emb_count:>5}")

    print(f"\nMATCHING METRICS:")
    print(f"  - Total Matches Created:        {len(all_matches):>5}")
    print(f"  - High-Impact Matches (>=0.70): {high_impact:>5}")

    print(f"\nMATCHES BY TYPE:")
    for mtype in (
        "direct_dependency",
        "optimization_opportunity",
        "compatible_tool",
        "architecture_relevant",
        "storage_relevant",
        "risk_relevant",
        "general_related",
    ):
        cnt = match_types.get(mtype, 0)
        pct = (cnt / len(all_matches) * 100) if all_matches else 0.0
        print(f"  - {mtype:<28} {cnt:>4} ({pct:>5.1f}%)")

    print(f"\nRECOMMENDATIONS BREAKDOWN:")
    for rec in (
        "upgrade_candidate",
        "evaluate",
        "consider",
        "optimization_candidate",
        "watch",
        "potential_risk",
        "not_recommended_yet",
    ):
        cnt = recommendations.get(rec, 0)
        pct = (cnt / len(all_matches) * 100) if all_matches else 0.0
        print(f"  - {rec:<28} {cnt:>4} ({pct:>5.1f}%)")

    print("=" * 70)


if __name__ == "__main__":
    run_context_audit()
