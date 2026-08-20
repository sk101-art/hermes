import argparse
import sys
import time
from app.context.matcher import match_all_projects_against_intelligence
from app.storage.db import Database

try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def run_context_match(max_candidates: int = 100, recency_days: int = 90) -> None:
    start_time = time.time()
    db = Database()

    print("=" * 70)
    print("HERMES — PROJECT CONTEXT & INTELLIGENCE MATCHER")
    print("=" * 70)

    projects = db.get_all_projects(active_only=True)
    if not projects:
        print("\nNo active projects indexed. Run 'python -m app.context_scan' first.")
        print("=" * 70)
        return

    print(f"Matching {len(projects)} active projects against top {max_candidates} StoryClusters...\n")

    results = match_all_projects_against_intelligence(
        db=db,
        max_candidates=max_candidates,
        recency_days=recency_days,
    )

    total_matches = sum(len(m_list) for m_list in results.values())
    direct_dep_matches = sum(1 for m_list in results.values() for m in m_list if m.match_type == "direct_dependency")
    high_impact_matches = sum(1 for m_list in results.values() for m in m_list if m.impact_score >= 0.70)
    risk_matches = sum(1 for m_list in results.values() for m in m_list if m.recommendation == "potential_risk")

    for proj_id, matches in results.items():
        proj = db.get_project(proj_id)
        proj_name = proj.name if proj else proj_id
        print(f"Project '{proj_name}' — {len(matches)} Relevant Developments Found:")

        for idx, m in enumerate(matches[:5], 1):
            cluster = db.get_cluster(m.entity_id)
            title = cluster.canonical_title if cluster else m.entity_id
            print(f"  [{idx:02d}] [{m.recommendation.upper()}] Impact: {m.impact_score:.2f} | Relevance: {m.relevance_score:.2f}")
            print(f"       Story: \"{title[:65]}...\"")
            print(f"       Type:  {m.match_type}")
            print(f"       Why:   {', '.join(m.reason_codes[:4])}")
        print("-" * 70)

    duration = time.time() - start_time
    print("\n" + "=" * 70)
    print("MATCHING SUMMARY")
    print("=" * 70)
    print(f"  Projects Matched:            {len(results):>5}")
    print(f"  Total Matches Created:       {total_matches:>5}")
    print(f"  Direct Dependency Matches:   {direct_dep_matches:>5}")
    print(f"  High-Impact Matches (>=0.70):{high_impact_matches:>5}")
    print(f"  Potential-Risk Matches:      {risk_matches:>5}")
    print(f"  Duration:                  {duration:>5.2f}s")
    print("=" * 70)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="HERMES Context Matcher")
    parser.add_argument("--candidates", type=int, default=100, help="Maximum candidates to evaluate")
    parser.add_argument("--days", type=int, default=90, help="Recency cutoff in days")
    args = parser.parse_args()
    run_context_match(max_candidates=args.candidates, recency_days=args.days)
