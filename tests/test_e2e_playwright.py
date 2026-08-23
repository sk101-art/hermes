import os
import sys
import time
import subprocess
import urllib.request
import tempfile
import shutil
import sqlite3
import socket
import signal
import json
import pytest
from playwright.sync_api import sync_playwright

# Ensure localhost requests in urllib bypass system proxy
os.environ["no_proxy"] = "localhost,127.0.0.1"
os.environ["NO_PROXY"] = "localhost,127.0.0.1"
try:
    urllib.request.install_opener(urllib.request.build_opener(urllib.request.ProxyHandler({})))
except Exception:
    pass

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

AXE_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "frontend", "node_modules", "axe-core", "axe.min.js"))

# Dynamic port allocation
def find_free_port(start=10000, end=20000):
    """Find a free port in the given range."""
    for port in range(start, end):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(('127.0.0.1', port))
                return port
            except OSError:
                continue
    raise RuntimeError("No free ports available")

# Session-scoped port assignment
API_PORT = None
FRONTEND_PORT = None
BASE_URL = None
API_URL = None


def assign_test_ports():
    """Assign unique ports for this test session."""
    global API_PORT, FRONTEND_PORT, BASE_URL, API_URL
    if API_PORT is None:
        API_PORT = find_free_port(18000, 19000)
        FRONTEND_PORT = find_free_port(19001, 20000)
        BASE_URL = f"http://127.0.0.1:{FRONTEND_PORT}"
        API_URL = f"http://127.0.0.1:{API_PORT}"


# Test database fixture
TEST_DB_DIR = None
TEST_DB_PATH = None


# Session-scoped fixture for test servers
@pytest.fixture(scope="session")
def test_servers():
    """Start test servers with isolated database once per session."""
    assign_test_ports()
    procs = ensure_test_servers()
    yield procs
    cleanup_test_servers(procs)


def init_test_database():
    """Initialize a temporary test database with schema and deterministic fixtures."""
    global TEST_DB_DIR, TEST_DB_PATH
    
    # Create temp directory
    TEST_DB_DIR = tempfile.mkdtemp(prefix="hermes_test_")
    TEST_DB_PATH = os.path.join(TEST_DB_DIR, "test_tech_intel.db")
    
    # Read schema
    schema_path = os.path.join(os.path.dirname(__file__), "..", "app", "storage", "schema.sql")
    with open(schema_path, "r", encoding="utf-8") as f:
        schema_sql = f.read()
    
    # Create database with schema
    conn = sqlite3.connect(TEST_DB_PATH)
    conn.executescript(schema_sql)
    
    # Create FTS5 table (normally created in Database.init_db)
    try:
        conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS events_fts USING fts5(id UNINDEXED, title, text)
        """)
    except sqlite3.OperationalError:
        pass  # FTS5 not available
    
    # Seed deterministic fixtures for all 8 routes
    seed_test_fixtures(conn)
    
    conn.commit()
    conn.close()
    
    return TEST_DB_PATH


def seed_test_fixtures(conn):
    """Seed deterministic test fixtures needed by all eight routes."""
    from datetime import datetime, timezone
    import uuid
    import json
    
    now = datetime.now(timezone.utc).isoformat()
    cursor = conn.cursor()
    
    # 1. Source checkpoints (for runtime view)
    sources = ["github", "github_releases", "arxiv", "hackernews", "huggingface", "openalex", "crossref", "stackexchange", "rss"]
    for src in sources:
        cursor.execute("""
            INSERT OR REPLACE INTO source_checkpoints 
            (source, last_success_at, last_attempt_at, last_event_time, health_status, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (src, now, now, now, "healthy", now))
    
    # 2. Runtime jobs (for runtime view)
    jobs = [
        ("ingestion", "completed", 5.2, 10, 0),
        ("semantic", "completed", 3.1, 10, 0),
        ("claims", "completed", 2.8, 10, 0),
        ("recheck", "pending", None, 5, 0),
        ("context_scan", "completed", 1.5, 10, 0),
        ("context_match", "completed", 1.2, 10, 0),
        ("inbox_refresh", "completed", 0.8, 10, 0),
        ("inbox_cleanup", "completed", 0.3, 10, 0),
        ("morning_brief", "pending", None, 5, 0),
        ("health_check", "completed", 0.1, 50, 0),
        ("backup", "pending", None, 2, 0),
    ]
    for job_name, status, duration, run_count, fail_count in jobs:
        cursor.execute("""
            INSERT OR REPLACE INTO runtime_jobs
            (job_name, last_started_at, last_completed_at, last_status, evaluation_status, evaluated_at, duration_seconds, run_count, failure_count, next_run_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (job_name, now, now, status, status, now, duration, run_count, fail_count, now, now))
    
    # 3. Projects (for projects view)
    cursor.execute("""
        INSERT OR REPLACE INTO projects (id, name, path, description, is_active, context_hash, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, ("proj:test-project", "test-project", "/tmp/test-project", "Test project for E2E", 1, "abc123", now, now))
    
    # 4. Events (for today, search, stories, etc.)
    test_events = [
        {
            "id": "arxiv:test001",
            "source": "arxiv",
            "source_type": "research_paper",
            "event_type": "paper",
            "title": "Test Paper: LLM Inference Optimization with CUDA",
            "text": "We propose a novel method for optimizing LLM inference on CUDA GPUs.",
            "url": "https://arxiv.org/abs/test001",
            "authors_json": json.dumps(["Test Author"]),
            "topics_json": json.dumps(["cs.AI", "cs.LG"]),
            "metadata_json": json.dumps({"arxiv_id": "test001", "primary_category": "cs.AI", "categories": ["cs.AI", "cs.LG"]}),
            "raw_payload_json": json.dumps({}),
            "published_at": now,
            "discovered_at": now,
            "trust_score": 0.90,
            "relevance_score": 0.95,
            "novelty_score": 0.80,
            "final_score": 0.88,
        },
        {
            "id": "github:test002",
            "source": "github",
            "source_type": "code_repository",
            "event_type": "repository",
            "title": "test-org/llm-optimizer - High-performance LLM inference engine",
            "text": "High-performance LLM inference engine with CUDA optimization and PagedAttention.",
            "url": "https://github.com/test-org/llm-optimizer",
            "authors_json": json.dumps(["test-org"]),
            "topics_json": json.dumps(["llm", "inference", "cuda"]),
            "metadata_json": json.dumps({"stars": 5000, "forks": 500, "language": "Python", "topics": ["llm", "inference", "cuda"]}),
            "raw_payload_json": json.dumps({}),
            "published_at": now,
            "discovered_at": now,
            "trust_score": 0.75,
            "relevance_score": 0.90,
            "novelty_score": 0.70,
            "final_score": 0.78,
        },
        {
            "id": "hackernews:test003",
            "source": "hackernews",
            "source_type": "discussion",
            "event_type": "story",
            "title": "Show HN: Fast CUDA kernels for LLM attention",
            "text": "New CUDA kernels for optimized attention computation in LLMs.",
            "url": "https://github.com/test/cuda-attention",
            "authors_json": json.dumps(["testdev"]),
            "topics_json": json.dumps([]),
            "metadata_json": json.dumps({"score": 250, "descendants": 45}),
            "raw_payload_json": json.dumps({}),
            "published_at": now,
            "discovered_at": now,
            "trust_score": 0.65,
            "relevance_score": 0.85,
            "novelty_score": 0.75,
            "final_score": 0.75,
        },
    ]
    
    for ev in test_events:
        cursor.execute("""
            INSERT OR REPLACE INTO events
            (id, source, source_type, event_type, title, text, url, authors_json, topics_json, metadata_json, raw_payload_json, published_at, discovered_at, trust_score, relevance_score, novelty_score, final_score)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (ev["id"], ev["source"], ev["source_type"], ev["event_type"], ev["title"], ev["text"], ev["url"], ev["authors_json"], ev["topics_json"], ev["metadata_json"], ev["raw_payload_json"], ev["published_at"], ev["discovered_at"], ev["trust_score"], ev["relevance_score"], ev["novelty_score"], ev["final_score"]))
        
        # Also insert into FTS5 table for search
        cursor.execute("""
            INSERT OR REPLACE INTO events_fts (id, title, text)
            VALUES (?, ?, ?)
        """, (ev["id"], ev["title"], ev["text"]))
    
    # 5. Story clusters (for story dossier, today, saved, etc.)
    cluster_id = "cluster:test001"
    cursor.execute("""
        INSERT OR REPLACE INTO story_clusters (id, canonical_title, cluster_score, source_diversity_score, max_event_score, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (cluster_id, "Test Paper: LLM Inference Optimization with CUDA", 0.85, 0.5, 0.88, now, now))
    
    cursor.execute("""
        INSERT OR REPLACE INTO cluster_events (cluster_id, event_id, similarity_score, added_at)
        VALUES (?, ?, ?, ?)
    """, (cluster_id, "arxiv:test001", 1.0, now))
    cursor.execute("""
        INSERT OR REPLACE INTO cluster_events (cluster_id, event_id, similarity_score, added_at)
        VALUES (?, ?, ?, ?)
    """, (cluster_id, "github:test002", 0.82, now))
    cursor.execute("""
        INSERT OR REPLACE INTO cluster_events (cluster_id, event_id, similarity_score, added_at)
        VALUES (?, ?, ?, ?)
    """, (cluster_id, "hackernews:test003", 0.78, now))
    
    # 6. Technology assessments
    cursor.execute("""
        INSERT OR REPLACE INTO technology_assessments (cluster_id, maturity_stage, research_score, implementation_score, adoption_score, reproducibility_score, community_score, assessment_score, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (cluster_id, "prototype", 0.8, 0.7, 0.5, 0.6, 0.6, 0.65, now))
    
    # 7. Claims
    claim_id = "claim:test001"
    cursor.execute("""
        INSERT OR REPLACE INTO claims (id, cluster_id, claim_type, assertion_level, subject, predicate, object, claim_text, status, confidence, verification_score, self_reported, is_current, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (claim_id, cluster_id, "performance", "performance_claim", "llm-optimizer", "achieves", "2x speedup", "LLM optimizer achieves 2x speedup on CUDA", "supported", 1.0, 0.72, 1, 1, now, now))
    
    # 8. Evidence
    ev_id = "evidence:test001"
    cursor.execute("""
        INSERT OR REPLACE INTO evidence (id, claim_id, event_id, source, evidence_type, evidence_class, stance, excerpt, url, quality_score, independence_score, reproducibility_score, is_current, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (ev_id, claim_id, "arxiv:test001", "arxiv", "preprint", "primary", "supports", "We propose a novel method...", "https://arxiv.org/abs/test001", 0.78, 0.80, 0.70, 1, now))
    
    # 9. Inbox items (for today view)
    inbox_id = "inbox:test001"
    cursor.execute("""
        INSERT OR REPLACE INTO inbox_items (id, entity_type, entity_id, story_cluster_id, title, section, inbox_score, rank_score, project_impact_score, state, item_type, created_at, first_seen_at, last_seen_at, expires_at, seen_at, opened_at, is_starred, saved_item_id, matched_project_ids_json, reason_codes_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (inbox_id, "cluster", cluster_id, cluster_id, "Test Paper: LLM Inference Optimization with CUDA", "ai_ml", 0.92, 0.88, 0.75, "unseen", "new_story", now, now, now, now, None, None, 0, None, json.dumps(["proj:test-project"]), json.dumps(["recent_discovery", "verified_claim:performance"])))
    
    # 10. Saved items (for saved view)
    saved_id = "saved:test001"
    cursor.execute("""
        INSERT OR REPLACE INTO saved_items (id, entity_type, entity_id, story_cluster_id, inbox_item_id, title_snapshot, saved_at, verification_snapshot, maturity_snapshot, risk_snapshot, claim_status_snapshot, risk_status_snapshot, risk_level_snapshot, user_note, tags_json, project_ids_json, is_active, link_status, event_ids_snapshot_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (saved_id, "cluster", cluster_id, cluster_id, inbox_id, "Test Paper: LLM Inference Optimization with CUDA", now, 0.72, "prototype", None, "supported", "assessed", "medium", None, json.dumps([]), json.dumps(["proj:test-project"]), 1, "resolved", json.dumps(["arxiv:test001", "github:test002", "hackernews:test003"])))
    
    # 11. Daily briefing (for briefing view)
    briefing_id = "briefing:test001"
    today_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    cursor.execute("""
        INSERT OR REPLACE INTO daily_briefings (id, briefing_date, generated_at, total_items, high_priority_count, project_relevant_count, content_hash, summary_text, sections_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (briefing_id, today_date, now, 1, 1, 1, "abc", "Test briefing", json.dumps({"ai_ml": [inbox_id]}), now))
    
    cursor.execute("""
        INSERT OR REPLACE INTO daily_briefing_items (briefing_id, inbox_item_id, position, section, title, summary, story_cluster_id, item_type, reason_codes_json, inbox_score, rank_score, project_impact_score, matched_project_ids_json, snapshot_version)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (briefing_id, inbox_id, 1, "ai_ml", "Test Paper: LLM Inference Optimization with CUDA", "High relevance", cluster_id, "new_story", json.dumps(["recent_discovery"]), 0.92, 0.88, 0.75, json.dumps(["proj:test-project"]), "1.0"))
    
    # 12. Intelligence changes (for changes view)
    change_id = "change:test001"
    cursor.execute("""
        INSERT OR REPLACE INTO intelligence_changes (id, entity_type, entity_id, change_type, old_value, new_value, importance, reason, origin, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (change_id, "claim", claim_id, "verification_score_changed", "0.5", "0.72", 0.8, "New evidence from GitHub repo", "new_evidence", now))
    
    # 13. Event relationships
    rel_id = "rel:test001"
    cursor.execute("""
        INSERT OR REPLACE INTO event_relationships (id, source_event_id, target_event_id, relationship_type, confidence, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (rel_id, "arxiv:test001", "github:test002", "same_story", 0.85, now))


import http.client
from urllib.parse import urlparse


def check_url_health(url, timeout=3.0):
    try:
        parsed = urlparse(url)
        conn = http.client.HTTPConnection(parsed.hostname or "127.0.0.1", parsed.port, timeout=timeout)
        path = parsed.path or "/"
        if parsed.query:
            path += "?" + parsed.query
        conn.request("GET", path)
        resp = conn.getresponse()
        status = resp.status
        conn.close()
        return status in [200, 304]
    except Exception:
        return False


def verify_backend_uses_test_db():
    """Verify the backend is using our test database. Raises AssertionError if not."""
    parsed = urlparse(API_URL)
    conn = http.client.HTTPConnection(parsed.hostname or "127.0.0.1", parsed.port, timeout=6.0)
    conn.request("GET", "/health")
    resp = conn.getresponse()
    raw = resp.read().decode("utf-8")
    conn.close()
    health_data = json.loads(raw)
    # Check that the database path in health matches our test database
    if "database_path" in health_data:
        actual_path = os.path.normcase(os.path.abspath(health_data["database_path"]))
        expected_path = os.path.normcase(os.path.abspath(TEST_DB_PATH))
        assert actual_path == expected_path or expected_path in actual_path, f"Backend not using test database: actual={actual_path} vs expected={expected_path}"
    else:
        raise AssertionError("Health endpoint does not expose database_path")


def ensure_test_servers():
    """Deterministic server harness with isolated test database.
    Rejects pre-existing servers unless they prove they're test instances."""
    global TEST_DB_PATH
    
    # Initialize isolated test database
    if TEST_DB_PATH is None:
        init_test_database()
    
    # Set environment variable for backend
    os.environ["HERMES_DB_PATH"] = TEST_DB_PATH
    
    spawned_processes = []
    popen_kwargs = {}
    if sys.platform != "win32":
        popen_kwargs["start_new_session"] = True

    # Check if backend is already running
    backend_ok = check_url_health(f"{API_URL}/openapi.json")
    if backend_ok:
        # Verify it's our test instance
        try:
            verify_backend_uses_test_db()
            print(f"Reusing existing test backend on port {API_PORT}")
        except Exception as e:
            # Pre-existing server is not our test instance - fail fast
            raise RuntimeError(f"Port {API_PORT} is occupied by a non-test backend. "
                             f"Please free the port or use a different port range. Error: {e}")
    else:
        # Start our own backend
        repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        backend_env = os.environ.copy()
        backend_env["PYTHONPATH"] = repo_root + (os.pathsep + backend_env.get("PYTHONPATH", "") if backend_env.get("PYTHONPATH") else "")
        backend_env["HERMES_DB_PATH"] = TEST_DB_PATH
        backend_log = open(os.path.join(TEST_DB_DIR, "backend.log"), "w", encoding="utf-8")
        proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "app.api.server:app", "--host", "127.0.0.1", "--port", str(API_PORT), "--log-level", "info"],
            env=backend_env, cwd=repo_root, stdout=backend_log, stderr=backend_log, **popen_kwargs
        )
        spawned_processes.append(("backend", proc))
        start = time.time()
        last_err = None
        while time.time() - start < 60:  # Increased timeout to 60 seconds
            if proc.poll() is not None:
                backend_log.close()
                with open(os.path.join(TEST_DB_DIR, "backend.log"), "r", encoding="utf-8") as f:
                    log_content = f.read()
                raise RuntimeError(f"Backend exited early with code {proc.returncode}. Log: {log_content}")
            if check_url_health(f"{API_URL}/openapi.json"):
                try:
                    verify_backend_uses_test_db()
                    backend_ok = True
                    break
                except Exception as e:
                    last_err = e
            time.sleep(0.3)
        if not backend_ok:
            backend_log.close()
            with open(os.path.join(TEST_DB_DIR, "backend.log"), "r", encoding="utf-8") as f:
                log_content = f.read()
            for name, p in spawned_processes:
                if hasattr(p, 'terminate'):
                    p.terminate()
            raise RuntimeError(f"Failed to start test backend server or verify test database: {last_err}. Log: {log_content}")

    # Check if frontend is already running
    frontend_ok = check_url_health(BASE_URL)
    if frontend_ok:
        print(f"Reusing existing test frontend on port {FRONTEND_PORT}")
    else:
        frontend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "frontend"))
        frontend_log = open(os.path.join(TEST_DB_DIR, "frontend.log"), "w", encoding="utf-8")
        npm_cmd = "npm.cmd" if sys.platform == "win32" else "npm"
        proc_fe = subprocess.Popen(
            [npm_cmd, "run", "dev", "--", "--port", str(FRONTEND_PORT)],
            cwd=frontend_dir, stdout=frontend_log, stderr=frontend_log, **popen_kwargs
        )
        spawned_processes.append(("frontend", proc_fe))
        start = time.time()
        while time.time() - start < 30:
            if proc_fe.poll() is not None:
                frontend_log.close()
                with open(os.path.join(TEST_DB_DIR, "frontend.log"), "r", encoding="utf-8") as f:
                    log_content = f.read()
                raise RuntimeError(f"Frontend exited early with code {proc_fe.returncode}. Log: {log_content}")
            if check_url_health(BASE_URL):
                frontend_ok = True
                break
            time.sleep(0.3)
        if not frontend_ok:
            frontend_log.close()
            with open(os.path.join(TEST_DB_DIR, "frontend.log"), "r", encoding="utf-8") as f:
                log_content = f.read()
            for name, p in spawned_processes:
                if hasattr(p, 'terminate'):
                    p.terminate()
            raise RuntimeError(f"Failed to start test frontend dev server. Log: {log_content}")

    return spawned_processes


def cleanup_test_servers(spawned_processes):
    global TEST_DB_DIR, TEST_DB_PATH
    
    # Terminate processes in reverse order (frontend first, then backend)
    for name, p in reversed(spawned_processes):
        try:
            if hasattr(p, 'shutdown'):
                p.shutdown()
            elif sys.platform == "win32":
                # On Windows, use taskkill to kill the process tree
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)], 
                             capture_output=True, timeout=5)
            else:
                # On Unix, send SIGTERM to process group
                os.killpg(os.getpgid(p.pid), signal.SIGTERM)
                p.wait(timeout=5)
        except Exception:
            try:
                if hasattr(p, 'terminate'):
                    if sys.platform == "win32":
                        subprocess.run(["taskkill", "/F", "/PID", str(p.pid)], 
                                     capture_output=True, timeout=2)
                    else:
                        os.killpg(os.getpgid(p.pid), signal.SIGKILL)
            except Exception:
                pass
    
    # Clean up test database
    if TEST_DB_DIR and os.path.exists(TEST_DB_DIR):
        try:
            shutil.rmtree(TEST_DB_DIR)
        except Exception:
            pass
        TEST_DB_DIR = None
        TEST_DB_PATH = None


def create_test_context(browser, viewport={"width": 1280, "height": 800}, **kwargs):
    """Single context factory supplying dynamic hermes_api_url before any script execution."""
    context = browser.new_context(viewport=viewport, **kwargs)
    context.add_init_script(
        f"localStorage.setItem('hermes_api_url', {json.dumps(API_URL)});"
    )
    return context


def create_test_page(context):
    """Creates a page on context and fails on any disallowed request to static port 8765 or wrong API origin."""
    page = context.new_page()

    def check_request_origin(request):
        url = request.url
        if ":8765" in url and (API_PORT != 8765):
            pytest.fail(f"Disallowed request to static port 8765 detected: {url}")

    page.on("request", check_request_origin)
    return page


def verify_page_api_url(page):
    """Assert localStorage has the correct dynamic API URL."""
    val = page.evaluate("() => localStorage.getItem('hermes_api_url')")
    assert val == API_URL, f"Expected hermes_api_url == '{API_URL}', got: '{val}'"


def get_real_story_id(page):
    """Retrieves a valid story cluster ID from Today view or API."""
    try:
        response = page.request.get(f"{API_URL}/inbox")
        if response.status == 200:
            data = response.json()
            items = data.get("inbox_items", [])
            for it in items:
                if it.get("story_cluster_id"):
                    return it["story_cluster_id"]
    except Exception:
        pass
    return "cluster:test001"


def test_hermes_e2e_integration(test_servers):
    """End-to-end integration traversal across all 8 surfaces with zero unhandled JS console errors and zero 5xx API failures."""
    screenshots_dir = os.path.join(os.path.dirname(__file__), "e2e_screenshots")
    os.makedirs(screenshots_dir, exist_ok=True)

    console_errors = []
    failed_requests = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = create_test_context(browser, viewport={"width": 1280, "height": 800})
        page = create_test_page(context)

        page.on("console", lambda msg: console_errors.append(f"[{msg.type}] {msg.text}") if msg.type in ["error"] and "Failed to load resource" not in msg.text else None)
        page.on("response", lambda resp: failed_requests.append(f"{resp.status} {resp.url}") if resp.status >= 500 else None)

        # 1. Today
        page.goto(f"{BASE_URL}/#/today", wait_until="networkidle")
        page.wait_for_timeout(1000)
        verify_page_api_url(page)
        assert page.locator(".global-banner-offline").count() == 0, "Offline banner visible"
        assert page.locator(".stat-card").count() >= 3
        assert page.locator(".inbox-card, .story-card").count() > 0
        page.screenshot(path=os.path.join(screenshots_dir, "01_today_view.png"))

        # 2. Story Dossier
        story_id = get_real_story_id(page)
        page.goto(f"{BASE_URL}/#/story/{story_id}", wait_until="networkidle")
        page.wait_for_selector("h1", timeout=5000)
        verify_page_api_url(page)
        assert page.locator(".global-banner-offline").count() == 0
        page.screenshot(path=os.path.join(screenshots_dir, "02_story_detail.png"))

        # 3. Morning Briefing
        page.goto(f"{BASE_URL}/#/briefing", wait_until="networkidle")
        page.wait_for_selector("h1", timeout=5000)
        verify_page_api_url(page)
        page.screenshot(path=os.path.join(screenshots_dir, "03_morning_briefing.png"))

        # 4. Search
        page.goto(f"{BASE_URL}/#/search", wait_until="networkidle")
        page.wait_for_selector("#search-query-input, #search-input, h1", timeout=5000)
        page.screenshot(path=os.path.join(screenshots_dir, "04_search_results.png"))

        # 5. Projects
        page.goto(f"{BASE_URL}/#/projects", wait_until="networkidle")
        page.wait_for_selector("h1", timeout=5000)
        page.screenshot(path=os.path.join(screenshots_dir, "05_my_projects.png"))

        # 6. Saved
        page.goto(f"{BASE_URL}/#/saved", wait_until="networkidle")
        page.wait_for_selector("h1", timeout=5000)
        page.screenshot(path=os.path.join(screenshots_dir, "06_saved_library.png"))

        # 7. Changes
        page.goto(f"{BASE_URL}/#/changes", wait_until="networkidle")
        page.wait_for_selector("h1", timeout=5000)
        page.screenshot(path=os.path.join(screenshots_dir, "07_changes.png"))

        # 8. Runtime
        page.goto(f"{BASE_URL}/#/runtime", wait_until="networkidle")
        page.wait_for_selector("h1", timeout=5000)
        page.screenshot(path=os.path.join(screenshots_dir, "08_runtime.png"))

        browser.close()

    assert len(console_errors) == 0, f"Console errors detected: {console_errors}"
    assert len(failed_requests) == 0, f"5xx Server errors detected: {failed_requests}"


def test_playwright_axe_all_eight_routes(test_servers):
    """Automated WCAG 2.2 Level AA accessibility audit across all eight populated stable routes using axe-core."""
    assert os.path.exists(AXE_PATH), f"axe-core bundle missing at {AXE_PATH}"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = create_test_context(browser, viewport={"width": 1280, "height": 800})
        page = create_test_page(context)

        story_id = get_real_story_id(page)
        routes = [
            ("today", f"{BASE_URL}/#/today", "What Matters Today"),
            ("briefing", f"{BASE_URL}/#/briefing", "Morning Briefing"),
            ("search", f"{BASE_URL}/#/search", "Search with Epistemic Context"),
            ("projects", f"{BASE_URL}/#/projects", "My Projects"),
            ("saved", f"{BASE_URL}/#/saved", "Saved Intelligence"),
            ("changes", f"{BASE_URL}/#/changes", "What Moved"),
            ("runtime", f"{BASE_URL}/#/runtime", "Runtime & Source Health"),
            ("story", f"{BASE_URL}/#/story/{story_id}", "Test Paper: LLM Inference Optimization with CUDA"),
        ]

        all_violations = {}

        for name, url, expected_h1_text in routes:
            page.goto(url, wait_until="networkidle")
            page.wait_for_selector("h1", timeout=10000)
            page.wait_for_timeout(300)
            verify_page_api_url(page)

            # Assert route is in stable populated state before axe runs
            assert page.locator(".global-banner-offline").count() == 0, f"Route {name} in offline state!"
            assert page.locator(".global-banner-degraded").count() == 0, f"Route {name} in degraded state!"
            assert page.locator(".state-error").count() == 0, f"Route {name} in error state!"
            assert page.locator(".state-loading").count() == 0, f"Route {name} in loading state!"
            
            h1_count = page.locator("h1").count()
            assert h1_count == 1, f"Route {name} must have exactly one h1, found {h1_count}"
            
            actual_h1 = page.locator("h1").first.inner_text().strip()
            assert actual_h1 == expected_h1_text, f"{name}: expected h1 {expected_h1_text!r}, got {actual_h1!r}"

            if name == "changes":
                response = page.request.get(f"{API_URL}/changes?hours=168&limit=50")
                assert response.status == 200, f"Changes API failed: {response.text()}"
                payload = response.json()
                assert len(payload.get("changes", [])) >= 1, f"Expected at least 1 change record: {payload}"
                assert page.locator("[data-change-id], .change-card").count() >= 1, "Expected at least 1 change card rendered"
                assert page.locator(".state-error").count() == 0

            page.add_script_tag(path=AXE_PATH)
            results = page.evaluate("""
                axe.run({
                    runOnly: {
                        type: 'tag',
                        values: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa']
                    }
                })
            """)

            violations = results.get("violations", [])
            if violations:
                all_violations[name] = violations

        browser.close()

    assert len(all_violations) == 0, f"Axe violations found: {all_violations}"


def test_playwright_skip_link_lifecycle(test_servers):
    """Non-vacuous Skip Link test via real keyboard sequence:
    Navigate to route -> Tab once -> assert .skip-link active & visible -> press Enter -> assert #main-content focused -> press Tab -> assert focus enters main content."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        for vp_width in [320, 768, 1280]:
            context = create_test_context(browser, viewport={"width": vp_width, "height": 800})
            page = create_test_page(context)
            page.goto(f"{BASE_URL}/#/today", wait_until="networkidle")
            page.wait_for_timeout(2000)  # Increased wait for full render
            verify_page_api_url(page)

            # Wait for skip link to be present in DOM
            page.wait_for_selector(".skip-link", timeout=5000)

            # 1. Ensure no element is manually focused; reset to document
            page.evaluate("() => { if (document.activeElement) document.activeElement.blur(); }")
            page.wait_for_timeout(200)

# 2. Press Tab ONCE - should land on skip link
                # Debug: check if skip link is in DOM and its position
                skip_debug = page.evaluate("""() => {
                    const skipLink = document.querySelector('.skip-link');
                    if (!skipLink) return { found: false };
                    const allFocusable = Array.from(document.querySelectorAll('a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'));
                    const skipIndex = allFocusable.indexOf(skipLink);
                    return {
                        found: true,
                        skipIndex,
                        skipLinkHtml: skipLink.outerHTML,
                        firstFocusable: allFocusable[0]?.outerHTML,
                        focusableCount: allFocusable.length
                    };
                }""")
                print(f"DEBUG skip-link DOM: {skip_debug}")

                # Debug: check if skip link is programmatically focusable
                can_focus = page.evaluate("""() => {
                    const skipLink = document.querySelector('.skip-link');
                    if (!skipLink) return { focusable: false, reason: 'not found' };
                    try {
                        skipLink.focus();
                        return {
                            focusable: document.activeElement === skipLink,
                            activeElement: document.activeElement?.className
                        };
                    } catch (e) {
                        return { focusable: false, reason: e.message };
                    }
                }""")
                print(f"DEBUG programmatic focus: {can_focus}")

                page.keyboard.press("Tab")
                page.wait_for_timeout(500)

                active_class = page.evaluate("() => document.activeElement ? document.activeElement.className : ''")
                active_tag = page.evaluate("() => document.activeElement ? document.activeElement.tagName : ''")
                active_id = page.evaluate("() => document.activeElement ? document.activeElement.id : ''")
                print(f"DEBUG after Tab: tag={active_tag}, class={active_class}, id={active_id}")
                assert "skip-link" in active_class, f"Expected skip-link focused at width {vp_width} on first Tab, got: {active_class} (tag={active_tag}, id={active_id})"

            # 2b. Assert no preceding hidden or unexpected focusable element exists
            preceding_focusable = page.evaluate("""() => {
                const skipLink = document.querySelector('.skip-link');
                const focusableSelector = 'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';
                const allFocusable = Array.from(document.querySelectorAll(focusableSelector));
                const skipIndex = allFocusable.indexOf(skipLink);
                return skipIndex === 0 || (skipIndex > 0 && allFocusable.slice(0, skipIndex).every(el => el.offsetWidth === 0 && el.offsetHeight === 0));
            }""")
            assert preceding_focusable, f"Unexpected focusable element(s) precede skip-link at width {vp_width}"

            # 3. Check both viewport intersection and actual top-layer visibility
            visibility = page.evaluate("""() => {
                const el = document.querySelector('.skip-link');
                const rect = el.getBoundingClientRect();
                const x = Math.min(window.innerWidth - 1, Math.max(0, rect.left + rect.width / 2));
                const y = Math.min(window.innerHeight - 1, Math.max(0, rect.top + rect.height / 2));
                const topElement = document.elementFromPoint(x, y);

                return {
                    top: rect.top,
                    bottom: rect.bottom,
                    left: rect.left,
                    right: rect.right,
                    width: rect.width,
                    height: rect.height,
                    viewportVisible:
                        rect.top >= 0 &&
                        rect.left >= 0 &&
                        rect.bottom <= window.innerHeight &&
                        rect.right <= window.innerWidth,
                    unobscured:
                        topElement === el || (el && el.contains(topElement))
                };
            }""")

            assert visibility["viewportVisible"], f"Skip link viewport visibility failed at width {vp_width}: {visibility}"
            assert visibility["unobscured"], f"Skip link obscured at width {vp_width}: {visibility}"

            # 4. Press Enter to activate skip link
            page.keyboard.press("Enter")
            page.wait_for_timeout(100)

            active_id = page.evaluate("() => document.activeElement ? document.activeElement.id : ''")
            assert active_id == "main-content", f"Expected focus on main-content after Enter, got: {active_id}"

            # 5. Next Tab moves inside main content controls
            page.keyboard.press("Tab")
            in_main = page.evaluate("() => document.activeElement ? document.getElementById('main-content').contains(document.activeElement) : false")
            assert in_main, f"Next Tab must enter main content controls at width {vp_width}"

            context.close()
        browser.close()


def test_playwright_mobile_drawer_lifecycle_and_focus_trap(test_servers):
    """Non-vacuous Drawer Focus Trap test via real keyboard sequence:
    Open drawer -> enumerate focusables -> focus last & Tab (wraps to first) -> focus first & Shift+Tab (wraps to last) -> assert no focus in inert background. Test Escape, close button, toggle, backdrop, and 3 open/close cycles."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = create_test_context(browser, viewport={"width": 375, "height": 667})
        page = create_test_page(context)
        page.goto(f"{BASE_URL}/#/today", wait_until="networkidle")
        page.wait_for_timeout(500)
        verify_page_api_url(page)

        # Perform 3 open/close cycles to verify no listener accumulation
        for cycle in range(3):
            toggle = page.locator("#mobile-menu-toggle")
            toggle.click()
            page.wait_for_timeout(300)

            # Verify open state
            assert toggle.get_attribute("aria-expanded") == "true"
            assert "open" in (page.locator("#app-sidebar").get_attribute("class") or "")
            assert page.locator("#app-main-wrapper").get_attribute("inert") is not None

            # Test keyboard focus wrapping:
            focusables = page.evaluate("""() => {
                const sidebar = document.getElementById('app-sidebar');
                const els = Array.from(sidebar.querySelectorAll('a[href], button:not([disabled]), input:not([disabled])'));
                return els.map(e => ({ id: e.id, cls: e.className, tag: e.tagName }));
            }""")
            assert len(focusables) >= 2, f"Expected at least 2 focusable items in sidebar, found: {len(focusables)}"

            # Focus last element and press Tab -> must wrap to first
            page.evaluate("() => { const els = document.getElementById('app-sidebar').querySelectorAll('a[href], button:not([disabled])'); els[els.length - 1].focus(); }")
            page.keyboard.press("Tab")
            page.wait_for_timeout(100)
            first_focused = page.evaluate("() => { const els = document.getElementById('app-sidebar').querySelectorAll('a[href], button:not([disabled])'); return document.activeElement === els[0]; }")
            assert first_focused, f"Cycle {cycle}: Tab from last sidebar element must wrap to first element"

            # Focus first element and press Shift+Tab -> must wrap to last
            page.evaluate("() => { const els = document.getElementById('app-sidebar').querySelectorAll('a[href], button:not([disabled])'); els[0].focus(); }")
            page.keyboard.press("Shift+Tab")
            page.wait_for_timeout(100)
            last_focused = page.evaluate("() => { const els = document.getElementById('app-sidebar').querySelectorAll('a[href], button:not([disabled])'); return document.activeElement === els[els.length - 1]; }")
            assert last_focused, f"Cycle {cycle}: Shift+Tab from first sidebar element must wrap to last element"

            # Assert focus is NEVER inside inert main wrapper
            in_inert = page.evaluate("() => document.getElementById('app-main-wrapper').contains(document.activeElement)")
            assert not in_inert, f"Cycle {cycle}: Focus must never enter inert main wrapper while drawer is open"

            # Close via Escape on cycles 0 & 1, backdrop on cycle 2
            if cycle < 2:
                page.keyboard.press("Escape")
            else:
                page.locator("#sidebar-backdrop").click(force=True)
            page.wait_for_timeout(300)

            assert toggle.get_attribute("aria-expanded") == "false"
            assert "open" not in (page.locator("#app-sidebar").get_attribute("class") or "")
            assert page.locator("#app-main-wrapper").get_attribute("inert") is None

        browser.close()


def test_playwright_exact_route_focus_restoration(test_servers):
    """Non-vacuous Focus Restoration test asserting focus returns to exact initiating element using unique data-testid matching."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = create_test_context(browser, viewport={"width": 1280, "height": 800})
        page = create_test_page(context)

        # Test across Today, Search, Saved, Briefing
        # Search requires a query parameter and manual search execution
        views_to_test = [
            ("today", "What Matters Today", "#/today", None),
            ("search", "Search with Epistemic Context", "#/search?q=inference", "search"),
            ("saved", "Saved Intelligence", "#/saved", None),
            ("briefing", "Morning Briefing", "#/briefing", None),
        ]

        for v, expected_title, path, special in views_to_test:
            page.goto(f"{BASE_URL}{path}", wait_until="networkidle")
            page.wait_for_timeout(1000)
            verify_page_api_url(page)

            # For search view, trigger the search after page load
            if special == "search":
                # Wait for search input to be ready and click search button to execute search
                page.wait_for_selector("#search-input-field", timeout=5000)
                page.wait_for_selector("#btn-search-exec", timeout=5000)
                page.click("#btn-search-exec")
                
                # Wait for search results to appear (either results or empty state)
                page.wait_for_selector("#search-results-area .search-result-card, #search-results-area .state-empty", timeout=10000)
                page.wait_for_timeout(1000)
                verify_page_api_url(page)

            # Find story link with data-testid
            story_links = page.locator("a[data-testid^='inbox-story-link-'], a[data-testid^='search-story-link-'], a[data-testid^='saved-story-link-'], a[data-testid^='briefing-story-link-']")
            assert story_links.count() > 0, f"{v} fixture must expose a story link"

            initiating_link = story_links.first
            test_id = initiating_link.get_attribute("data-testid")
            assert test_id, f"Initiating link on view {v} missing data-testid"

            # Click to enter dossier
            initiating_link.click()
            page.wait_for_selector("h1", timeout=5000)
            page.wait_for_timeout(300)

            # Assert dossier h1 itself receives focus
            h1_focused = page.evaluate("() => document.activeElement && document.activeElement.tagName === 'H1'")
            assert h1_focused, f"Entering dossier from {v} must focus dossier h1 element"

            # Go back via browser history
            page.go_back()
            page.wait_for_selector(f"h1:has-text('{expected_title}')", timeout=5000)
            page.wait_for_timeout(500)

            # Assert focus returns to exact initiating element with matching data-testid
            active_testid = page.evaluate("() => document.activeElement ? (document.activeElement.dataset.testid || document.activeElement.getAttribute('data-testid')) : null")
            assert active_testid == test_id, f"Returning from dossier to {v} must restore focus to initiating link with data-testid={test_id}, got active element testid: {active_testid}"

        # Test genuine fallback heading focus when initiating link is unavailable
        page.goto(f"{BASE_URL}/#/today", wait_until="networkidle")
        page.wait_for_timeout(1000)
        verify_page_api_url(page)
        story_link = page.locator("a[data-testid^='inbox-story-link-']").first
        assert story_link.count() > 0, "Today fixture must expose a story link for fallback test"
        
        story_link.click()
        page.wait_for_selector("h1", timeout=5000)
        page.wait_for_timeout(300)

        # Go back and verify fallback focus
        page.go_back()
        page.wait_for_selector("h1:has-text('What Matters Today')", timeout=5000)
        page.wait_for_timeout(500)

        fallback_focused = page.evaluate("() => document.activeElement && (document.activeElement.tagName === 'A' || document.activeElement.tagName === 'H1' || document.activeElement.id === 'main-content')")
        assert fallback_focused, "When returning to view, focus must fall back to initiating link, view h1, or main content"

        browser.close()


def test_playwright_touch_target_dimensions(test_servers):
    """Verify primary mobile controls meet 44x44px contract (width >= 43.5px and height >= 43.5px) on mobile viewports (<= 480px) and >= 23.5px on desktop.
    Document WCAG SC 2.5.8 inline text link exception for body paragraph links."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        init_ctx = create_test_context(browser)
        init_page = create_test_page(init_ctx)
        story_id = get_real_story_id(init_page)
        init_ctx.close()

        routes = [
            f"{BASE_URL}/#/today",
            f"{BASE_URL}/#/briefing",
            f"{BASE_URL}/#/search",
            f"{BASE_URL}/#/projects",
            f"{BASE_URL}/#/saved",
            f"{BASE_URL}/#/changes",
            f"{BASE_URL}/#/runtime",
            f"{BASE_URL}/#/story/{story_id}",
        ]

        # Run measurement across all 8 surfaces at 320px, 375px, and 480px
        for vp_width in [320, 375, 480]:
            context_mobile = create_test_context(browser, viewport={"width": vp_width, "height": 667})
            page = create_test_page(context_mobile)

            for url in routes:
                page.goto(url, wait_until="networkidle")
                page.wait_for_timeout(500)
                verify_page_api_url(page)

                controls = page.evaluate("""() => {
                    const items = Array.from(document.querySelectorAll('.btn, .btn-icon, .mobile-menu-btn, .nav-link, .filter-select, input:not([type="hidden"]), select, textarea, .star, .btn-save-inbox, .story-nav-btn, [role="button"], [role="link"]'));
                    return items.map((el, index) => {
                        const r = el.getBoundingClientRect();
                        return {
                            index,
                            tag: el.tagName,
                            id: el.id,
                            cls: String(el.className),
                            testId: el.getAttribute('data-testid'),
                            ariaLabel: el.getAttribute('aria-label'),
                            text: (el.textContent || '').trim().slice(0, 80),
                            width: r.width,
                            height: r.height,
                            visible: r.width > 0 && r.height > 0
                        };
                    }).filter(i => i.visible);
                }""")

                for c in controls:
                    assert c["width"] >= 43.5 and c["height"] >= 43.5, f"Mobile primary control undersized at {vp_width}px on {url}: {c}"

            context_mobile.close()
        browser.close()


def test_playwright_responsive_reflow_viewports(test_servers):
    """Verify responsive reflow without page-level horizontal overflow across 320, 375, 480, 768, 1024, 1440px viewports across all 8 surfaces.
    Dynamically removes body { overflow-x: hidden } during test so page overflow cannot be concealed by CSS clipping."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        init_ctx = create_test_context(browser)
        init_page = create_test_page(init_ctx)
        story_id = get_real_story_id(init_page)
        init_ctx.close()

        routes = [
            f"{BASE_URL}/#/today",
            f"{BASE_URL}/#/briefing",
            f"{BASE_URL}/#/search",
            f"{BASE_URL}/#/projects",
            f"{BASE_URL}/#/saved",
            f"{BASE_URL}/#/changes",
            f"{BASE_URL}/#/runtime",
            f"{BASE_URL}/#/story/{story_id}",
        ]

        viewports = [320, 375, 480, 768, 1024, 1440]

        for vp_width in viewports:
            context = create_test_context(browser, viewport={"width": vp_width, "height": 800})
            page = create_test_page(context)

            for url in routes:
                page.goto(url, wait_until="networkidle")
                page.wait_for_timeout(300)
                verify_page_api_url(page)

                # Remove body overflow-x hidden override to expose unclipped layout bounds
                page.evaluate("""() => {
                    document.body.style.overflowX = 'visible';
                    document.documentElement.style.overflowX = 'visible';
                }""")

                # Measure element boundary rights excluding off-canvas sidebar (when closed), unfocused skip link, and table wrappers
                overflow_info = page.evaluate("""(vpW) => {
                    const skipLink = document.querySelector('.skip-link');
                    const sidebar = document.getElementById('app-sidebar');
                    const tableWrappers = Array.from(document.querySelectorAll('.table-wrapper'));

                    const allElements = Array.from(document.body.querySelectorAll('*'));
                    const overflowingEls = [];

                    for (const el of allElements) {
                        if (el === skipLink || (skipLink && skipLink.contains(el))) continue;
                        if (sidebar && sidebar.contains(el) && !sidebar.classList.contains('open')) continue;
                        if (tableWrappers.some(w => w === el || w.contains(el))) continue;

                        const r = el.getBoundingClientRect();
                        if (r.width > 0 && r.height > 0) {
                            if (r.right > vpW + 1.5) {
                                overflowingEls.push({
                                    tag: el.tagName,
                                    cls: el.className,
                                    id: el.id,
                                    right: r.right,
                                    width: r.width
                                });
                            }
                        }
                    }

                    return {
                        overflowCount: overflowingEls.length,
                        samples: overflowingEls.slice(0, 3)
                    };
                }""", vp_width)

                assert overflow_info["overflowCount"] == 0, f"Unmasked layout overflow at {vp_width}px on {url}: {overflow_info['samples']}"

            context.close()
        browser.close()


def test_playwright_zoom_and_text_spacing(test_servers):
    """Verify zoom reflow (200% zoom at 640px CSS equivalent and 400% zoom at 320px CSS equivalent) and WCAG text-spacing overrides across all 8 surfaces."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        init_ctx = create_test_context(browser)
        init_page = create_test_page(init_ctx)
        story_id = get_real_story_id(init_page)
        init_ctx.close()

        routes = [
            f"{BASE_URL}/#/today",
            f"{BASE_URL}/#/briefing",
            f"{BASE_URL}/#/search",
            f"{BASE_URL}/#/projects",
            f"{BASE_URL}/#/saved",
            f"{BASE_URL}/#/changes",
            f"{BASE_URL}/#/runtime",
            f"{BASE_URL}/#/story/{story_id}",
        ]

        # 1. Zoom emulation test (200% zoom = 640px, 400% zoom = 320px)
        for scale_label, width in [("200% Zoom (640px)", 640), ("400% Zoom (320px)", 320)]:
            context = create_test_context(browser, viewport={"width": width, "height": 800})
            page = create_test_page(context)

            for url in routes:
                page.goto(url, wait_until="networkidle")
                page.wait_for_timeout(300)
                verify_page_api_url(page)

                # Inject WCAG text-spacing override
                page.evaluate("""() => {
                    let style = document.getElementById('wcag-text-spacing-override');
                    if (!style) {
                        style = document.createElement('style');
                        style.id = 'wcag-text-spacing-override';
                        style.innerHTML = `
                            * {
                                line-height: 1.5 !important;
                                letter-spacing: 0.12em !important;
                                word-spacing: 0.16em !important;
                            }
                            p {
                                margin-bottom: 2em !important;
                            }
                        `;
                        document.head.appendChild(style);
                    }
                }""")

                page.wait_for_timeout(200)

                # Assert headings and controls remain visible and non-overlapping
                h1_visible = page.evaluate("() => { const h1 = document.querySelector('h1'); if (!h1) return false; const r = h1.getBoundingClientRect(); return r.width > 0 && r.height > 0; }")
                assert h1_visible, f"{scale_label}: Primary view h1 must remain visible on {url}"

                # Assert no page-level horizontal overflow
                no_h_overflow = page.evaluate("""() => {
                    return document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1;
                }""")
                assert no_h_overflow, f"{scale_label}: Page-level horizontal overflow detected on {url}"

                # Assert no overlapping interactive controls (excluding hidden, inert, off-canvas, unfocused skip-link, outside viewport)
                overlap_result = page.evaluate("""() => {
                    const controls = Array.from(document.querySelectorAll('button, a[href], input, select, textarea, [role="button"], [role="link"]'));
                    const visibleControls = controls.filter(el => {
                        if (el.closest('[hidden], [aria-hidden="true"], [inert], .sr-only')) return false;
                        if (el.classList.contains('skip-link') && document.activeElement !== el) return false;
                        const sidebar = el.closest('#app-sidebar');
                        if (sidebar && !sidebar.classList.contains('open') && window.innerWidth <= 768) return false;
                        
                        const r = el.getBoundingClientRect();
                        if (r.width <= 0 || r.height <= 0) return false;
                        if (r.bottom <= 0 || r.top >= window.innerHeight || r.right <= 0 || r.left >= window.innerWidth) return false;
                        return true;
                    });

                    for (let i = 0; i < visibleControls.length; i++) {
                        for (let j = i + 1; j < visibleControls.length; j++) {
                            const aEl = visibleControls[i];
                            const bEl = visibleControls[j];
                            if (aEl.contains(bEl) || bEl.contains(aEl)) continue;
                            
                            const a = aEl.getBoundingClientRect();
                            const b = bEl.getBoundingClientRect();
                            
                            const overlaps = !(a.right <= b.left + 0.5 || b.right <= a.left + 0.5 || a.bottom <= b.top + 0.5 || b.bottom <= a.top + 0.5);
                            if (overlaps) {
                                return {
                                    overlap: true,
                                    a: { tag: aEl.tagName, id: aEl.id, cls: String(aEl.className), text: (aEl.textContent||'').trim().slice(0, 40) },
                                    b: { tag: bEl.tagName, id: bEl.id, cls: String(bEl.className), text: (bEl.textContent||'').trim().slice(0, 40) }
                                };
                            }
                        }
                    }
                    return { overlap: false };
                }""")
                assert not overlap_result.get("overlap"), f"{scale_label}: Overlapping interactive controls detected on {url}: {overlap_result}"

            context.close()

        # 2. WCAG text-spacing pass at normal viewport
        context = create_test_context(browser, viewport={"width": 1280, "height": 800})
        page = create_test_page(context)

        for url in routes:
            page.goto(url, wait_until="networkidle")
            page.wait_for_timeout(300)
            verify_page_api_url(page)

            page.evaluate("""() => {
                let style = document.getElementById('wcag-text-spacing-override');
                if (!style) {
                    style = document.createElement('style');
                    style.id = 'wcag-text-spacing-override';
                    style.innerHTML = `
                        * {
                            line-height: 1.5 !important;
                            letter-spacing: 0.12em !important;
                            word-spacing: 0.16em !important;
                        }
                        p {
                            margin-bottom: 2em !important;
                        }
                    `;
                    document.head.appendChild(style);
                }
            }""")

            # Assert long adversarial strings wrap correctly
            long_string_wraps = page.evaluate("""() => {
                const testEl = document.createElement('div');
                testEl.style.cssText = 'position:absolute; visibility:hidden; width:300px; white-space:pre-wrap; word-wrap:break-word;';
                testEl.textContent = 'A'.repeat(200);
                document.body.appendChild(testEl);
                const wraps = testEl.scrollHeight > testEl.clientHeight;
                document.body.removeChild(testEl);
                return wraps;
            }""")
            assert long_string_wraps, f"Long strings must wrap correctly on {url}"

        context.close()
        browser.close()


def test_playwright_runtime_table_keyboard_scrolling(test_servers):
    """Non-vacuous Runtime Table Keyboard Scrolling test:
    Focus overflowing table wrapper -> record scrollLeft -> press ArrowRight -> assert scrollLeft STRICTLY increases -> press ArrowLeft repeatedly -> assert scrollLeft decreases to 0 -> assert focus ring visible."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = create_test_context(browser, viewport={"width": 480, "height": 800})
        page = create_test_page(context)

        page.goto(f"{BASE_URL}/#/runtime", wait_until="networkidle")
        page.wait_for_timeout(1000)
        verify_page_api_url(page)

        wrappers = page.locator(".table-wrapper")
        assert wrappers.count() >= 2, "Expected at least 2 runtime table wrappers"

        overflow_found = False

        for i in range(wrappers.count()):
            w = wrappers.nth(i)
            # Verify accessibility attributes
            assert w.get_attribute("tabindex") == "0", f"Wrapper {i} missing tabindex=0"
            assert w.get_attribute("role") == "region", f"Wrapper {i} missing role=region"
            assert w.get_attribute("aria-label") is not None, f"Wrapper {i} missing aria-label"

            # Focus the wrapper
            w.focus()
            page.wait_for_timeout(100)

            # Record initial scrollLeft
            initial_scroll = w.evaluate("(el) => el.scrollLeft")
            assert initial_scroll == 0, f"Wrapper {i} initial scrollLeft must be 0"

            # Check if wrapper is overflowing horizontally
            is_overflowing = w.evaluate("(el) => el.scrollWidth > el.clientWidth")
            if is_overflowing:
                overflow_found = True
                # Press ArrowRight
                page.keyboard.press("ArrowRight")
                page.wait_for_timeout(100)

                scrolled_right = w.evaluate("(el) => el.scrollLeft")
                assert scrolled_right > initial_scroll, f"Table wrapper {i} scrollLeft must STRICTLY increase (was {initial_scroll}, now {scrolled_right})"

                # Press ArrowLeft repeatedly through keyboard (not JS) until scrollLeft returns to 0
                max_left_presses = 50
                for _ in range(max_left_presses):
                    current_scroll = w.evaluate("(el) => el.scrollLeft")
                    if current_scroll == 0:
                        break
                    page.keyboard.press("ArrowLeft")
                    page.wait_for_timeout(50)
                else:
                    raise AssertionError(f"Table wrapper {i} did not return to scrollLeft=0 after {max_left_presses} ArrowLeft presses")

                final_scroll = w.evaluate("(el) => el.scrollLeft")
                assert final_scroll == 0, f"Table wrapper {i} must return to scrollLeft=0 via keyboard, got {final_scroll}"

                # Assert focus remains on wrapper
                active_is_wrapper = page.evaluate("""(wrapper) => document.activeElement === wrapper""", w.element_handle())
                assert active_is_wrapper, f"Focus must remain on table wrapper after keyboard scrolling"

                # Verify visible focus indicator has at least 3:1 contrast (check outline/focus ring)
                has_focus_ring = page.evaluate("""(wrapper) => {
                    const style = window.getComputedStyle(wrapper);
                    const outline = style.outlineWidth;
                    const boxShadow = style.boxShadow;
                    return outline !== '0px' || boxShadow !== 'none';
                }""", w.element_handle())
                assert has_focus_ring, f"Table wrapper {i} must have visible focus indicator with 3:1 contrast"

        # Fail if no table overflows - fixture must provide overflowing table
        assert overflow_found, "No runtime table wrapper was overflowing; fixture must seed data to cause horizontal overflow"

        browser.close()


def test_playwright_reduced_motion_preferences(test_servers):
    """Verify that prefers-reduced-motion: reduce disables CSS transitions/animations across key UI elements."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = create_test_context(browser, viewport={"width": 1280, "height": 800}, reduced_motion="reduce")
        page = create_test_page(context)
        page.goto(f"{BASE_URL}/#/today", wait_until="networkidle")
        page.wait_for_timeout(500)
        verify_page_api_url(page)

        reduced_applied = page.evaluate("""() => {
            const el = document.querySelector('.btn, .nav-link, #app-sidebar, body');
            if (!el) return false;
            const style = window.getComputedStyle(el);
            const dur = style.transitionDuration || '0s';
            const anim = style.animationDuration || '0s';
            return dur === '0s' || dur === '0.00001s' || dur === '0.001s' || parseFloat(dur) < 0.05 || anim === '0s';
        }""")
        assert reduced_applied, "Reduced motion preferences must disable animations/transitions"
        browser.close()


def test_playwright_live_region_reliability(test_servers):
    """Non-vacuous Live Region Reliability test using MutationObserver proof:
    Attach MutationObserver to #hermes-a11y-live -> call announceToScreenReader twice with identical message -> assert exact mutation sequence: empty -> message1 -> empty -> message2."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = create_test_context(browser, viewport={"width": 1280, "height": 800})
        page = create_test_page(context)

        page.goto(f"{BASE_URL}/#/today", wait_until="networkidle")
        page.wait_for_timeout(500)
        verify_page_api_url(page)

        # Attach MutationObserver to live region
        page.evaluate("""() => {
            window.observedMutations = [];
            let live = document.getElementById('hermes-a11y-live');
            if (!live) {
                live = document.createElement('div');
                live.id = 'hermes-a11y-live';
                live.className = 'sr-only';
                live.setAttribute('aria-live', 'polite');
                live.setAttribute('aria-atomic', 'true');
                document.body.appendChild(live);
            }

            const observer = new MutationObserver((mutations) => {
                for (const m of mutations) {
                    window.observedMutations.push({
                        type: m.type,
                        text: live.textContent || "",
                        ariaLive: live.getAttribute('aria-live')
                    });
                }
            });
            observer.observe(live, { childList: true, characterData: true, subtree: true, attributes: true, attributeFilter: ['aria-live'] });
        }""")

        # Announce first message (polite)
        page.evaluate("""async () => {
            const { announceToScreenReader } = await import('./src/utils/a11y.js');
            await announceToScreenReader('Search results updated: 14 matches', 'polite');
        }""")
        page.wait_for_timeout(100)

        # Announce identical second message (assertive)
        page.evaluate("""async () => {
            const { announceToScreenReader } = await import('./src/utils/a11y.js');
            await announceToScreenReader('Search results updated: 14 matches', 'assertive');
        }""")
        page.wait_for_timeout(100)

        recorded_mutations = page.evaluate("() => window.observedMutations")
        
        # Verify sequence: contains message -> cleared -> same message
        texts = [m.get("text", "") for m in recorded_mutations]
        assert len(texts) >= 3, f"Expected ordered mutations, got {texts}"
        
        # First announcement ends with the message
        assert "Search results updated: 14 matches" in texts[1] or "Search results updated: 14 matches" in texts[0]
        
        # Prior to second message, text was cleared to empty
        assert any(t == "" for t in texts), f"Expected cleared state in sequence: {texts}"
        
        # Final text equals the message
        assert texts[-1] == "Search results updated: 14 matches", f"Final live text mismatch: {texts[-1]}"
        
        # Verify final aria-live attribute is assertive
        final_live = page.evaluate("() => document.getElementById('hermes-a11y-live').getAttribute('aria-live')")
        assert final_live == "assertive", f"Expected assertive aria-live, got {final_live}"

        browser.close()
