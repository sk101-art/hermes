"""HERMES Supervisor — manages API and daemon as separate child processes.

The supervisor is the single entry point registered with the OS scheduler
(Windows Task Scheduler at logon). It:
  1. Acquires a supervisor-level single-instance lock (prevents duplicates).
  2. Spawns the API server (app.api.server) and the daemon (app.runtime.runner)
     as separate managed subprocesses sharing the same env/cwd/DB resolution.
  3. Restarts either child if it exits unexpectedly (bounded backoff).
  4. Shuts down both children cleanly on SIGINT/SIGTERM or supervisor exit.

Usage:
    python -m app.runtime.supervisor            # run supervisor
    python -m app.runtime.supervisor --status   # show supervisor/child status
    python -m app.runtime.supervisor --dry-run  # preview configuration only
"""
import argparse
import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from app.runtime.locks import SingleInstanceLock, is_pid_alive
from app.runtime.state import load_runtime_config

SUPERVISOR_LOCK_PATH = "data/supervisor.lock"
SUPERVISOR_STATE_PATH = "data/supervisor_state.json"
MAX_RESTART_ATTEMPTS = 5
RESTART_BACKOFF_BASE_SECONDS = 5


def _resolve_python() -> str:
    return str(Path(sys.executable).resolve())


def _write_state(state: Dict) -> None:
    try:
        p = Path(SUPERVISOR_STATE_PATH)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(state, indent=2), encoding="utf-8")
    except Exception:
        pass


def _read_state() -> Optional[Dict]:
    try:
        p = Path(SUPERVISOR_STATE_PATH)
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        pass
    return None


def build_child_commands() -> Dict[str, List[str]]:
    """Builds the subprocess commands for API and daemon children."""
    python_exe = _resolve_python()
    config = load_runtime_config()
    api_cfg = config.get("api", {})
    host = api_cfg.get("host", "127.0.0.1")
    port = api_cfg.get("port", 8765)

    return {
        "api": [python_exe, "-m", "app.api.server", "--host", host, "--port", str(port)],
        "daemon": [python_exe, "-m", "app.runtime.runner"],
    }


def run_supervisor(dry_run: bool = False) -> int:
    """Main supervisor loop. Returns process exit code."""
    commands = build_child_commands()

    if dry_run:
        print("=" * 65)
        print("HERMES — SUPERVISOR (DRY RUN)")
        print("=" * 65)
        print(f"Python:    {_resolve_python()}")
        print(f"CWD:       {os.getcwd()}")
        print(f"API cmd:   {' '.join(commands['api'])}")
        print(f"Daemon cmd:{' '.join(commands['daemon'])}")
        print(f"Lock:      {SUPERVISOR_LOCK_PATH}")
        print(f"Restart:   max {MAX_RESTART_ATTEMPTS} attempts, backoff {RESTART_BACKOFF_BASE_SECONDS}s base")
        print("=" * 65)
        return 0

    # Prevent duplicate supervisors
    lock = SingleInstanceLock(lock_path=SUPERVISOR_LOCK_PATH)
    if not lock.acquire():
        info = lock.get_lock_info() or {}
        print(f"[Supervisor] Another supervisor is already running (PID: {info.get('pid', 'unknown')}). Exiting.")
        return 1

    stop_requested = False

    def _handle_signal(signum, frame):
        nonlocal stop_requested
        stop_requested = True

    signal.signal(signal.SIGINT, _handle_signal)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _handle_signal)

    print(f"[Supervisor] Started (PID {os.getpid()}). Managing API + daemon.")

    children: Dict[str, subprocess.Popen] = {}
    restart_counts: Dict[str, int] = {"api": 0, "daemon": 0}
    last_restart: Dict[str, float] = {"api": 0.0, "daemon": 0.0}

    def spawn(name: str) -> None:
        cmd = commands[name]
        env = os.environ.copy()
        children[name] = subprocess.Popen(cmd, cwd=os.getcwd(), env=env)
        print(f"[Supervisor] Spawned '{name}' (PID {children[name].pid}): {' '.join(cmd)}")

    try:
        # Initial spawn
        for name in commands:
            spawn(name)

        _write_state({
            "supervisor_pid": os.getpid(),
            "started_at": datetime.now(timezone.utc).isoformat(),
            "children": {n: children[n].pid for n in children},
        })

        while not stop_requested:
            for name in list(commands.keys()):
                proc = children.get(name)
                if proc is None:
                    continue
                ret = proc.poll()
                if ret is not None and not stop_requested:
                    # Child exited unexpectedly — restart with backoff
                    restart_counts[name] += 1
                    if restart_counts[name] > MAX_RESTART_ATTEMPTS:
                        print(f"[Supervisor] '{name}' exceeded max restart attempts ({MAX_RESTART_ATTEMPTS}). Giving up on this child.")
                        children[name] = None
                        continue
                    backoff = RESTART_BACKOFF_BASE_SECONDS * restart_counts[name]
                    elapsed = time.time() - last_restart[name]
                    if elapsed < backoff:
                        time.sleep(min(backoff - elapsed, 5))
                    print(f"[Supervisor] '{name}' exited (code {ret}). Restarting (attempt {restart_counts[name]})...")
                    last_restart[name] = time.time()
                    spawn(name)
                    _write_state({
                        "supervisor_pid": os.getpid(),
                        "children": {n: children[n].pid for n in children if children.get(n)},
                    })

            time.sleep(2)

    finally:
        print("[Supervisor] Shutting down children...")
        for name, proc in children.items():
            if proc and proc.poll() is None:
                proc.terminate()
        # Wait for graceful exit
        deadline = time.time() + 10
        for name, proc in children.items():
            if proc and proc.poll() is None:
                remaining = max(0, deadline - time.time())
                try:
                    proc.wait(timeout=remaining)
                except subprocess.TimeoutExpired:
                    proc.kill()
        lock.release()
        try:
            Path(SUPERVISOR_STATE_PATH).unlink(missing_ok=True)
        except Exception:
            pass
        print("[Supervisor] Stopped.")

    return 0


def supervisor_status() -> int:
    """Prints current supervisor and child process status."""
    state = _read_state()
    if not state:
        print("[Supervisor] Not running (no state file).")
        return 1

    sup_pid = state.get("supervisor_pid")
    alive = is_pid_alive(sup_pid) if sup_pid else False
    print(f"Supervisor PID: {sup_pid} ({'RUNNING' if alive else 'NOT RUNNING'})")
    print(f"Started at:     {state.get('started_at', 'unknown')}")
    for name, pid in (state.get("children") or {}).items():
        child_alive = is_pid_alive(pid) if pid else False
        print(f"  {name:<8} PID: {pid} ({'RUNNING' if child_alive else 'NOT RUNNING'})")
    return 0 if alive else 1


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="HERMES Supervisor — manages API + daemon")
    parser.add_argument("--dry-run", action="store_true", help="Preview configuration without starting")
    parser.add_argument("--status", action="store_true", help="Show supervisor status")
    args = parser.parse_args(argv)

    if args.status:
        return supervisor_status()
    return run_supervisor(dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
