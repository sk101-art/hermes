import argparse
import sys
import time
from datetime import datetime, timezone

from app.services.intelligence import search_intelligence
from app.storage.db import Database


if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def main():
    parser = argparse.ArgumentParser(
        description="HERMES — Local Technology Intelligence Query CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m app.query "LLM inference optimization" --top 10
  python -m app.query "vLLM" --verified-only
  python -m app.query "CUDA compiler" --project cuda-compiler-lab --explain
  python -m app.query "vector database" --source arxiv --days 30
  python -m app.query "storage" --mode lexical
        """,
    )
    parser.add_argument("query", type=str, help="Search query or technology keyword")
    parser.add_argument("--top", "-n", type=int, default=10, help="Max results to return (1-50, default 10)")
    parser.add_argument("--project", "-p", type=str, default=None, help="Project name or ID for context relevance boost")
    parser.add_argument("--source", "-s", type=str, default=None, help="Filter by specific source (e.g. github, arxiv)")
    parser.add_argument("--days", "-d", type=int, default=None, help="Filter events published within N days")
    parser.add_argument("--verified-only", action="store_true", help="Only return supported/verified claims & stories")
    parser.add_argument("--mode", type=str, choices=["hybrid", "lexical", "semantic"], default="hybrid", help="Search mode")
    parser.add_argument("--explain", action="store_true", help="Print transparent score breakdown for each result")

    args = parser.parse_args()

    t0 = time.time()
    db = Database()

    results = search_intelligence(
        query=args.query,
        project=args.project,
        source=args.source,
        days=args.days,
        limit=args.top,
        verified_only=args.verified_only,
        mode=args.mode,
        explain=args.explain,
        db=db,
    )
    duration_ms = (time.time() - t0) * 1000.0

    print("=" * 70)
    print("HERMES — LOCAL TECHNOLOGY INTELLIGENCE SEARCH")
    print("=" * 70)
    print(f"Query:         \"{args.query}\"")
    print(f"Mode:          {args.mode.upper()}")
    print(f"Filters:       project={args.project or 'all'} | source={args.source or 'all'} | days={args.days or 'all'} | verified_only={args.verified_only}")
    print(f"Duration:      {duration_ms:.1f} ms | Found: {len(results)} results (capped at {args.top})")
    print("=" * 70)

    if not results:
        print("\n[!] No matching verified intelligence found for query.")
        print("    Try adjusting filters, using a broader query, or switching mode to 'lexical'.\n")
        return

    for idx, r in enumerate(results, 1):
        print(f"\n[{idx}] {r.title}")
        print(f"    Score:        {r.score:.4f}  |  Verification: {r.verification_score:.2f} ({r.maturity or 'unknown'}, risk: {r.risk or 'unknown'})")
        print(f"    Sources:      {', '.join(r.sources)}  |  Published: {r.published_at or 'unknown'}")
        if r.project_relevance > 0.0:
            print(f"    Project Rel:  {r.project_relevance:.2f} ({', '.join(r.reason_codes)})")
        if r.summary:
            clean_sum = r.summary.replace("\n", " ").strip()
            if len(clean_sum) > 160:
                clean_sum = clean_sum[:157] + "..."
            print(f"    Summary:      {clean_sum}")
        if r.urls:
            print(f"    URL:          {r.urls[0]}")
        if args.explain and r.explain:
            exp = r.explain
            print(f"    [Explain]     Lexical: {exp.get('lexical_score', 0):.4f} | Semantic: {exp.get('semantic_score', 0):.4f} | Verif: +{exp.get('verification_adjustment', 0):.4f} | Fresh: +{exp.get('freshness_adjustment', 0):.4f} | Proj: +{exp.get('project_boost', 0):.4f} -> Final: {exp.get('final_score', 0):.4f}")

    print("\n" + "=" * 70 + "\n")


if __name__ == "__main__":
    main()
