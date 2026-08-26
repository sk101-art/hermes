import os
import shutil
import tempfile
import threading
import time
from datetime import datetime, timezone
import pytest
from fastapi.testclient import TestClient

from app.api.server import app, validate_api_host
from app.api.routes import get_db
from app.models.schemas import Claim, Event, InboxItem, Project, StoryCluster
from app.storage.db import Database


@pytest.fixture
def client_with_db():
    temp_dir = tempfile.mkdtemp()
    db_path = os.path.join(temp_dir, "test_api.db")
    setup_db = Database(db_path=db_path)

    now = datetime.now(timezone.utc)

    # Insert sample data
    ev = Event(
        id="ev_api_1",
        source="github",
        source_type="code_repository",
        event_type="release",
        title="vLLM Inference Engine API",
        text="High-throughput serving for large models",
        url="https://github.com/vllm-project/vllm",
        discovered_at=now,
        final_score=0.90,
    )
    setup_db.save_event(ev)

    cl = StoryCluster(
        id="cluster_api_1",
        canonical_title="vLLM Inference Engine API",
        event_ids=["ev_api_1"],
        sources=["github"],
        cluster_score=0.90,
        source_diversity_score=0.50,
        max_event_score=0.90,
        created_at=now,
        updated_at=now,
    )
    setup_db.save_cluster(cl)

    claim = Claim(
        id="claim_api_1",
        cluster_id="cluster_api_1",
        subject="vLLM",
        predicate="supports",
        object="distributed continuous batching",
        claim_text="vLLM supports distributed continuous batching",
        claim_type="architecture",
        status="supported",
        verification_score=0.85,
    )
    setup_db.save_claim(claim)

    proj = Project(
        id="project:api-test",
        name="api-test-suite",
        path=os.path.join(temp_dir, "api_proj"),
        languages=["Python"],
        frameworks=["FastAPI"],
        libraries=["requests"],
        topics=["api-testing"],
    )
    setup_db.save_project(proj)

    inbox = InboxItem(
        id="inbox_api_1",
        entity_type="cluster",
        entity_id="cluster_api_1",
        story_cluster_id="cluster_api_1",
        title="vLLM Inference Engine API",
        section="ai_ml",
        inbox_score=0.88,
        rank_score=0.90,
        project_impact_score=0.80,
        state="unseen",
        matched_project_ids=["project:api-test"],
    )
    setup_db.save_inbox_item(inbox)

    # Generator dependency override - creates new connection per request, closes after
    def override_get_db():
        request_db = Database(db_path=db_path)
        try:
            yield request_db
        finally:
            request_db.close()

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)

    yield client, setup_db

    app.dependency_overrides.clear()
    setup_db.close()
    shutil.rmtree(temp_dir, ignore_errors=True)


def test_api_health(client_with_db):
    client, _ = client_with_db
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "healthy"
    assert data["database"] == "ok"


def test_api_search(client_with_db):
    client, _ = client_with_db
    resp = client.get("/search?q=vLLM&mode=lexical")
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] >= 1
    assert "vLLM" in data["results"][0]["title"]


def test_api_inbox(client_with_db):
    client, _ = client_with_db
    resp = client.get("/inbox")
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] >= 1
    assert data["inbox_items"][0]["title"] == "vLLM Inference Engine API"


def test_api_stories_and_claims(client_with_db):
    client, _ = client_with_db
    resp_story = client.get("/stories/cluster_api_1")
    assert resp_story.status_code == 200
    assert resp_story.json()["canonical_title"] == "vLLM Inference Engine API"

    resp_claim = client.get("/claims/claim_api_1")
    assert resp_claim.status_code == 200
    assert resp_claim.json()["claim_text"] == "vLLM supports distributed continuous batching"

    # 404 test
    resp_404 = client.get("/stories/unknown_cluster")
    assert resp_404.status_code == 404


def test_api_projects(client_with_db):
    client, _ = client_with_db
    resp = client.get("/projects")
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 1
    assert data["projects"][0]["name"] == "api-test-suite"


def test_api_host_validation():
    # Local hosts are safe
    assert validate_api_host("127.0.0.1") == "127.0.0.1"
    assert validate_api_host("localhost") == "localhost"

    # Non-local host without allow_external is forced to 127.0.0.1
    assert validate_api_host("0.0.0.0", allow_external=False) == "127.0.0.1"
    assert validate_api_host("192.168.1.50", allow_external=False) == "127.0.0.1"

    # Non-local host with allow_external is preserved
    assert validate_api_host("0.0.0.0", allow_external=True) == "0.0.0.0"


def test_concurrent_readers_and_writers_sqlite(client_with_db):
    client, db = client_with_db
    stop_flag = False
    errors = []

    def writer_loop():
        i = 0
        while not stop_flag and i < 20:
            try:
                ev = Event(
                    id=f"ev_conc_{i}",
                    source="github",
                    source_type="code_repository",
                    event_type="commit",
                    title=f"Concurrent Commit {i}",
                    url=f"https://github.com/test/{i}",
                    discovered_at=datetime.now(timezone.utc),
                )
                db.save_event(ev)
                time.sleep(0.01)
                i += 1
            except Exception as e:
                errors.append(f"Writer error: {e}")

    def reader_loop():
        for _ in range(20):
            try:
                resp = client.get("/search?q=Concurrent&mode=lexical")
                assert resp.status_code == 200
                time.sleep(0.01)
            except Exception as e:
                errors.append(f"Reader error: {e}")

    t_writer = threading.Thread(target=writer_loop)
    t_reader = threading.Thread(target=reader_loop)

    t_writer.start()
    t_reader.start()

    t_writer.join()
    stop_flag = True
    t_reader.join()

    assert len(errors) == 0, f"Concurrency errors occurred: {errors}"


def test_projects_endpoints(client_with_db):
    client, db = client_with_db
    now = datetime.now(timezone.utc)

    # 1. Insert Project
    proj = Project(
        id="project:test_compiler",
        name="Test Compiler",
        path="/secret/path/compiler",
        description="A test compiler project",
        languages=["c++", "llvm"],
        frameworks=["mlir"],
        is_active=True,
        last_indexed_at=now,
    )
    db.save_project(proj)

    # 2. GET /projects
    resp = client.get("/projects")
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] >= 1
    p_found = next(p for p in data["projects"] if p["project_id"] == "project:test_compiler")
    assert p_found["name"] == "Test Compiler"
    assert "c++" in p_found["languages"]
    assert "path" not in p_found

    # 3. GET /projects/{id}
    resp_detail = client.get("/projects/project:test_compiler")
    assert resp_detail.status_code == 200
    prof = resp_detail.json()
    assert prof["project_id"] == "project:test_compiler"
    assert prof["name"] == "Test Compiler"
    assert "path" not in prof

    # 4. GET /projects/{id}/intelligence
    resp_intel = client.get("/projects/project:test_compiler/intelligence")
    assert resp_intel.status_code == 200
    intel = resp_intel.json()
    assert intel["project_id"] == "project:test_compiler"
    assert "technology_profile" in intel
    assert "intelligence_available" in intel
    assert "path" not in intel

    # 5. Nonexistent project returns 404
    resp_404 = client.get("/projects/project:nonexistent/intelligence")
    assert resp_404.status_code == 404
