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
    """Guarantee a controlled environment for every test.

    Production precedence is HERMES_DB_PATH > explicit path, so any leaked
    value would silently redirect every Database() call. Each test therefore
    starts with these variables cleared; tests that need them set them
    explicitly (via monkeypatch or direct assignment) and the original
    shell values are restored afterwards.
    """
    keys = ["HERMES_DB_PATH", "HERMES_LOCK_PATH", "HERMES_TEST_INSTANCE_ID"]
    saved = {k: os.environ.get(k) for k in keys}
    for k in keys:
        os.environ.pop(k, None)
    yield
    for k, v in saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
