"""Shared pytest fixtures for the HERMES backend test suite.

The autouse fixture below guarantees test isolation for process-global state:
HERMES_DB_PATH / HERMES_LOCK_PATH are restored after every test, so a test that
mutates os.environ directly (without monkeypatch) cannot leak its database path
into subsequent tests.
"""
import os

import pytest


@pytest.fixture(autouse=True)
def _isolate_hermes_env():
    """Snapshot and restore HERMES env vars around every test."""
    keys = ["HERMES_DB_PATH", "HERMES_LOCK_PATH", "HERMES_TEST_INSTANCE_ID"]
    saved = {k: os.environ.get(k) for k in keys}
    yield
    for k, v in saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
