import os
from datetime import datetime, timezone, timedelta
import pytest
from app.storage.db import Database
from app.models.schemas import RefreshOperation

def test_refresh_operations_claiming_and_stale_recovery(tmp_path):
    db_file = str(tmp_path / "test_operations.db")
    db = Database(db_path=db_file)

    # 1. Enqueue refresh operations
    op1 = RefreshOperation(
        id="op1",
        scope="daily_refresh",
        status="queued",
        idempotency_key="key1",
        requested_at=datetime.now(timezone.utc)
    )
    db.save_refresh_operation(op1)

    # Verify enqueued
    saved_op = db.get_refresh_operation("op1")
    assert saved_op is not None
    assert saved_op.status == "queued"

    # 2. Claim operation
    worker_id = "worker-1"
    now = datetime.now(timezone.utc)
    lease_expires = now + timedelta(minutes=5)
    
    claimed = db.claim_refresh_operation("op1", worker_id, now, lease_expires)
    assert claimed is True

    # Double claim should fail
    claimed_again = db.claim_refresh_operation("op1", "worker-2", now, lease_expires)
    assert claimed_again is False

    # Stale operation recovery:
    # Let's create a stale operation
    op2 = RefreshOperation(
        id="op2",
        scope="project_scan",
        status="running",
        worker_id="worker-dead",
        claimed_at=now - timedelta(hours=1),
        lease_expires_at=now - timedelta(minutes=30),
        heartbeat_at=now - timedelta(hours=1),
        requested_at=now - timedelta(hours=1)
    )
    db.save_refresh_operation(op2)

    # Run stale recovery
    recovered_count = db.recover_stale_refresh_operations(now)
    assert recovered_count == 1

    recovered_op = db.get_refresh_operation("op2")
    assert recovered_op.status == "failed"
    assert "lease expired" in recovered_op.error_summary.lower()
