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
    strong_semantic = sum(1 for m in all_matches if any("semantic_similarity" in r and float(r.split(":")[1]) >= 0.60 for r in m.reason_codes))

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
    print(f"  - Direct Dependency Matches:    {match_types.get('direct_dependency', 0):>5}")
    print(f"  - Strong Semantic Matches:      {strong_semantic:>5}")
    print(f"  - Technology Overlaps:          {match_types.get('technology_overlap', 0):>5}")
    print(f"  - Architecture Relevant:        {match_types.get('architecture_relevant', 0):>5}")
    print(f"  - Storage Relevant:             {match_types.get('storage_relevant', 0):>5}")
    print(f"  - Optimization Relevant:        {match_types.get('optimization_opportunity', 0):>5}")
    print(f"  - Weak / General Matches:       {match_types.get('general_related', 0):>5}")
    print(f"  - High-Impact Matches (>=0.70): {high_impact:>5}")

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

    # Sample top direct dependencies
    direct_matches = [m for m in all_matches if m.match_type == "direct_dependency"]
    direct_matches.sort(key=lambda m: (m.impact_score, m.relevance_score), reverse=True)

    print(f"\nTOP DIRECT DEPENDENCY MATCHES ({len(direct_matches)}):")
    print("-" * 70)
    for idx, m in enumerate(direct_matches[:20], 1):
        cl = db.get_cluster(m.entity_id)
        title = cl.canonical_title if cl else m.entity_id
        print(f"{idx:02d}. Project: {m.project_id} | Impact: {m.impact_score:.2f} | Rel: {m.relevance_score:.2f}")
        print(f"    Story: \"{title[:60]}\"")
        dep_codes = [r for r in m.reason_codes if r.startswith("dependency_match:")]
        if dep_codes:
            print(f"    Dependency Identity: {dep_codes[0]}")
        print()

    print("=" * 70)


if __name__ == "__main__":
    run_context_audit()
