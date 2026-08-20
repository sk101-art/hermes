import os
import shutil
import socket
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from app.runtime.locks import SingleInstanceLock
from app.runtime.state import is_heartbeat_alive, load_runtime_config, read_heartbeat
from app.storage.db import Database

try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def check_network_connectivity(timeout: float = 2.0) -> bool:
    """Fast check for external network availability without heavy HTTP requests."""
    test_hosts = [("1.1.1.1", 53), ("8.8.8.8", 53), ("github.com", 443)]
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
) -> Dict[str, Any]:
    """
    Evaluates database integrity, reference folder, network, disk, embedding model,
    and runtime lock to compute system health status: HEALTHY, DEGRADED, or UNHEALTHY.
    """
    if now is None:
        now = datetime.now(timezone.utc)
    if config is None:
        config = load_runtime_config()

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
            db_status = f"corrupt: {row}"
            issues.append(f"Database quick_check failed: {row}")
    except Exception as e:
        db_status = f"unwritable: {e}"
        issues.append(f"Database unwritable: {e}")

    # 2. Reference Folder Accessible
    ref_path = Path("reference")
    ref_status = "accessible"
    if not ref_path.exists():
        ref_status = "missing"
        warnings.append("Reference folder 'reference/' does not exist")
    elif not os.access(str(ref_path), os.R_OK):
        ref_status = "inaccessible"
        warnings.append("Reference folder 'reference/' is not readable")

    # 3. Network Health
    net_ok = check_network_connectivity()
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
        disk_status = f"error: {e}"

    # 5. Embedding Model Check
    emb_status = "cached"
    try:
        import sentence_transformers
    except ImportError:
        emb_status = "missing_dependency"
        issues.append("sentence_transformers package not importable")

    # 6. Runtime Lock & Daemon Heartbeat
    lock_info = SingleInstanceLock().get_lock_info()
    hb_alive, hb_data = is_heartbeat_alive()
    if lock_info and not hb_alive:
        warnings.append("Daemon lock exists but heartbeat is stale")

    # 7. Source Health Summary
    source_health = {}
    try:
        checkpoints = db.get_all_source_checkpoints()
        for cp in checkpoints:
            source_health[cp.source] = {
                "health": cp.health_status,
                "fails": cp.consecutive_failures,
                "last_success": cp.last_success_at.isoformat() if cp.last_success_at else None,
                "next_retry": cp.next_retry_at.isoformat() if cp.next_retry_at else None,
            }
            if cp.health_status in ("degraded", "rate_limited"):
                warnings.append(f"Source '{cp.source}' is {cp.health_status} ({cp.consecutive_failures} failures)")
    except Exception:
        pass

    # 8. Compute Overall Status
    if issues:
        overall = "UNHEALTHY"
    elif warnings or not net_ok:
        overall = "DEGRADED"
    else:
        overall = "HEALTHY"

    return {
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
        "timestamp": now.isoformat(),
    }


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
