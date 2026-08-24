import hashlib
import json
import os
import shutil
import socket
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from app.runtime.locks import SingleInstanceLock
from app.runtime.sanitization import sanitize_error
from app.runtime.state import is_heartbeat_alive, load_runtime_config, read_heartbeat
from app.storage.db import Database

try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# Thread-safe in-memory cache for system health
_health_cache: Dict[str, Tuple[datetime, Dict[str, Any]]] = {}
_cache_lock = threading.Lock()
HEALTH_CACHE_TTL_SECONDS = 15.0


def invalidate_health_cache(db_path: Optional[str] = None) -> None:
    """Invalidates the health cache for a specific database path or globally if None."""
    global _health_cache
    with _cache_lock:
        if db_path is None:
            _health_cache.clear()
        else:
            canonical = str(Path(db_path).resolve())
            keys_to_del = [k for k in _health_cache if k.startswith(canonical)]
            for k in keys_to_del:
                _health_cache.pop(k, None)


def check_network_connectivity(timeout: float = 0.5) -> bool:
    """Fast check for external network availability with bounded timeout."""
    test_hosts = [("1.1.1.1", 53), ("8.8.8.8", 53), ("1.0.0.1", 53)]
    for host, port in test_hosts:
        try:
            sock = socket.create_connection((host, port), timeout=timeout)
            sock.close()
            return True
        except (socket.timeout, OSError):
            continue
    return False


def check_system_health(
    db: Database,
    config: Optional[Dict[str, Any]] = None,
    now: Optional[datetime] = None,
    use_cache: bool = True,
    checkpoints_map: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Evaluates database integrity, reference folder, network, disk, embedding model,
    and runtime lock to compute system health status: HEALTHY, DEGRADED, or UNHEALTHY.

    Results are cached per (database_path, config_hash) for up to 15.0 seconds.
    """
    if now is None:
        now = datetime.now(timezone.utc)
    if config is None:
        config = load_runtime_config()

    # Determine canonical database identity for cache isolation
    try:
        db_path_str = str(Path(db.db_path).resolve())
    except Exception:
        db_path_str = str(getattr(db, "db_path", "unknown_db"))

    cfg_str = json.dumps(config, sort_keys=True, default=str)
    cfg_hash = hashlib.sha256(cfg_str.encode("utf-8")).hexdigest()[:12]
    cache_key = f"{db_path_str}:{cfg_hash}"

    if use_cache:
        with _cache_lock:
            if cache_key in _health_cache:
                cached_time, cached_val = _health_cache[cache_key]
                age = (now - cached_time).total_seconds()
                if age < HEALTH_CACHE_TTL_SECONDS:
                    res = dict(cached_val)
                    res["observed_at"] = cached_time.isoformat()
                    res["cache_age_seconds"] = round(age, 2)
                    res["is_cached"] = True
                    return res

    min_disk_mb = config.get("min_free_disk_mb", 1024)
    issues = []
    warnings = []

    # 1. Database Writable & Integrity
    db_status = "ok"
    try:
        cursor = db.conn.cursor()
        cursor.execute("PRAGMA quick_check")
        row = cursor.fetchone()
        if not row or row[0] != "ok":
            _, clean_row = sanitize_error(f"quick_check failed: {row}")
            db_status = f"corrupt: {clean_row}"
            issues.append(f"Database quick_check failed: {clean_row}")
    except Exception as e:
        _, clean_err = sanitize_error(e)
        db_status = f"unwritable: {clean_err}"
        issues.append(f"Database unwritable: {clean_err}")

    # 2. Reference Folder Accessible
    ref_path = Path("reference")
    ref_status = "accessible"
    if not ref_path.exists():
        ref_status = "missing"
        warnings.append("Reference folder 'reference/' does not exist")
    elif not os.access(str(ref_path), os.R_OK):
        ref_status = "inaccessible"
        warnings.append("Reference folder 'reference/' is not readable")

    # 3. Network Health (Probe Isolated)
    net_ok = check_network_connectivity(timeout=1.0)
    net_status = "online" if net_ok else "offline"
    if not net_ok:
        warnings.append("Network connection unavailable (offline mode)")

    # 4. Disk Space
    disk_status = "ok"
    free_mb = 0
    try:
        data_dir = Path("data").resolve()
        data_dir.mkdir(parents=True, exist_ok=True)
        usage = shutil.disk_usage(str(data_dir))
        free_mb = int(usage.free / (1024 * 1024))
        if free_mb < min_disk_mb:
            disk_status = f"low_space ({free_mb} MB < {min_disk_mb} MB)"
            warnings.append(f"Free disk space low: {free_mb} MB available")
    except Exception as e:
        _, clean_disk = sanitize_error(e)
        disk_status = f"error: {clean_disk}"

    # 5. Embedding Model Check
    from importlib.util import find_spec
    emb_status = (
        "available"
        if find_spec("sentence_transformers") is not None
        else "missing_dependency"
    )

    if emb_status == "missing_dependency":
        issues.append("sentence_transformers package not available")

    # 6. Runtime Lock & Daemon Heartbeat
    lock_info = SingleInstanceLock().get_lock_info()
    hb_alive, hb_data = is_heartbeat_alive()
    if lock_info and not hb_alive:
        warnings.append("Daemon lock exists but heartbeat is stale")

    # 7. Source Health Summary (Batch Loaded)
    source_health = {}
    try:
        cps_map = checkpoints_map if checkpoints_map is not None else db.get_all_source_checkpoints_map()
        for src, cp in cps_map.items():
            source_health[src] = {
                "health": cp.health_status,
                "fails": cp.consecutive_failures,
                "last_success": cp.last_success_at.isoformat() if cp.last_success_at else None,
                "next_retry": cp.next_retry_at.isoformat() if cp.next_retry_at else None,
                "error_category": cp.last_error_category,
                "sanitized_error": cp.last_error,
            }
            if cp.health_status in ("degraded", "rate_limited"):
                warnings.append(f"Source '{src}' is {cp.health_status} ({cp.consecutive_failures} failures)")
    except Exception:
        pass

    # 8. Compute Overall Status
    if issues or db_status != "ok":
        overall = "UNHEALTHY"
    elif warnings or not net_ok:
        overall = "DEGRADED"
    else:
        overall = "HEALTHY"

    result = {
        "status": overall,
        "database": db_status,
        "reference_folder": ref_status,
        "network": net_status,
        "disk_free_mb": free_mb,
        "disk_status": disk_status,
        "embedding_model": emb_status,
        "daemon_running": hb_alive,
        "daemon_pid": hb_data.get("pid") if hb_data else (lock_info.get("pid") if lock_info else None),
        "source_health": source_health,
        "issues": issues,
        "warnings": warnings,
        "observed_at": now.isoformat(),
        "timestamp": now.isoformat(),
        "cache_age_seconds": 0.0,
        "is_cached": False,
    }

    with _cache_lock:
        _health_cache[cache_key] = (now, result)

    return result


def run_health_cli():
    db = Database()
    health = check_system_health(db)

    print("=" * 65)
    print("HERMES — SYSTEM RUNTIME HEALTH CHECK")
    print("=" * 65)
    print(f"Overall Status:      {health['status']}")
    print(f"Database Integrity:  {health['database']}")
    print(f"Reference Folder:    {health['reference_folder']}")
    print(f"Network Status:      {health['network']}")
    print(f"Embedding Model:     {health['embedding_model']}")
    print(f"Disk Free Space:     {health['disk_free_mb']} MB ({health['disk_status']})")
    print(f"Daemon Running:      {'YES (PID: ' + str(health['daemon_pid']) + ')' if health['daemon_running'] else 'NO'}")

    if health["source_health"]:
        print(f"\nSOURCE STATUS:")
        for src, sdata in health["source_health"].items():
            print(f"  - {src:<20}: {sdata['health'].upper():<12} (Fails: {sdata['fails']})")

    if health["issues"]:
        print(f"\nCRITICAL ISSUES ({len(health['issues'])}):")
        for iss in health["issues"]:
            print(f"  [ERROR] {iss}")

    if health["warnings"]:
        print(f"\nWARNINGS ({len(health['warnings'])}):")
        for w in health["warnings"]:
            print(f"  [WARN] {w}")

    print("=" * 65)
    if health["status"] == "UNHEALTHY":
        sys.exit(1)


if __name__ == "__main__":
    run_health_cli()
