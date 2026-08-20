import argparse
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone

from app.storage.db import Database

try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def run_audit(lookback_hours: int = 24):
    db = Database()
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=lookback_hours)

    print("=" * 70)
    print(f"HERMES — RUNTIME EXECUTION AUDIT (Last {lookback_hours} Hours)")
    print("=" * 70)

    runs = db.get_recent_runtime_job_runs(limit=200)
    filtered_runs = [r for r in runs if r.started_at >= cutoff]

    print(f"\nJOB EXECUTION SUMMARY:")
    print(f"  - Total Runs Evaluated:  {len(filtered_runs):>4}")

    status_counts = Counter(r.status for r in filtered_runs)
    for st, count in status_counts.most_common():
        print(f"  - {st.upper():<15}:        {count:>4}")

    # Job-by-job breakdown
    job_counts = Counter(r.job_name for r in filtered_runs)
    print(f"\nEXECUTIONS BY JOB:")
    for j, cnt in job_counts.most_common():
        fails = sum(1 for r in filtered_runs if r.job_name == j and r.status == "failed")
        items = sum(r.items_processed for r in filtered_runs if r.job_name == j)
        print(f"  - {j:<20}: {cnt:>3} runs (Failures: {fails}, Items: {items})")

    # Recent Execution Log
    print(f"\nRECENT JOB RUN LOGS (Top 20):")
    print("-" * 70)
    print(f"{'Job Name':<18} {'Started':<16} {'Duration':<10} {'Status':<12} {'Items'}")
    print("-" * 70)
    for r in filtered_runs[:20]:
        st_time = r.started_at.strftime("%m-%d %H:%M:%S")
        dur = f"{r.duration_seconds:.2f}s"
        print(f"{r.job_name:<18} {st_time:<16} {dur:<10} {r.status.upper():<12} {r.items_processed}")
        if r.error_summary:
            print(f"    [Error] {r.error_summary[:60]}")

    # Source diversity warning check
    events = [e for e in db.get_all_events() if e.discovered_at and e.discovered_at >= cutoff]
    if events:
        src_counts = Counter(e.source for e in events)
        total_evs = len(events)
        print(f"\nSOURCE INGESTION DIVERSITY (Last {lookback_hours}h):")
        for src, cnt in src_counts.most_common():
            pct = cnt / total_evs * 100
            print(f"  - {src:<20}: {cnt:>4} ({pct:>5.1f}%)")
            if pct > 60.0 and total_evs > 10:
                print(f"    [DIAGNOSTIC WARNING] Source diversity low: {pct:.1f}% {src.upper()}-derived.")

    print("=" * 70)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="HERMES Runtime Audit")
    parser.add_argument("--hours", type=int, default=24, help="Lookback window in hours")
    args = parser.parse_args()
    run_audit(lookback_hours=args.hours)
