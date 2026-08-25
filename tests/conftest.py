import os
import tempfile
import pytest
import shutil

@pytest.fixture(scope="session", autouse=True)
def set_temp_db_path():
    temp_dir = tempfile.mkdtemp()
    os.environ["HERMES_DB_PATH"] = os.path.join(temp_dir, "test_hermes.db")
    yield
    try:
        shutil.rmtree(temp_dir)
    except Exception:
        pass

import importlib.util
original_find_spec = importlib.util.find_spec

def mock_find_spec(name, package=None):
    if name == 'sentence_transformers':
        class Dummy: pass
        return Dummy()
    return original_find_spec(name, package)

@pytest.fixture(scope='session', autouse=True)
def mock_sentence_transformers_health():
    importlib.util.find_spec = mock_find_spec
    yield
    importlib.util.find_spec = original_find_spec

