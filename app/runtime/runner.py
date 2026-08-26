import argparse
import logging
import os
import signal
import sqlite3
import sys
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterator, List, Optional

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
    run_saved_hydration,
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


@contextmanager
def _operation_lease(
    db_path: str,
    op_id: str,
    worker_id: str,
    lease_minutes: int = 5,
    renew_seconds: int = 60,
) -> Iterator[None]:
    """Renews a running operation's lease/heartbeat while it executes.

    Long-running operations would otherwise exceed their lease and be
    reclaimed as abandoned by ``recover_stale_refresh_operations``. Renewals
    run on a daemon thread with a dedicated SQLite connection so they do not
    contend with the worker's connection.
    """
    stop = threading.Event()

    def _renew() -> None:
        try:
            conn = sqlite3.connect(db_path, timeout=10.0)
        except Exception:
            return
        try:
            while not stop.wait(renew_seconds):
                now = datetime.now(timezone.utc)
                lease_expires_at = now + timedelta(minutes=lease_minutes)
                try:
                    conn.execute(
                        """
                        UPDATE refresh_operations
                        SET heartbeat_at = ?, lease_expires_at = ?
                        WHERE id = ? AND status = 'running' AND worker_id = ?
                        """,
                        (now.isoformat(), lease_expires_at.isoformat(), op_id, worker_id),
                    )
                    conn.commit()
                except Exception:
                    pass
        finally:
            try:
                conn.close()
            except Exception:
                pass

    thread = threading.Thread(target=_renew, daemon=True, name=f"op-heartbeat-{op_id}")
    thread.start()
    try:
        yield
    finally:
        stop.set()


def _execute_operation_scope(db: Database, op, now: datetime) -> None:
    """Executes the work for a claimed operation scope. Raises on failure."""
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
    elif op.scope == "saved_hydration":
        run_saved_hydration(db, now=now)
    elif op.scope == "project_scan":
        # Targeted operation: scan ONLY the project named by op.target_id,
        # never all projects.
        if not op.target_id:
            raise ValueError("project_scan operation is missing target_id")
        from app.services.projects import scan_single_project
        scan_res = scan_single_project(project_id=op.target_id, db=db)
        if scan_res.get("status") == "failed":
            raise ValueError(f"project_scan failed for {op.target_id}: {scan_res.get('error')}")
    elif op.scope == "search_refresh":
        run_source_ingestion(db, now=now)
        run_semantic_processing(db, now=now)
        run_claims_processing(db, now=now)
    elif op.scope == "story_recheck":
        run_longitudinal_recheck(db, now=now)
    else:
        # Unknown scope is a terminal failure, never a silent success.
        raise ValueError(f"Unknown operation scope: {op.scope}")


def process_next_queued_operation(
    db: Database,
    worker_id: Optional[str] = None,
    now: Optional[datetime] = None,
    lease_minutes: int = 5,
) -> Optional[Dict[str, Any]]:
    """Claims and executes the next queued refresh operation, if any.

    This is the single canonical worker dispatch used by the daemon loop and
    directly testable in isolation. Returns a result dict describing the
    processed operation, or None when no queued operation existed.
    """
    if now is None:
        now = datetime.now(timezone.utc)
    if worker_id is None:
        worker_id = f"worker-{os.getpid()}"

    db.recover_stale_refresh_operations(now)
    op = db.get_next_queued_operation()
    if op is None:
        return None

    lease_expires = now + timedelta(minutes=lease_minutes)
    if not db.claim_refresh_operation(op.id, worker_id, now, lease_expires):
        # Another worker claimed it first.
        return {"operation_id": op.id, "status": "skipped", "reason": "claim_lost"}

    with _operation_lease(db.db_path, op.id, worker_id):
        try:
            _execute_operation_scope(db, op, now)
            completed_at = datetime.now(timezone.utc)
            db.conn.execute(
                "UPDATE refresh_operations SET status = 'completed', completed_at = ?, lease_expires_at = NULL WHERE id = ?",
                (completed_at.isoformat(), op.id),
            )
            db.conn.commit()
            return {"operation_id": op.id, "scope": op.scope, "status": "completed"}
        except Exception as e:
            from app.runtime.sanitization import sanitize_error
            _, sanitized = sanitize_error(e)
            db.conn.execute(
                "UPDATE refresh_operations SET status = 'failed', error_summary = ?, completed_at = ?, lease_expires_at = NULL WHERE id = ?",
                (sanitized, datetime.now(timezone.utc).isoformat(), op.id),
            )
            db.conn.commit()
            return {"operation_id": op.id, "scope": op.scope, "status": "failed", "error": sanitized}


def startup_daily_catch_up(
    db: Database,
    now: Optional[datetime] = None,
    config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Startup catch-up for the daily intelligence cycle.

    Inspects the daily-run status for the current runtime date (NOT merely
    briefing existence):
      - no run and scheduled time passed -> run the full daily refresh
      - failed run past retry interval -> retry via the same pipeline
      - completed/completed_empty/partial_sources -> skip (day is settled)
      - scheduled time not yet passed -> skip (normal schedule will handle it)
    """
    if now is None:
        now = datetime.now(timezone.utc)
    if config is None:
        config = load_runtime_config()

    from app.runtime.timezone import runtime_date_string, to_runtime_local
    from app.runtime.scheduler import is_job_due

    today_str = runtime_date_string(now, config)
    run_state = db.get_daily_signal_run_by_date(today_str)

    if run_state is not None and run_state.status in ("completed", "completed_empty", "partial_sources"):
        return {"action": "skipped", "reason": "ALREADY_COMPLETED_TODAY", "surface_date": today_str}

    due, reason = is_job_due("daily_refresh", db, now, config)
    if not due:
        return {"action": "skipped", "reason": reason, "surface_date": today_str}

    result = run_daily_refresh(db, now=now, surface_date=today_str)
    return {"action": "executed", "reason": reason, "surface_date": today_str, "result": result}


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
        # A. Startup daily-cycle catch-up: inspects daily-run status (not just
        # briefing existence) and retries failed/incomplete cycles per policy.
        try:
            now_utc = datetime.now(timezone.utc)
            catch_up = startup_daily_catch_up(db, now=now_utc, config=config)
            if catch_up.get("action") == "executed":
                logger.info(f"Startup daily catch-up executed ({catch_up.get('reason')}).")
            else:
                logger.info(f"Startup daily catch-up skipped: {catch_up.get('reason')}")
        except Exception as e:
            logger.error(f"Startup daily catch-up check failed: {e}")

        logger.info("HERMES daemon started successfully. Entering scheduler loop.")
        while not _stop_requested:
            now = datetime.now(timezone.utc)
            run_all_due_jobs(db, now=now, config=config)
            
            # B. Poll and execute queued background operations via the
            # canonical testable dispatch.
            try:
                op_result = process_next_queued_operation(db, now=now)
                if op_result:
                    logger.info(f"Processed refresh operation: {op_result}")
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
    # Database() applies the operational default path resolution
    # (HERMES_DB_PATH env > default runtime DB), so the daemon always
    # operates on the canonical operational database.
    db = Database()
    run_daemon(
        db=db,
        once=args.once,
        job_name=args.job,
        dry_run=args.dry_run,
    )
    return 0


if __name__ == "__main__":
    main()
