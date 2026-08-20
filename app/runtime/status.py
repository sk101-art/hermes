import sys
from datetime import datetime, timezone
from pathlib import Path

from app.runtime.locks import SingleInstanceLock
from app.runtime.scheduler import JOB_DEPENDENCIES_ORDER, is_job_due
from app.runtime.state import is_heartbeat_alive, is_source_due, load_runtime_config
from app.storage.db import Database

try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def run_status():
    db = Database()
    config = load_runtime_config()
    now = datetime.now(timezone.utc)

    hb_alive, hb_data = is_heartbeat_alive()
    lock_info = SingleInstanceLock().get_lock_info()

    print("=" * 70)
    print("HERMES — RUNTIME & DAEMON STATUS")
    print("=" * 70)

    # 1. Daemon Process State
    if hb_alive and hb_data:
        print(f"Daemon Status:      RUNNING (PID: {hb_data.get('pid')}, Host: {hb_data.get('hostname')})")
        print(f"Last Heartbeat:     {hb_data.get('timestamp')}")
    elif lock_info and not hb_alive:
        print(f"Daemon Status:      STALE / ABNORMAL (Lock PID: {lock_info.get('pid')}, Heartbeat unresponsive)")
    else:
        print(f"Daemon Status:      STOPPED (Not running)")

    # 2. Key Milestones
    today_str = now.strftime("%Y-%m-%d")
    briefing = db.get_daily_briefing(today_str)
    if briefing:
        print(f"Today's Briefing:   GENERATED ({briefing.total_items} items, {briefing.generated_at.strftime('%H:%M:%S UTC')})")
    else:
        print(f"Today's Briefing:   NOT YET GENERATED")

    ingest_job = db.get_runtime_job("ingestion")
    if ingest_job and ingest_job.last_completed_at:
        print(f"Last Ingestion:     {ingest_job.last_completed_at.strftime('%Y-%m-%d %H:%M:%S UTC')}")
    else:
        print(f"Last Ingestion:     Never")

    # 3. Source Health Table
    print(f"\nSOURCE HEALTH & CHECKPOINTS:")
    print("-" * 70)
    print(f"{'Source':<20} {'Health':<12} {'Failures':<10} {'Last Success':<20}")
    print("-" * 70)

    all_sources = config.get("sources", {}).keys()
    for src in all_sources:
        cp = db.get_source_checkpoint(src)
        due, reason = is_source_due(src, db, now, config)
        if cp:
            succ_str = cp.last_success_at.strftime("%m-%d %H:%M") if cp.last_success_at else "Never"
            print(f"{src:<20} {cp.health_status.upper():<12} {cp.consecutive_failures:<10} {succ_str:<20}")
        else:
            print(f"{src:<20} {'UNKNOWN':<12} {0:<10} {'Never':<20}")

    # 4. Job State Table
    print(f"\nSCHEDULED RUNTIME JOBS:")
    print("-" * 70)
    print(f"{'Job Name':<18} {'Status':<12} {'Runs':<6} {'Fails':<6} {'Last Run':<15} {'Next Due'}")
    print("-" * 70)

    for j in JOB_DEPENDENCIES_ORDER:
        j_state = db.get_runtime_job(j)
        due, reason = is_job_due(j, db, now, config)
        if j_state:
            last_run = j_state.last_completed_at.strftime("%m-%d %H:%M") if j_state.last_completed_at else "Never"
            status_disp = j_state.last_status.upper()
            print(f"{j:<18} {status_disp:<12} {j_state.run_count:<6} {j_state.failure_count:<6} {last_run:<15} {reason}")
        else:
            print(f"{j:<18} {'PENDING':<12} {0:<6} {0:<6} {'Never':<15} {reason}")

    # 5. Metrics Counters
    metrics = db.get_runtime_metrics()
    if metrics:
        print(f"\nLIFETIME RUNTIME METRICS:")
        for k, v in sorted(metrics.items()):
            print(f"  - {k:<25}: {v:>6}")

    print("=" * 70)


if __name__ == "__main__":
    run_status()
