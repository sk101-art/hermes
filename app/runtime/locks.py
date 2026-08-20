import json
import os
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional


def is_pid_alive(pid: int) -> bool:
    """Checks if a process with given PID is currently active on the host OS."""
    if pid <= 0:
        return False
    if sys.platform == "win32":
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if handle:
                kernel32.CloseHandle(handle)
                return True
            # Check last error: 5 = ERROR_ACCESS_DENIED (means process exists)
            err = kernel32.GetLastError()
            if err == 5:
                return True
            return False
        except Exception:
            pass
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False


class SingleInstanceLock:
    """
    Prevents multiple HERMES daemon instances from running concurrently.
    Supports crash-safe stale lock detection and recovery.
    """

    def __init__(self, lock_path: str = "data/hermes.lock"):
        self.lock_path = Path(lock_path)
        self.acquired = False
        self.owner_pid = os.getpid()

    def acquire(self) -> bool:
        """Attempts to acquire the single instance lock."""
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)

        if self.lock_path.exists():
            try:
                content = self.lock_path.read_text(encoding="utf-8")
                data = json.loads(content) if content else {}
                existing_pid = data.get("pid")

                if existing_pid == self.owner_pid:
                    self.acquired = True
                    return True

                if existing_pid and is_pid_alive(existing_pid):
                    # Active process owns the lock
                    return False
                else:
                    # Stale lock from terminated process -> recover
                    try:
                        self.lock_path.unlink(missing_ok=True)
                    except Exception:
                        pass
            except Exception:
                try:
                    self.lock_path.unlink(missing_ok=True)
                except Exception:
                    pass

        # Write lock file
        payload = {
            "pid": self.owner_pid,
            "hostname": platform.node(),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "version": "0.9.0",
        }
        try:
            self.lock_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            self.acquired = True
            return True
        except Exception:
            return False

    def release(self) -> None:
        """Releases the lock file if owned by the current process."""
        if self.acquired and self.lock_path.exists():
            try:
                content = self.lock_path.read_text(encoding="utf-8")
                data = json.loads(content) if content else {}
                if data.get("pid") == self.owner_pid:
                    self.lock_path.unlink(missing_ok=True)
            except Exception:
                pass
            finally:
                self.acquired = False

    def get_lock_info(self) -> Optional[Dict[str, Any]]:
        """Returns details about the current lock file."""
        if not self.lock_path.exists():
            return None
        try:
            content = self.lock_path.read_text(encoding="utf-8")
            return json.loads(content) if content else None
        except Exception:
            return None

    def __enter__(self):
        if not self.acquire():
            raise RuntimeError(f"HERMES single-instance lock could not be acquired (held by another active process).")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.release()


class JobLock:
    """In-process and file-assisted lock for individual heavy jobs to prevent self-overlap."""

    _active_jobs = set()

    def __init__(self, job_name: str, lock_dir: str = "data/locks"):
        self.job_name = job_name
        self.lock_dir = Path(lock_dir)
        self.lock_file = self.lock_dir / f"{job_name}.lock"
        self.acquired = False

    def acquire(self) -> bool:
        if self.job_name in JobLock._active_jobs:
            return False

        self.lock_dir.mkdir(parents=True, exist_ok=True)
        if self.lock_file.exists():
            try:
                data = json.loads(self.lock_file.read_text(encoding="utf-8"))
                pid = data.get("pid")
                if pid and pid != os.getpid() and is_pid_alive(pid):
                    return False
                self.lock_file.unlink(missing_ok=True)
            except Exception:
                self.lock_file.unlink(missing_ok=True)

        try:
            payload = {"job_name": self.job_name, "pid": os.getpid(), "acquired_at": datetime.now(timezone.utc).isoformat()}
            self.lock_file.write_text(json.dumps(payload), encoding="utf-8")
            JobLock._active_jobs.add(self.job_name)
            self.acquired = True
            return True
        except Exception:
            return False

    def release(self) -> None:
        JobLock._active_jobs.discard(self.job_name)
        if self.acquired and self.lock_file.exists():
            try:
                self.lock_file.unlink(missing_ok=True)
            except Exception:
                pass
            finally:
                self.acquired = False

    def __enter__(self):
        if not self.acquire():
            raise RuntimeError(f"Job lock for '{self.job_name}' could not be acquired.")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.release()
