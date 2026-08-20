import subprocess
import sys
from typing import Tuple

from app.runtime.install_windows import TASK_NAME, query_task


def uninstall_scheduled_task() -> Tuple[bool, str]:
    """Removes the HERMES scheduled startup task from Windows Task Scheduler."""
    print("=" * 65)
    print("HERMES — UNINSTALLING WINDOWS STARTUP TASK")
    print("=" * 65)
    print(f"Task Name: {TASK_NAME}")

    cmd = ["schtasks", "/delete", "/tn", TASK_NAME, "/f"]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=False)
        # Verify removal
        exists, _ = query_task(TASK_NAME)
        if exists:
            err = res.stderr.strip() or res.stdout.strip()
            print(f"[Error] Failed to remove task: {err}")
            return False, err

        print("Status:    REMOVED & VERIFIED")
        print("=" * 65)
        return True, "Task successfully removed"
    except Exception as e:
        print(f"[Error] Exception occurred during task removal: {e}")
        return False, str(e)


if __name__ == "__main__":
    success, msg = uninstall_scheduled_task()
    if not success:
        sys.exit(1)
