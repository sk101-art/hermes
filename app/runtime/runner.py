import argparse
import logging
import os
import signal
import sys
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.runtime.locks import SingleInstanceLock
from app.runtime.logging_config import setup_runtime_logging
from app.runtime.scheduler import execute_job, is_job_due, run_all_due_jobs
from app.runtime.state import (
    is_source_due,
    load_runtime_config,
    recover_interrupted_jobs,
    write_heartbeat,
)
from app.storage.db import Database
from app.runtime.jobs import (
    run_daily_refresh,
    run_inbox_generation,
    generate_scheduled_morning_briefing,
    run_health_check_job,
    run_longitudinal_recheck,
    run_context_scan,
    run_context_match,
    run_source_ingestion,
    run_semantic_processing,
    run_claims_processing,
)


try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

_stop_requested = False


def _signal_handler(signum, frame):
    global _stop_requested
    _stop_requested = True
    print(f"\n[HERMES] Received shutdown signal ({signum}). Finishing current task and exiting gracefully...", flush=True)


def run_daemon(
    db: Database,
    once: bool = False,
    job_name: Optional[str] = None,
    dry_run: bool = False,
    poll_interval_seconds: int = 30,
) -> None:
    """Runs the HERMES background runtime service or one-off tasks."""
    global _stop_requested
    config = load_runtime_config()
    logger = setup_runtime_logging(
        log_file=config.get("log_file", "logs/hermes.log"),
        log_level=config.get("log_level", "INFO"),
        console=True,
    )

    print("=" * 65)
    print("HERMES — AUTONOMOUS BACKGROUND RUNTIME")
    if dry_run:
        print("MODE: DRY RUN (Inspection only, No mutations)")
    elif once:
        print("MODE: RUN ONCE")
    elif job_name:
        print(f"MODE: RUN JOB ({job_name})")
    else:
        print("MODE: CONTINUOUS DAEMON (Press Ctrl+C to stop)")
    print("=" * 65)

    # 1. Handle Dry Run
    if dry_run:
        now = datetime.now(timezone.utc)
        print(f"\nDRY RUN EVALUATION ({now.strftime('%Y-%m-%d %H:%M:%S UTC')}):")
        print("-" * 65)

        print("\nJOB SCHEDULE STATUS:")
        from app.runtime.scheduler import JOB_DEPENDENCIES_ORDER
        for j in JOB_DEPENDENCIES_ORDER:
            due, reason = is_job_due(j, db, now, config)
            status_str = "DUE NOW" if due else "NOT DUE"
            print(f"  - {j:<20}: [{status_str:<7}] ({reason})")

        print("\nSOURCE DUE STATUS:")
        for s in config.get("sources", {}).keys():
            due, reason = is_source_due(s, db, now, config)
            status_str = "DUE NOW" if due else "NOT DUE"
            print(f"  - {s:<20}: [{status_str:<7}] ({reason})")

        print("\n" + "=" * 65)
        return

    # 2. Acquire Single Instance Lock
    lock_path = os.getenv("HERMES_LOCK_PATH", config.get("lock_file", "data/hermes.lock"))
    lock = SingleInstanceLock(lock_path=lock_path)
    if not lock.acquire():
        info = lock.get_lock_info() or {}
        print(f"[Error] Another HERMES instance is already running (PID: {info.get('pid', 'unknown')}). Exiting.")
        sys.exit(1)

    # Register signals
    signal.signal(signal.SIGINT, _signal_handler)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _signal_handler)

    try:
        # 3. Startup Recovery
        logger.info("Initializing runtime and checking for interrupted jobs...")
        recovered = recover_interrupted_jobs(db)
        if recovered:
            logger.warning(f"Recovered {len(recovered)} interrupted job runs from previous abnormal shutdown.")

        write_heartbeat(status="running")

        # 4. Handle Specific Single Job
        if job_name:
            res = execute_job(job_name, db, now=datetime.now(timezone.utc), config=config)
            print(f"\nJob Execution Result ({job_name}):")
            print(f"  Status:   {res.get('status')}")
            print(f"  Duration: {res.get('duration_seconds', 0):.2f}s")
            if res.get("error"):
                print(f"  Error:    {res['error']}")
            return

        # 5. Handle Run Once
        if once:
            start_time = time.time()
            now = datetime.now(timezone.utc)
            results = run_all_due_jobs(db, now=now, config=config)
            duration = time.time() - start_time

            executed = [r for r in results if r.get("status") == "completed"]
            skipped = [r for r in results if r.get("status") == "skipped"]
            failed = [r for r in results if r.get("status") == "failed"]

            print(f"\nRun Once Completed in {duration:.2f}s:")
            print(f"  - Jobs Executed: {len(executed):>3}")
            print(f"  - Jobs Skipped:  {len(skipped):>3}")
            print(f"  - Jobs Failed:   {len(failed):>3}")

            if executed:
                print("\nEXECUTED JOBS:")
                for r in executed:
                    print(f"  - {r['job_name']:<20}: {r.get('duration_seconds', 0):.2f}s ({r.get('reason', '')})")
            if failed:
                print("\nFAILED JOBS:")
                for r in failed:
                    print(f"  [ERROR] {r['job_name']}: {r.get('error')}")
            return

        # 6. Continuous Daemon Loop
        # A. Startup briefing catch-up check
        try:
            from app.runtime.timezone import runtime_date_string
            now_utc = datetime.now(timezone.utc)
            today_str = runtime_date_string(now_utc, config)
            logger.info(f"Checking startup catch-up for morning briefing on {today_str}...")
            existing_briefing = db.get_daily_briefing(today_str)
            if not existing_briefing:
                logger.info(f"Morning Briefing for {today_str} is missing. Running daily refresh catch-up...")
                run_daily_refresh(db, now=now_utc, surface_date=today_str)
                logger.info("Startup briefing catch-up completed successfully.")
            else:
                logger.info(f"Morning Briefing for {today_str} already exists. Startup catch-up skipped.")
        except Exception as e:
            logger.error(f"Startup briefing catch-up check failed: {e}")

        logger.info("HERMES daemon started successfully. Entering scheduler loop.")
        while not _stop_requested:
            now = datetime.now(timezone.utc)
            run_all_due_jobs(db, now=now, config=config)
            
            # B. Poll and execute queued background operations
            try:
                db.recover_stale_refresh_operations(now)
                op = db.get_next_queued_operation()
                if op:
                    from datetime import timedelta
                    worker_id = f"worker-{os.getpid()}"
                    lease_expires = now + timedelta(minutes=5)
                    if db.claim_refresh_operation(op.id, worker_id, now, lease_expires):
                        logger.info(f"Claimed queued refresh operation: {op.id} [scope={op.scope}]")
                        try:
                            if op.scope == "daily_refresh":
                                run_daily_refresh(db, now=now)
                            elif op.scope == "inbox_refresh":
                                run_inbox_generation(db, now=now)
                            elif op.scope == "morning_brief":
                                generate_scheduled_morning_briefing(db, now=now)
                            elif op.scope == "health_check":
                                run_health_check_job(db, now=now)
                            elif op.scope == "recheck":
                                run_longitudinal_recheck(db, now=now)
                            elif op.scope == "project_scan":
                                run_context_scan(db, now=now)
                                run_context_match(db, now=now)
                            elif op.scope == "search_refresh":
                                run_source_ingestion(db, now=now)
                                run_semantic_processing(db, now=now)
                                run_claims_processing(db, now=now)
                            elif op.scope == "story_recheck":
                                run_longitudinal_recheck(db, now=now)
                            else:
                                logger.warning(f"Unknown operation scope: {op.scope}")

                            db.conn.execute(
                                "UPDATE refresh_operations SET status = 'completed', completed_at = ?, lease_expires_at = NULL WHERE id = ?",
                                (datetime.now(timezone.utc).isoformat(), op.id)
                            )
                            db.conn.commit()
                            logger.info(f"Completed refresh operation: {op.id}")
                        except Exception as e:
                            logger.exception(f"Failed refresh operation {op.id}: {e}")
                            db.conn.execute(
                                "UPDATE refresh_operations SET status = 'failed', error_summary = ?, completed_at = ?, lease_expires_at = NULL WHERE id = ?",
                                (str(e), datetime.now(timezone.utc).isoformat(), op.id)
                            )
                            db.conn.commit()
            except Exception as ex:
                logger.error(f"Error checking refresh operations: {ex}")

            write_heartbeat(status="running")

            # Sleep in short increments to respond quickly to shutdown signals
            for _ in range(poll_interval_seconds):
                if _stop_requested:
                    break
                time.sleep(1)

    finally:
        logger.info("Shutting down HERMES daemon...")
        write_heartbeat(status="stopped")
        lock.release()
        logger.info("HERMES daemon stopped cleanly.")
        print("[HERMES] Shutdown complete.")


def main(argv: Optional[List[str]] = None):
    parser = argparse.ArgumentParser(description="HERMES Autonomous Runtime Runner")
    parser.add_argument("--once", action="store_true", help="Run all currently due jobs once and exit")
    parser.add_argument("--job", type=str, default=None, help="Run a specific named job once")
    parser.add_argument("--dry-run", action="store_true", help="Preview due jobs and sources without mutating state")
    args = parser.parse_args(argv)
    import os
    db = Database(db_path=os.getenv("HERMES_DB_PATH", "data/tech_intel.db"))
    run_daemon(
        db=db,
        once=args.once,
        job_name=args.job,
        dry_run=args.dry_run,
    )
    return 0


if __name__ == "__main__":
    main()
