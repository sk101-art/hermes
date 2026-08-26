import argparse
import os
import subprocess
import sys
from pathlib import Path
from typing import Tuple

TASK_NAME = "HERMES-Tech-Intelligence"


def build_task_parameters() -> Tuple[str, str, str, str]:
    """Generates dynamic, absolute parameters for Windows Task Scheduler registration.

    The scheduled task launches the HERMES supervisor, which manages both the
    API server and the daemon as separate child processes with automatic
    restart on failure and duplicate prevention.
    """
    python_exe = str(Path(sys.executable).resolve())
    working_dir = str(Path.cwd().resolve())
    action_cmd = f'"{python_exe}" -m app.runtime.supervisor'
    return TASK_NAME, python_exe, working_dir, action_cmd


def query_task(task_name: str = TASK_NAME) -> Tuple[bool, str]:
    """Queries Task Scheduler to check if the task exists."""
    cmd = ["schtasks", "/query", "/tn", task_name, "/fo", "LIST"]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if res.returncode == 0 and task_name.lower() in res.stdout.lower():
            return True, res.stdout
        return False, res.stderr or res.stdout
    except Exception as e:
        return False, str(e)


def install_scheduled_task(dry_run: bool = False) -> Tuple[bool, str]:
    """
    Registers HERMES autonomous runtime as a logon scheduled task for the current user.
    """
    task_name, python_exe, working_dir, action_cmd = build_task_parameters()

    if dry_run:
        print("=" * 65)
        print("HERMES — WINDOWS TASK SCHEDULER INSTALLATION (DRY RUN)")
        print("=" * 65)
        print(f"Task Name:          {task_name}")
        print(f"Python Executable:  {python_exe}")
        print(f"Working Directory:  {working_dir}")
        print(f"Action Command:     {action_cmd}")
        print(f"Trigger:            At User Logon (/sc ONLOGON)")
        print(f"Settings:           Supervisor manages API+daemon; restarts children")
        print(f"                    on failure; single-instance lock prevents duplicates")
        print("=" * 65)
        return True, "Dry-run complete. No changes made."

    print("=" * 65)
    print("HERMES — INSTALLING WINDOWS STARTUP TASK")
    print("=" * 65)
    print(f"Task Name:          {task_name}")
    print(f"Python Executable:  {python_exe}")
    print(f"Working Directory:  {working_dir}")

    # Build schtasks create command for current user at logon
    # /sc ONLOGON /tr "python.exe -m app.runtime.runner" /f
    cmd = [
        "schtasks",
        "/create",
        "/tn",
        task_name,
        "/tr",
        action_cmd,
        "/sc",
        "ONLOGON",
        "/f",
    ]

    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if res.returncode != 0:
            err = res.stderr.strip() or res.stdout.strip()
            print(f"[Error] Failed to register scheduled task: {err}")
            return False, err

        # Verify task exists
        exists, query_output = query_task(task_name)
        if not exists:
            print("[Error] schtasks returned success but query verification failed.")
            return False, "Task verification failed"

        print(f"Status:             INSTALLED & VERIFIED")
        print("=" * 65)
        return True, "Task successfully registered and verified"
    except Exception as e:
        print(f"[Error] Exception occurred during task installation: {e}")
        return False, str(e)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="HERMES Windows Task Scheduler Installer")
    parser.add_argument("--dry-run", action="store_true", help="Preview scheduled task configuration without installing")
    args = parser.parse_args()
    success, msg = install_scheduled_task(dry_run=args.dry_run)
    if not success:
        sys.exit(1)
