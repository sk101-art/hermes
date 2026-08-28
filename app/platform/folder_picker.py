"""Native folder-picker abstraction for the HERMES local API.

Browsers cannot expose the absolute filesystem path of a selected directory
(``<input type="file">`` gives only a fake name, and the File System Access
API returns an opaque handle). HERMES therefore opens a *native* OS folder
dialog in the interactive user session and hands the backend the real path.

Security properties enforced here:

* Only ONE picker may be open at a time (module-level lock + busy flag).
* Cancellation is a clean ``PickerCancelled`` — never an error surfaced to
  the user.
* The dialog runs in a short-lived child process with a hard timeout so a
  hung dialog can never wedge the API worker.
* The launcher is injectable so tests can exercise the full flow without a
  real desktop session.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from dataclasses import dataclass
from typing import Callable, List, Optional

# Hard cap on how long we wait for the user to make a selection.
PICKER_TIMEOUT_SECONDS = 300


class PickerCancelled(Exception):
    """The user closed the dialog without choosing a folder."""


class PickerBusy(Exception):
    """Another folder picker is already open."""


class PickerUnavailable(Exception):
    """No native picker could be launched on this platform/session."""


@dataclass(frozen=True)
class PickerResult:
    """Outcome of a successful native folder selection."""

    path: str  # absolute path exactly as chosen in the dialog
    folder_name: str


# --- PowerShell script --------------------------------------------------------
# Runs in STA mode (required by the WinForms FolderBrowserDialog / IFileDialog
# COM apartment). Prints a single JSON line so the parent can parse the result
# unambiguously. Exit codes: 0 = selected, 3 = cancelled, anything else = error.
_WINDOWS_PICKER_PS1 = r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$dialog = New-Object System.Windows.Forms.FolderBrowserDialog
$dialog.Description = 'Select the project folder for HERMES to index'
$dialog.ShowNewFolderButton = $false
$result = $dialog.ShowDialog()
if ($result -eq [System.Windows.Forms.DialogResult]::OK -and $dialog.SelectedPath) {
    Write-Output ('HERMES_PICK:' + (@{ path = $dialog.SelectedPath } | ConvertTo-Json -Compress))
    exit 0
} else {
    Write-Output 'HERMES_PICK_CANCELLED'
    exit 3
}
"""


def _default_windows_launcher(args: List[str]) -> subprocess.CompletedProcess:
    """Launches PowerShell in STA mode for the WinForms dialog API."""
    return subprocess.run(
        args,
        capture_output=True,
        text=True,
        timeout=PICKER_TIMEOUT_SECONDS,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def _default_posix_launcher(args: List[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        args,
        capture_output=True,
        text=True,
        timeout=PICKER_TIMEOUT_SECONDS,
    )


def _build_windows_command() -> List[str]:
    """Builds the powershell.exe command line for the STA dialog.

    ``-STA`` is mandatory: FolderBrowserDialog (and the IFileDialog COM
    interface behind modern dialogs) must run on a single-threaded apartment
    thread, and uvicorn worker threads are MTA.
    """
    exe = "powershell.exe"
    return [
        exe,
        "-NoProfile",
        "-NonInteractive",
        "-STA",
        "-ExecutionPolicy", "Bypass",
        "-Command", _WINDOWS_PICKER_PS1,
    ]


def _parse_windows_output(stdout: str) -> PickerResult:
    """Parses the JSON marker line emitted by the PowerShell script."""
    for line in (stdout or "").splitlines():
        line = line.strip()
        if line.startswith("HERMES_PICK:"):
            payload = json.loads(line[len("HERMES_PICK:"):])
            raw_path = str(payload.get("path", "")).strip()
            if not raw_path:
                raise PickerUnavailable("Native dialog returned an empty path.")
            abs_path = os.path.abspath(raw_path)
            return PickerResult(path=abs_path, folder_name=os.path.basename(abs_path.rstrip("/\\")) or abs_path)
        if line == "HERMES_PICK_CANCELLED":
            raise PickerCancelled()
    raise PickerUnavailable("Native dialog produced no parseable result.")


class FolderPicker:
    """Serializes native folder-picker invocations.

    Only one dialog may be open at any time; concurrent requests receive
    ``PickerBusy`` (surfaced as HTTP 409 by the API layer).
    """

    def __init__(
        self,
        launcher: Optional[Callable[[List[str]], subprocess.CompletedProcess]] = None,
        timeout_seconds: float = PICKER_TIMEOUT_SECONDS,
    ) -> None:
        self._lock = threading.Lock()
        self._busy = False
        self._timeout = timeout_seconds
        self._launcher = launcher

    @property
    def busy(self) -> bool:
        return self._busy

    def pick_folder(self, title: Optional[str] = None) -> PickerResult:
        """Opens the native dialog and blocks until the user decides.

        Raises:
            PickerBusy: another picker is already open.
            PickerCancelled: the user dismissed the dialog.
            PickerUnavailable: the dialog could not be launched/parsed.
        """
        with self._lock:
            if self._busy:
                raise PickerBusy("A folder picker is already open.")
            self._busy = True
        try:
            return self._run_dialog(title)
        finally:
            with self._lock:
                self._busy = False

    def _run_dialog(self, title: Optional[str]) -> PickerResult:
        if sys.platform == "win32":
            return self._run_windows_dialog()
        # Non-Windows fallbacks (zenity / osascript) keep the module usable in
        # development environments, but Windows is the primary target.
        if sys.platform == "darwin":
            return self._run_macos_dialog()
        return self._run_linux_dialog()

    def _run_windows_dialog(self) -> PickerResult:
        launcher = self._launcher or _default_windows_launcher
        cmd = _build_windows_command()
        try:
            proc = launcher(cmd)
        except subprocess.TimeoutExpired as exc:
            raise PickerUnavailable("The folder dialog timed out.") from exc
        except FileNotFoundError as exc:
            raise PickerUnavailable("PowerShell is not available on this system.") from exc
        except Exception as exc:  # pragma: no cover - defensive
            raise PickerUnavailable(f"Failed to launch folder dialog: {exc}") from exc

        if proc.returncode == 3:
            raise PickerCancelled()
        if proc.returncode != 0:
            detail = (proc.stderr or "").strip()[:200]
            raise PickerUnavailable(f"Folder dialog failed (exit {proc.returncode}): {detail}")
        return _parse_windows_output(proc.stdout or "")

    def _run_macos_dialog(self) -> PickerResult:  # pragma: no cover - non-target
        launcher = self._launcher or _default_posix_launcher
        script = 'POSIX path of (choose folder with prompt "Select the project folder for HERMES to index")'
        try:
            proc = launcher(["osascript", "-e", script])
        except Exception as exc:
            raise PickerUnavailable(f"Failed to launch folder dialog: {exc}") from exc
        if proc.returncode != 0:
            raise PickerCancelled()
        raw = (proc.stdout or "").strip()
        if not raw:
            raise PickerUnavailable("Native dialog returned an empty path.")
        abs_path = os.path.abspath(raw)
        return PickerResult(path=abs_path, folder_name=os.path.basename(abs_path.rstrip("/")) or abs_path)

    def _run_linux_dialog(self) -> PickerResult:  # pragma: no cover - non-target
        launcher = self._launcher or _default_posix_launcher
        try:
            proc = launcher(["zenity", "--file-selection", "--directory",
                             "--title=Select the project folder for HERMES to index"])
        except FileNotFoundError as exc:
            raise PickerUnavailable("zenity is not available on this system.") from exc
        except Exception as exc:
            raise PickerUnavailable(f"Failed to launch folder dialog: {exc}") from exc
        if proc.returncode != 0:
            raise PickerCancelled()
        raw = (proc.stdout or "").strip()
        if not raw:
            raise PickerUnavailable("Native dialog returned an empty path.")
        abs_path = os.path.abspath(raw)
        return PickerResult(path=abs_path, folder_name=os.path.basename(abs_path.rstrip("/")) or abs_path)


# Process-wide singleton so the "one picker at a time" rule holds across all
# requests handled by this server process.
_default_picker: Optional[FolderPicker] = None
_default_picker_lock = threading.Lock()


def get_default_picker() -> FolderPicker:
    global _default_picker
    with _default_picker_lock:
        if _default_picker is None:
            _default_picker = FolderPicker()
        return _default_picker


def set_default_picker(picker: Optional[FolderPicker]) -> None:
    """Test hook: swap the process-wide picker instance."""
    global _default_picker
    with _default_picker_lock:
        _default_picker = picker
