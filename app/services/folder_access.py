"""Machine-local folder approvals and native-picker selection tokens.

This module implements the trust boundary for local project folders:

* **Selection tokens** — short-lived, random, single-use opaque tokens that
  stand for "the folder the user just chose in the native OS dialog". The
  frontend never sees (and can never tamper with) the absolute path; it only
  submits the token back.
* **Session tokens** — per-server-process tokens tying selection tokens to the
  current local session.
* **Approved roots** — a machine-local JSON ledger
  (``data/runtime/approved_project_roots.json``) recording every directory the
  user explicitly approved for indexing. Tracked config files are never
  modified. Revoking an approval stops future scans but preserves all stored
  intelligence.

All state here is local to this machine/process; nothing is derived from
browser-supplied paths.
"""
from __future__ import annotations

import json
import os
import secrets
import tempfile
import threading
import time
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional

# --- Tunables -----------------------------------------------------------------
SELECTION_TOKEN_TTL_SECONDS = 300        # 5 minutes to use a selection
SESSION_TOKEN_TTL_SECONDS = 12 * 3600    # 12 hours per local session
PICKER_RATE_LIMIT_MAX_CALLS = 5
PICKER_RATE_LIMIT_WINDOW_SECONDS = 60.0

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_APPROVALS_FILE = REPO_ROOT / "data" / "runtime" / "approved_project_roots.json"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def approvals_file_path() -> Path:
    """Resolves the machine-local approvals ledger path.

    ``HERMES_APPROVED_ROOTS_FILE`` overrides the default location (used by
    tests and unusual deployments).
    """
    env = os.environ.get("HERMES_APPROVED_ROOTS_FILE", "").strip()
    if env:
        return Path(env).expanduser().resolve()
    return DEFAULT_APPROVALS_FILE


# =============================================================================
# In-memory token stores (selection + session tokens)
# =============================================================================
class _TokenStores:
    """Thread-safe in-memory stores for selection and session tokens."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._selections: Dict[str, Dict[str, Any]] = {}
        self._sessions: Dict[str, float] = {}  # token -> expiry epoch

    # --- session tokens -------------------------------------------------
    def issue_session_token(self) -> Dict[str, Any]:
        token = secrets.token_urlsafe(32)
        expires_at = _utcnow() + timedelta(seconds=SESSION_TOKEN_TTL_SECONDS)
        with self._lock:
            self._sessions[token] = expires_at.timestamp()
        return {"session_token": token, "expires_at": _iso(expires_at)}

    def validate_session_token(self, token: Optional[str]) -> bool:
        if not token:
            return False
        with self._lock:
            expiry = self._sessions.get(token)
            if expiry is None:
                return False
            if time.time() > expiry:
                self._sessions.pop(token, None)
                return False
            return True

    # --- selection tokens -------------------------------------------------
    def create_selection_token(self, path: str, folder_name: str, session_token: str) -> Dict[str, Any]:
        token = secrets.token_urlsafe(24)
        expires_at = _utcnow() + timedelta(seconds=SELECTION_TOKEN_TTL_SECONDS)
        record = {
            "token": token,
            "path": path,
            "folder_name": folder_name,
            "session_token": session_token,
            "created_at": _utcnow(),
            "expires_at": expires_at,
            "used": False,
        }
        with self._lock:
            self._prune_expired_locked()
            self._selections[token] = record
        return {
            "selection_token": token,
            "display_path": path,
            "folder_name": folder_name,
            "expires_at": _iso(expires_at),
        }

    def consume_selection_token(self, token: Optional[str], session_token: Optional[str]) -> Dict[str, Any]:
        """Single-use consumption of a selection token.

        Raises ValueError with a user-safe message on any problem (expired,
        unknown, replayed, or session mismatch). The token is destroyed on
        every consumption attempt so a replay can never succeed later.
        """
        if not token:
            raise ValueError("Missing folder selection token.")
        with self._lock:
            self._prune_expired_locked()
            record = self._selections.pop(token, None)
        if record is None:
            raise ValueError("Folder selection token is invalid or has expired.")
        if record["used"]:
            raise ValueError("Folder selection token was already used.")
        if _utcnow() > record["expires_at"]:
            raise ValueError("Folder selection token has expired.")
        if record["session_token"] != (session_token or ""):
            raise ValueError("Folder selection token does not belong to this session.")
        record["used"] = True
        return record

    def _prune_expired_locked(self) -> None:
        now = _utcnow()
        expired = [t for t, r in self._selections.items() if now > r["expires_at"]]
        for t in expired:
            self._selections.pop(t, None)
        expired_sessions = [t for t, exp in self._sessions.items() if time.time() > exp]
        for t in expired_sessions:
            self._sessions.pop(t, None)

    def clear(self) -> None:
        with self._lock:
            self._selections.clear()
            self._sessions.clear()


_stores = _TokenStores()


def get_token_stores() -> _TokenStores:
    return _stores


# =============================================================================
# Rate limiter for the native picker endpoint
# =============================================================================
class RateLimiter:
    """Sliding-window call limiter (thread-safe)."""

    def __init__(self, max_calls: int = PICKER_RATE_LIMIT_MAX_CALLS,
                 window_seconds: float = PICKER_RATE_LIMIT_WINDOW_SECONDS) -> None:
        self.max_calls = max_calls
        self.window_seconds = window_seconds
        self._lock = threading.Lock()
        self._calls: Deque[float] = deque()

    def allow(self) -> bool:
        now = time.monotonic()
        with self._lock:
            while self._calls and now - self._calls[0] > self.window_seconds:
                self._calls.popleft()
            if len(self._calls) >= self.max_calls:
                return False
            self._calls.append(now)
            return True

    def reset(self) -> None:
        with self._lock:
            self._calls.clear()


picker_rate_limiter = RateLimiter()


# =============================================================================
# Approved roots ledger (machine-local JSON file, atomic writes)
# =============================================================================
class ApprovalStore:
    """Persistent ledger of explicitly approved project folders.

    Records are keyed by canonical (resolved, case-folded on Windows) path.
    Writes are atomic: temp file + ``os.replace`` so a crash can never leave a
    half-written ledger.
    """

    def __init__(self, file_path: Optional[Path] = None) -> None:
        self._lock = threading.Lock()
        self._file_path = file_path

    @property
    def file_path(self) -> Path:
        return self._file_path or approvals_file_path()

    @staticmethod
    def _canonical(path: str) -> str:
        return str(Path(path)).replace("\\", "/").lower()

    def _load_locked(self) -> Dict[str, Dict[str, Any]]:
        path = self.file_path
        if not path.exists():
            return {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            records = data.get("approved_roots", {}) if isinstance(data, dict) else {}
            return records if isinstance(records, dict) else {}
        except Exception:
            # Corrupt ledger: treat as empty rather than crashing the API.
            return {}

    def _save_locked(self, records: Dict[str, Dict[str, Any]]) -> None:
        path = self.file_path
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"version": 1, "updated_at": _iso(_utcnow()), "approved_roots": records}
        fd, tmp_name = tempfile.mkstemp(prefix=".approved_roots_", suffix=".tmp", dir=str(path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, ensure_ascii=False)
            os.replace(tmp_name, path)
        except Exception:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise

    def list_records(self) -> List[Dict[str, Any]]:
        with self._lock:
            records = self._load_locked()
        return sorted(records.values(), key=lambda r: r.get("approved_at", ""))

    def get_for_project(self, project_id: str, state: Optional[str] = None) -> List[Dict[str, Any]]:
        out = []
        for rec in self.list_records():
            if rec.get("project_id") == project_id and (state is None or rec.get("state") == state):
                out.append(rec)
        return out

    def approve(self, path: str, project_id: str, source: str = "native_picker") -> Dict[str, Any]:
        resolved = str(Path(path).resolve())
        key = self._canonical(resolved)
        with self._lock:
            records = self._load_locked()
            record = records.get(key) or {}
            record.update({
                "path": resolved,
                "approved_at": _iso(_utcnow()),
                "approval_source": source,
                "project_id": project_id,
                "state": "active",
                "revoked_at": None,
            })
            records[key] = record
            self._save_locked(records)
            return dict(record)

    def revoke_for_project(self, project_id: str) -> List[Dict[str, Any]]:
        revoked = []
        with self._lock:
            records = self._load_locked()
            for key, rec in records.items():
                if rec.get("project_id") == project_id and rec.get("state") == "active":
                    rec["state"] = "revoked"
                    rec["revoked_at"] = _iso(_utcnow())
                    revoked.append(dict(rec))
            if revoked:
                self._save_locked(records)
        return revoked

    def revoke_path(self, path: str) -> bool:
        """Revokes the approval for one exact path (if active)."""
        key = self._canonical(str(Path(path).resolve()))
        with self._lock:
            records = self._load_locked()
            rec = records.get(key)
            if rec and rec.get("state") == "active":
                rec["state"] = "revoked"
                rec["revoked_at"] = _iso(_utcnow())
                self._save_locked(records)
                return True
            return False

    def remove(self, path: str) -> bool:
        key = self._canonical(str(Path(path).resolve()))
        with self._lock:
            records = self._load_locked()
            if key in records:
                del records[key]
                self._save_locked(records)
                return True
            return False

    def active_paths(self) -> List[Path]:
        paths = []
        for rec in self.list_records():
            if rec.get("state") == "active":
                try:
                    paths.append(Path(rec["path"]).resolve())
                except Exception:
                    continue
        return paths

    def is_revoked(self, path: str) -> bool:
        """True iff this exact path has a revoked approval and no active one."""
        key = self._canonical(str(Path(path).resolve()))
        with self._lock:
            records = self._load_locked()
        rec = records.get(key)
        return bool(rec and rec.get("state") == "revoked")


_default_store: Optional[ApprovalStore] = None
_default_store_lock = threading.Lock()


def get_approval_store() -> ApprovalStore:
    """Process-wide store bound to the (env-overridable) ledger path.

    A new instance is created if the resolved path changed since the last
    call (tests flip HERMES_APPROVED_ROOTS_FILE per test).
    """
    global _default_store
    with _default_store_lock:
        path = approvals_file_path()
        if _default_store is None or _default_store.file_path != path:
            _default_store = ApprovalStore(path)
        return _default_store


def is_folder_access_revoked(path: str) -> bool:
    """Scan gate: True when the folder's approval was explicitly revoked."""
    try:
        return get_approval_store().is_revoked(path)
    except Exception:
        return False


# =============================================================================
# Candidate folder validation
# =============================================================================
def _is_subpath(child: Path, parent: Path) -> bool:
    try:
        c = str(child).replace("\\", "/").lower().rstrip("/")
        p = str(parent).replace("\\", "/").lower().rstrip("/")
        return c == p or c.startswith(p + "/")
    except Exception:
        return False


def _symlink_escape(raw_path: str, resolved: Path) -> bool:
    """True when resolving the literally-selected path lands somewhere else.

    The native dialog returns the folder the user actually clicked. If
    resolution walks through a symlink/junction (or ``..`` traversal), the
    real target is a different directory than the one chosen — that is an
    escape and is always rejected. Comparison is case-insensitive because
    Windows resolution normalizes component casing without any link involved.
    """
    try:
        literal = str(Path(os.path.abspath(raw_path))).lower().replace("\\", "/").rstrip("/")
        real = str(resolved).lower().replace("\\", "/").rstrip("/")
        return literal != real
    except Exception:
        return True


def validate_folder_safety(raw_path: str, db: Any = None, ignore_project_id: Optional[str] = None) -> Path:
    """SAFETY validation only — independent of how the folder was chosen.

    Checks: exists, readable directory, not a drive/home/runtime root, no
    symlink escape, does not contain the HERMES database, and no duplicate or
    overlapping registration against existing projects.

    Deliberately does NOT check the legacy/default allowed roots: a folder
    chosen in the trusted native picker is approved by that act alone (subject
    to the explicit administrator policy ceiling, checked separately).

    Raises ValueError with a human-readable reason on any failure; returns the
    canonical resolved directory on success.
    """
    if not raw_path or not str(raw_path).strip():
        raise ValueError("No folder was selected.")

    try:
        resolved = Path(raw_path).resolve(strict=True)
    except OSError:
        raise ValueError("The selected folder does not exist or cannot be resolved.")

    if _symlink_escape(raw_path, resolved):
        raise ValueError("The selected folder resolves through a symbolic link; choose the real folder instead.")

    if not resolved.is_dir():
        raise ValueError("The selected path is not a directory.")
    if not os.access(resolved, os.R_OK):
        raise ValueError("The selected folder is not readable.")

    # Drive roots (C:\, /) are never valid project folders.
    if resolved.parent == resolved:
        raise ValueError("A drive root cannot be used as a project folder.")

    # The user profile root is never valid either.
    try:
        home = Path.home().resolve()
        if resolved == home:
            raise ValueError("The user profile root cannot be used as a project folder.")
    except Exception:
        pass

    # HERMES operational data must never be indexed.
    data_dir = (REPO_ROOT / "data").resolve()
    if resolved == data_dir or _is_subpath(resolved, data_dir):
        raise ValueError("HERMES operational data directories cannot be used as project folders.")

    # Never approve a folder that contains the runtime database itself.
    try:
        from app.storage.db import resolve_db_path
        db_file = Path(resolve_db_path(None)).resolve()
        if _is_subpath(db_file, resolved):
            raise ValueError("The selected folder contains the HERMES database and cannot be indexed.")
    except ValueError:
        raise
    except Exception:
        pass

    # Duplicate / overlapping registrations against existing projects.
    try:
        existing = db.get_all_projects(active_only=True) if db is not None else []
    except Exception:
        existing = []
    for proj in existing:
        if ignore_project_id and proj.id == ignore_project_id:
            continue
        try:
            other = Path(proj.path).resolve()
        except Exception:
            continue
        if resolved == other:
            raise ValueError(f"Folder is already registered as project '{proj.name}'.")
        if _is_subpath(resolved, other) or _is_subpath(other, resolved):
            raise ValueError(f"Folder overlaps with existing project '{proj.name}' ({proj.path}).")

    return resolved


def validate_admin_policy(resolved: Path) -> None:
    """APPROVAL/POLICY validation: the explicit administrator ceiling.

    ``HERMES_ALLOWED_PROJECT_ROOTS``, when (and only when) explicitly set, is
    the single hard policy ceiling that even native-picker selections cannot
    cross. Config-file roots and built-in defaults are legacy/seeded approvals
    and deliberately do NOT restrict new picker approvals.
    """
    try:
        from app.context.scanner import get_admin_policy_roots, is_inside_admin_policy
        if get_admin_policy_roots() and not is_inside_admin_policy(resolved):
            raise ValueError(
                "The selected folder is outside the administrator's allowed project roots policy "
                "(HERMES_ALLOWED_PROJECT_ROOTS)."
            )
    except ValueError:
        raise
    except Exception:
        pass


def validate_candidate_folder(raw_path: str, db: Any, ignore_project_id: Optional[str] = None) -> Path:
    """Full validation for a folder chosen through the native picker:
    safety validation + explicit admin-policy ceiling. Legacy/default allowed
    roots are NOT a restriction here — the trusted picker is the approval.
    """
    resolved = validate_folder_safety(raw_path, db, ignore_project_id=ignore_project_id)
    validate_admin_policy(resolved)
    return resolved


def issue_selection_token(picker_result: Any, session_token: str, db: Any) -> Dict[str, Any]:
    """Validates a native-picker result, then issues the short-lived,
    single-use selection token for exactly the chosen directory.

    Safety + policy validation happens BEFORE the token exists, so an invalid
    folder can never produce a usable token.
    """
    resolved = validate_candidate_folder(picker_result.path, db)
    return get_token_stores().create_selection_token(
        path=str(resolved),
        folder_name=picker_result.folder_name,
        session_token=session_token,
    )


# =============================================================================
# High-level flows used by the API layer
# =============================================================================
def add_project_with_approved_folder(
    name: str,
    description: Optional[str],
    folder_selection_token: Optional[str],
    session_token: Optional[str],
    db: Any,
) -> Any:
    """Atomically: consume token → validate → approve → create project → scan.

    If project creation fails, the approval is rolled back so no unused
    approval is left behind.
    """
    from app.services import projects as projects_service

    # Single-use consumption: the token is destroyed by this attempt and can
    # never be replayed, whether or not creation below succeeds.
    selection = get_token_stores().consume_selection_token(folder_selection_token, session_token)
    # Re-validate at consumption time: the folder may have changed between
    # selection and submission (TTL is up to 5 minutes).
    resolved = validate_candidate_folder(selection["path"], db)

    # Predict the project id exactly like projects_service.add_project does.
    name_clean = (name or "").strip()
    if not name_clean:
        raise ValueError("Project name must not be empty.")
    project_id = f"project:{name_clean.lower().replace(' ', '_')}"
    if db.get_project(project_id) is not None:
        raise ValueError(f"Project '{name_clean}' already exists.")

    # Atomic unit: persist the approval for the EXACT selected directory,
    # create the project, and enqueue the targeted scan together. If the
    # project write fails, the approval is rolled back — no orphans.
    store = get_approval_store()
    store.approve(str(resolved), project_id=project_id, source="native_picker")
    try:
        proj = projects_service.add_project(
            name=name_clean,
            path=str(resolved),
            description=description,
            db=db,
            approved_via_picker=True,
        )
    except Exception:
        # Roll back the approval — never leave an unused approval behind.
        store.remove(str(resolved))
        raise
    return proj


def replace_project_folder(
    project_id: str,
    folder_selection_token: Optional[str],
    session_token: Optional[str],
    db: Any,
) -> Any:
    """Replaces a project's folder using a fresh native-picker selection.

    Flow: consume token → validate (ignoring the project itself) → approve the
    new folder → update the project → revoke the old folder's approval. If the
    update fails, the new approval is rolled back and the old approval stays
    active.
    """
    from app.services import projects as projects_service

    proj = db.get_project(project_id)
    if proj is None:
        raise LookupError(f"Project '{project_id}' not found.")

    selection = get_token_stores().consume_selection_token(folder_selection_token, session_token)
    resolved = validate_candidate_folder(selection["path"], db, ignore_project_id=project_id)

    # Remember the old folder so its approval can be revoked after success.
    old_path: Optional[Path] = None
    try:
        old_path = Path(proj.path).resolve()
    except Exception:
        old_path = None

    store = get_approval_store()
    store.approve(str(resolved), project_id=project_id, source="native_picker")
    try:
        updated = projects_service.update_project(
            project_id=project_id,
            path=str(resolved),
            db=db,
            approved_via_picker=True,
        )
    except Exception:
        # Roll back the new approval; the old one remains active.
        store.remove(str(resolved))
        raise
    # Revoke the previous folder's approval (keeps its history row).
    if old_path is not None and old_path != resolved:
        store.revoke_path(str(old_path))
    return updated


def revoke_project_folder(project_id: str, db: Any) -> List[Dict[str, Any]]:
    """Revokes folder access for a project without deleting the project or its
    stored intelligence. Future scans of the folder are skipped."""
    proj = db.get_project(project_id)
    if proj is None:
        raise LookupError(f"Project '{project_id}' not found.")
    return get_approval_store().revoke_for_project(project_id)


def approval_status(record: Dict[str, Any]) -> str:
    """Computes a human-readable folder status for the GUI."""
    if record.get("state") != "active":
        return "revoked"
    p = Path(record.get("path", ""))
    try:
        if not p.exists():
            return "missing"
        if not p.is_dir():
            return "missing"
        if not os.access(p, os.R_OK):
            return "unreadable"
    except Exception:
        return "missing"
    return "ok"


def list_approvals_with_status(db: Any) -> List[Dict[str, Any]]:
    """Approval records enriched with live folder status and project name."""
    out = []
    for rec in get_approval_store().list_records():
        item = dict(rec)
        item["status"] = approval_status(rec)
        proj = None
        try:
            proj = db.get_project(rec.get("project_id", "")) if rec.get("project_id") else None
        except Exception:
            proj = None
        item["project_name"] = proj.name if proj else None
        out.append(item)
    return out
