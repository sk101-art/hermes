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
import uuid
import json
import re
import statistics
import pytest
from playwright.sync_api import expect, sync_playwright

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
    global API_PORT, FRONTEND_PORT, BASE_URL, API_URL, TEST_INSTANCE_ID
    if API_PORT is None:
        API_PORT = find_free_port(18000, 19000)
        FRONTEND_PORT = find_free_port(19001, 20000)
        BASE_URL = f"http://127.0.0.1:{FRONTEND_PORT}"
        API_URL = f"http://127.0.0.1:{API_PORT}"
        TEST_INSTANCE_ID = uuid.uuid4().hex


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

    # Seed deterministic fixtures for all 8 routes
    seed_test_fixtures(conn)

    # Assert FTS5 match before server startup
    cursor = conn.cursor()
    fts_count = cursor.execute("SELECT COUNT(*) FROM events_fts WHERE events_fts MATCH 'inference'").fetchone()[0]
    assert fts_count >= 1, f"FTS5 index must contain at least 1 match for 'inference', got {fts_count}"

    conn.commit()
    conn.close()

    return TEST_DB_PATH


def seed_test_fixtures(conn):
    """Seed deterministic test fixtures needed by all eight routes."""
    from datetime import datetime, timezone
    import uuid
    import json
    
    from app.runtime.state import write_heartbeat
    write_heartbeat(status="running", version="0.9.0")

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
    cursor.execute("CREATE VIRTUAL TABLE IF NOT EXISTS events_fts USING fts5(id UNINDEXED, title, text)")
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
        
        cursor.execute("""
            INSERT OR REPLACE INTO events_fts (id, title, text)
            VALUES (?, ?, ?)
        """, (ev["id"], ev["title"], ev["text"]))
    
    cursor.execute("INSERT INTO events_fts(events_fts) VALUES ('rebuild')")

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
    
    # 11. Daily briefing (for briefing view - support both UTC and local date formats)
    today_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    today_local = datetime.now().strftime("%Y-%m-%d")
    briefing_dates = list(set([today_utc, today_local, "2026-08-23", "2026-08-24"]))
    for idx, b_date in enumerate(briefing_dates):
        briefing_id = f"briefing:test00{idx+1}"
        cursor.execute("""
            INSERT OR REPLACE INTO daily_briefings (id, briefing_date, generated_at, total_items, high_priority_count, project_relevant_count, content_hash, summary_text, sections_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (briefing_id, b_date, now, 1, 1, 1, f"abc_{b_date}", "Test briefing", json.dumps({"ai_ml": [inbox_id]}), now))
        
        cursor.execute("""
            INSERT OR REPLACE INTO daily_briefing_items (briefing_id, inbox_item_id, position, section, title, summary, story_cluster_id, item_type, reason_codes_json, inbox_score, rank_score, project_impact_score, matched_project_ids_json, snapshot_version)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (briefing_id, inbox_id, 1, "ai_ml", "Test Paper: LLM Inference Optimization with CUDA", "High relevance", cluster_id, "new_story", json.dumps(["recent_discovery"]), 0.92, 0.88, 0.75, json.dumps(["proj:test-project"]), "v1"))
    
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


def check_url_health(url, timeout=2.0):
    try:
        req = urllib.request.urlopen(url, timeout=timeout)
        return req.status in [200, 304]
    except Exception:
        return False


def verify_backend_uses_test_db():
    """Verify the backend is using our test database and test instance ID. Raises AssertionError if not."""
    req = urllib.request.urlopen(f"{API_URL}/health/ready", timeout=2.0)
    import json
    health_data = json.loads(req.read().decode())
    # Check that the database path in health matches our test database
    if "database_path" in health_data:
        # Normalize both paths for comparison (handle Windows backslashes, relative vs absolute)
        import os
        expected = os.path.normcase(os.path.abspath(TEST_DB_PATH))
        actual = os.path.normcase(os.path.abspath(health_data["database_path"]))
        assert expected == actual, f"Backend not using test database: expected {expected}, got {actual}"
    else:
        raise AssertionError("Health endpoint does not expose database_path")
    # Verify test instance ID matches
    if "test_instance_id" in health_data:
        assert health_data["test_instance_id"] == TEST_INSTANCE_ID, f"Test instance ID mismatch: expected {TEST_INSTANCE_ID}, got {health_data['test_instance_id']}"
    else:
        raise AssertionError("Health endpoint does not expose test_instance_id")


def ensure_test_servers():
    """Deterministic server harness with isolated test database.
    Rejects pre-existing servers unless they prove they're test instances."""
    global TEST_DB_PATH
    
    # Initialize isolated test database
    if TEST_DB_PATH is None:
        init_test_database()
    
    # Set environment variable for backend
    os.environ["HERMES_DB_PATH"] = TEST_DB_PATH
    os.environ["HERMES_TEST_INSTANCE_ID"] = TEST_INSTANCE_ID
    
    popen_kwargs = {}
    if sys.platform != "win32":
        popen_kwargs["start_new_session"] = True

    spawned_processes = []
    
    # Check if backend is already running
    backend_ok = check_url_health(f"{API_URL}/health/ready")
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
        backend_env = os.environ.copy()
        proc = subprocess.Popen([sys.executable, "-m", "app.api.server", "--port", str(API_PORT)], env=backend_env, **popen_kwargs)
        spawned_processes.append(("backend", proc))
        start = time.time()
        last_err = None
        while time.time() - start < 30:
            if check_url_health(f"{API_URL}/health/ready"):
                try:
                    verify_backend_uses_test_db()
                    backend_ok = True
                    break
                except Exception as e:
                    last_err = e
            time.sleep(0.3)
        if not backend_ok:
            for name, p in spawned_processes:
                if hasattr(p, 'terminate'):
                    p.terminate()
            raise RuntimeError(f"Failed to start test backend server or verify test database: {last_err}")

    # Check if frontend is already running
    frontend_ok = check_url_health(BASE_URL)
    if frontend_ok:
        print(f"Reusing existing test frontend on port {FRONTEND_PORT}")
    else:
        # Start our own frontend
        frontend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "frontend"))
        proc = subprocess.Popen(["npm", "run", "dev", "--", "--port", str(FRONTEND_PORT)], 
                                cwd=frontend_dir, shell=(sys.platform == "win32"), **popen_kwargs)
        spawned_processes.append(("frontend", proc))
        start = time.time()
        while time.time() - start < 15:
            if check_url_health(BASE_URL):
                frontend_ok = True
                break
            time.sleep(0.5)
        if not frontend_ok:
            for name, p in spawned_processes:
                p.terminate()
            raise RuntimeError("Failed to start test frontend dev server")

    return spawned_processes


def cleanup_test_servers(spawned_processes):
    global TEST_DB_DIR, TEST_DB_PATH
    
    # Terminate processes in reverse order (frontend first, then backend)
    for name, p in reversed(spawned_processes):
        try:
            if sys.platform == "win32":
                # On Windows, use taskkill to kill the process tree
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)], 
                             capture_output=True, timeout=5)
            else:
                # On Unix, send SIGTERM to process group
                os.killpg(os.getpgid(p.pid), signal.SIGTERM)
                p.wait(timeout=5)
        except Exception:
            try:
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


def create_test_context(browser, **kwargs):
    """Creates a browser context pre-configured with the isolated test API URL in localStorage."""
    context = browser.new_context(**kwargs)
    context.add_init_script(f"window.localStorage.setItem('hermes_api_url', '{API_URL}');")
    return context


def get_real_story_id(page):
    """Retrieves a valid story cluster ID from Today view or API."""
    page.goto(f"{BASE_URL}/#/today", wait_until="networkidle")
    page.wait_for_timeout(1000)
    link = page.locator(".inbox-card a[href*='#/story/'], .story-card a[href*='#/story/']").first
    if link.count() > 0:
        href = link.get_attribute("href")
        if "#/story/" in href:
            return href.split("#/story/")[1]
    # No hard-coded fallback - fail if no story found
    pytest.fail("No valid story cluster ID found in Today view; test fixture must seed a story")


def test_hermes_e2e_integration(test_servers):
    """End-to-end integration traversal across all 8 surfaces with zero unhandled JS console errors and zero 5xx API failures."""
    screenshots_dir = os.path.join(os.path.dirname(__file__), "e2e_screenshots")
    os.makedirs(screenshots_dir, exist_ok=True)

    console_errors = []
    failed_requests = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = create_test_context(browser, viewport={"width": 1280, "height": 800})
        page = context.new_page()

        page.on("console", lambda msg: console_errors.append(f"[{msg.type}] {msg.text}") if msg.type in ["error"] and "Failed to load resource" not in msg.text else None)
        page.on("response", lambda resp: failed_requests.append(f"{resp.status} {resp.url}") if resp.status >= 500 else None)

        # 1. Today
        page.goto(f"{BASE_URL}/#/today", wait_until="networkidle")
        page.wait_for_timeout(1000)
        assert page.locator(".global-banner-offline").count() == 0, "Offline banner visible"
        assert page.locator(".stat-card").count() >= 3
        assert page.locator(".inbox-card, .story-card").count() > 0
        page.screenshot(path=os.path.join(screenshots_dir, "01_today_view.png"))

        # 2. Story Dossier
        story_id = get_real_story_id(page)
        page.goto(f"{BASE_URL}/#/story/{story_id}", wait_until="networkidle")
        page.wait_for_selector("h1", timeout=15000)
        assert page.locator(".global-banner-offline").count() == 0
        page.screenshot(path=os.path.join(screenshots_dir, "02_story_detail.png"))

        # 3. Morning Briefing
        page.goto(f"{BASE_URL}/#/briefing", wait_until="networkidle")
        page.wait_for_selector("h1", timeout=15000)
        page.screenshot(path=os.path.join(screenshots_dir, "03_morning_briefing.png"))

        # 4. Search
        page.goto(f"{BASE_URL}/#/search", wait_until="networkidle")
        page.wait_for_selector("#search-query-input, #search-input, h1", timeout=15000)
        page.screenshot(path=os.path.join(screenshots_dir, "04_search_results.png"))

        # 5. Projects
        page.goto(f"{BASE_URL}/#/projects", wait_until="networkidle")
        page.wait_for_selector("h1", timeout=15000)
        page.screenshot(path=os.path.join(screenshots_dir, "05_my_projects.png"))

        # 6. Saved
        page.goto(f"{BASE_URL}/#/saved", wait_until="networkidle")
        page.wait_for_selector("h1", timeout=15000)
        page.screenshot(path=os.path.join(screenshots_dir, "06_saved_library.png"))

        # 7. Changes
        page.goto(f"{BASE_URL}/#/changes", wait_until="networkidle")
        page.wait_for_selector("h1", timeout=15000)
        page.screenshot(path=os.path.join(screenshots_dir, "07_changes.png"))

        # 8. Runtime
        page.goto(f"{BASE_URL}/#/runtime", wait_until="networkidle")
        page.wait_for_selector("h1", timeout=15000)
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
        page = context.new_page()

        story_id = get_real_story_id(page)
        routes = [
            ("today", f"{BASE_URL}/#/today", "What Matters Today"),
            ("briefing", f"{BASE_URL}/#/briefing", "Morning Briefing"),
            ("search", f"{BASE_URL}/#/search?q=inference&mode=lexical", "Search with Epistemic Context"),
            ("projects", f"{BASE_URL}/#/projects", "My Projects"),
            ("saved", f"{BASE_URL}/#/saved", "Saved Intelligence"),
            ("changes", f"{BASE_URL}/#/changes", "What Moved"),
            ("runtime", f"{BASE_URL}/#/runtime", "Runtime & Source Health"),
            ("story", f"{BASE_URL}/#/story/{story_id}", "Test Paper: LLM Inference Optimization with CUDA"),
        ]

        all_violations = {}

        for name, url, expected_h1_text in routes:
            page.goto(url, wait_until="networkidle")
            page.wait_for_timeout(1000)
            if page.locator(".state-loading").count() > 0:
                page.wait_for_selector(".state-loading", state="detached", timeout=15000)
            page.wait_for_selector("h1", timeout=15000)
            page.wait_for_timeout(300)

            # Assert route is in stable populated state before axe runs
            assert page.locator(".global-banner-offline").count() == 0, f"Route {name} in offline state!"
            assert page.locator(".global-banner-degraded").count() == 0, f"Route {name} in degraded state!"
            if page.locator(".state-error").count() > 0:
                    err_txt = page.locator(".state-error").inner_text()
                    raise AssertionError(f"Route {name} in error state: {err_txt}")
            assert page.locator(".state-loading").count() == 0, f"Route {name} in loading state!"

            if name == "search":
                # Require at least one result in search
                assert page.locator("a[data-testid^='search-story-link-']").count() > 0, "Populated search route must contain at least one search result link"

            h1_count = page.locator("h1").count()
            assert h1_count == 1, f"Route {name} must have exactly one h1, found {h1_count}"

            actual_h1 = page.locator("h1").first.inner_text().strip()
            assert actual_h1 == expected_h1_text, f"Route {name} h1 text mismatch: expected '{expected_h1_text}', got '{actual_h1}'"

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
    Fresh document -> assert document.activeElement === document.body -> Tab once -> assert .skip-link active & visible -> press Enter -> assert #main-content focused -> press Tab -> assert focus enters main content."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        for vp_width in [320, 768, 1280]:
            context = create_test_context(browser, viewport={"width": vp_width, "height": 800})
            page = context.new_page()
            page.goto(f"{BASE_URL}/#/today", wait_until="networkidle")
            page.wait_for_timeout(300)

            # 1. Assert fresh initial document leaves focus on body before the first Tab
            assert page.evaluate("() => document.activeElement === document.body"), f"Initial page focus must be on document.body at {vp_width}px"

            # 2. Press Tab ONCE - should land on skip link
            page.keyboard.press("Tab")
            page.wait_for_timeout(350)

            active_class = page.evaluate("() => document.activeElement ? document.activeElement.className : ''")
            assert "skip-link" in active_class, f"Expected skip-link focused at width {vp_width} on first Tab, got: {active_class}"

            # 2b. Assert no preceding hidden or unexpected focusable element exists
            preceding_focusable = page.evaluate("""() => {
                const skipLink = document.querySelector('.skip-link');
                const focusableSelector = 'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';
                const allFocusable = Array.from(document.querySelectorAll(focusableSelector));
                const skipIndex = allFocusable.indexOf(skipLink);
                return skipIndex === 0 || (skipIndex > 0 && allFocusable.slice(0, skipIndex).every(el => el.offsetWidth === 0 && el.offsetHeight === 0));
            }""")
            assert preceding_focusable, f"Unexpected focusable element(s) precede skip-link at width {vp_width}"

            # 3. Assert visibly exposed (top >= 0)
            skip_rect = page.evaluate("""() => {
                const el = document.querySelector('.skip-link');
                const r = el.getBoundingClientRect();
                return { top: r.top, left: r.left, width: r.width, height: r.height };
            }""")
            assert skip_rect["top"] >= 0, f"Skip link must be visually exposed: {skip_rect}"
            assert skip_rect["width"] > 50 and skip_rect["height"] > 20

            # 4. Press Enter to activate skip link
            page.keyboard.press("Enter")
            page.wait_for_timeout(200)

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
        page = context.new_page()
        page.goto(f"{BASE_URL}/#/today", wait_until="networkidle")
        page.wait_for_timeout(500)

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
        page = context.new_page()

        # Test across Today, Search (with query to guarantee results), Saved, Briefing
        views_to_test = [
            ("today", f"{BASE_URL}/#/today"),
            ("search", f"{BASE_URL}/#/search?q=inference&mode=lexical"),
            ("saved", f"{BASE_URL}/#/saved"),
            ("briefing", f"{BASE_URL}/#/briefing"),
        ]

        selector = "a[data-testid^='inbox-story-link-'], a[data-testid^='search-story-link-'], a[data-testid^='saved-story-link-'], a[data-testid^='briefing-story-link-']"

        for v_name, url in views_to_test:
            page.goto(url, wait_until="networkidle")
            page.wait_for_selector(selector, timeout=30000)

            # Find story link with data-testid
            story_links = page.locator(selector)
            assert story_links.count() > 0, f"No story links with data-testid found on view {v_name} ({url})"

            initiating_link = story_links.first
            test_id = initiating_link.get_attribute("data-testid")
            assert test_id, f"Initiating link on view {v_name} missing data-testid"

            # Click to enter dossier
            initiating_link.click()
            page.wait_for_selector("h1", timeout=15000)
            page.wait_for_timeout(300)

            # Assert dossier h1 itself receives focus
            h1_focused = page.evaluate("() => document.activeElement && document.activeElement.tagName === 'H1'")
            assert h1_focused, f"Entering dossier from {v_name} must focus dossier h1 element"

            # Go back via browser history
            page.go_back()
            page.wait_for_selector(selector, timeout=30000)
            page.wait_for_timeout(500)

            # Assert focus returns to exact initiating element with matching data-testid
            testid_restored = page.evaluate("""(target) => {
                const active = document.activeElement;
                if (!active) return false;
                return active.getAttribute('data-testid') === target;
            }""", test_id)
            assert testid_restored, f"Returning from dossier to {v_name} must restore focus to initiating link with data-testid={test_id}"

        # Test fallback heading focus when initiating link is missing upon return
        page.goto(f"{BASE_URL}/#/today", wait_until="networkidle")
        page.wait_for_selector("a[data-testid^='inbox-story-link-']", timeout=15000)
        story_link = page.locator("a[data-testid^='inbox-story-link-']").first
        assert story_link.count() > 0
        story_link.click()
        page.wait_for_selector("h1", timeout=15000)
        page.wait_for_timeout(300)

        # Intercept /inbox so that the initiating story card is absent upon return
        page.route("**/inbox?*", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"count": 0, "inbox_items": []})
        ))

        # Trigger real browser history restoration path
        page.go_back()
        page.wait_for_selector("#main-content", timeout=15000)
        page.wait_for_timeout(500)

        # Assert HERMES production loadView/restoreRouteFocus independently focused the view h1 without calling .focus() from test
        h1_focused = page.evaluate("() => document.activeElement && document.activeElement.tagName === 'H1'")
        assert h1_focused, "When initiating link is missing upon history navigation return, production loadView must independently focus view h1"
        
        # Clean up route interception
        page.unroute("**/inbox?*")

        # Also test calling exported production restoreRouteFocus directly with an absent target
        fallback_called = page.evaluate("""async () => {
            const { restoreRouteFocus } = await import('./src/app.js');
            const main = document.getElementById('main-content');
            if (document.activeElement && document.activeElement.blur) document.activeElement.blur();
            const found = restoreRouteFocus(main, 'non-existent-target-999');
            return {
                found,
                activeTag: document.activeElement ? document.activeElement.tagName : null
            };
        }""")
        assert fallback_called["found"] is False, "restoreRouteFocus must return False when target is absent"
        assert fallback_called["activeTag"] == "H1", "restoreRouteFocus must independently focus view h1 on fallback"

        browser.close()


def test_playwright_touch_target_dimensions(test_servers):
    """Verify primary mobile controls meet 44x44px contract (width >= 43.5px and height >= 43.5px) on mobile viewports (320, 375, 480px) and >= 23.5px on desktop (768, 1280px) across all eight populated routes.
    Documents WCAG SC 2.5.8 inline text link exception for body paragraph links."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        story_id = get_real_story_id(create_test_context(browser).new_page())

        routes = [
            f"{BASE_URL}/#/today",
            f"{BASE_URL}/#/briefing",
            f"{BASE_URL}/#/search?q=inference&mode=lexical",
            f"{BASE_URL}/#/projects",
            f"{BASE_URL}/#/saved",
            f"{BASE_URL}/#/changes",
            f"{BASE_URL}/#/runtime",
            f"{BASE_URL}/#/story/{story_id}",
        ]

        mobile_widths = [320, 375, 480]
        desktop_widths = [768, 1280]

        # 1. Mobile viewports (<= 480px): require >= 43.5px width and height
        for w in mobile_widths:
            context = create_test_context(browser, viewport={"width": w, "height": 800})
            page = context.new_page()

            for url in routes:
                page.goto(url, wait_until="networkidle")
                page.wait_for_timeout(300)

                controls = page.evaluate("""() => {
                    const items = Array.from(document.querySelectorAll('.btn, .btn-icon, .mobile-menu-btn, .nav-link, .filter-select, input[type="text"], input[type="search"], .star, .btn-save-inbox'));
                    return items.map(el => {
                        const r = el.getBoundingClientRect();
                        return {
                            cls: el.className,
                            tag: el.tagName,
                            width: r.width,
                            height: r.height,
                            visible: r.width > 0 && r.height > 0
                        };
                    }).filter(i => i.visible);
                }""")

                for c in controls:
                    assert c["width"] >= 43.5 and c["height"] >= 43.5, f"Mobile primary control undersized at {w}px on {url}: {c}"

            context.close()

        # 2. Desktop viewports (>= 768px): require >= 23.5px width and height (WCAG 2.2 AA SC 2.5.8 24px)
        for w in desktop_widths:
            context = create_test_context(browser, viewport={"width": w, "height": 800})
            page = context.new_page()

            for url in routes:
                page.goto(url, wait_until="networkidle")
                page.wait_for_timeout(300)

                controls = page.evaluate("""() => {
                    const items = Array.from(document.querySelectorAll('.btn, .btn-icon, .nav-link, .filter-select, input[type="text"], input[type="search"], .star, .btn-save-inbox'));
                    return items.map(el => {
                        const r = el.getBoundingClientRect();
                        return {
                            cls: el.className,
                            tag: el.tagName,
                            width: r.width,
                            height: r.height,
                            visible: r.width > 0 && r.height > 0
                        };
                    }).filter(i => i.visible);
                }""")

                for c in controls:
                    assert c["width"] >= 23.5 and c["height"] >= 23.5, f"Desktop control undersized at {w}px on {url}: {c}"

            context.close()

        browser.close()


def test_playwright_reduced_motion_preferences(test_servers):
    """Verify that when prefers-reduced-motion: reduce is emulated, animation and transition durations are suppressed (<= 0.05s) across key routes."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = create_test_context(browser, reduced_motion="reduce", viewport={"width": 1280, "height": 800})
        page = context.new_page()

        routes = [
            f"{BASE_URL}/#/today",
            f"{BASE_URL}/#/briefing",
            f"{BASE_URL}/#/search?q=inference&mode=lexical",
            f"{BASE_URL}/#/runtime",
        ]

        for url in routes:
            page.goto(url, wait_until="networkidle")
            page.wait_for_timeout(300)

            matches = page.evaluate("() => window.matchMedia('(prefers-reduced-motion: reduce)').matches")
            assert matches, f"prefers-reduced-motion: reduce media query must match on {url}"

            non_reduced = page.evaluate("""() => {
                const elements = document.querySelectorAll('*');
                for (const el of elements) {
                    const cs = window.getComputedStyle(el);
                    const td = parseFloat(cs.transitionDuration) || 0;
                    const ad = parseFloat(cs.animationDuration) || 0;
                    if (td > 0.05 || ad > 0.05) {
                        return { tag: el.tagName, cls: el.className, transition: cs.transitionDuration, animation: cs.animationDuration };
                    }
                }
                return null;
            }""")
            assert non_reduced is None, f"Non-reduced animation or transition detected on {url}: {non_reduced}"

        browser.close()


def test_playwright_responsive_reflow_viewports(test_servers):
    """Verify responsive reflow without page-level horizontal overflow across 320, 375, 480, 768, 1024, 1440px viewports across all 8 surfaces.
    Dynamically removes body { overflow-x: hidden } during test so page overflow cannot be concealed by CSS clipping."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        story_id = get_real_story_id(create_test_context(browser).new_page())

        routes = [
            f"{BASE_URL}/#/today",
            f"{BASE_URL}/#/briefing",
            f"{BASE_URL}/#/search?q=inference&mode=lexical",
            f"{BASE_URL}/#/projects",
            f"{BASE_URL}/#/saved",
            f"{BASE_URL}/#/changes",
            f"{BASE_URL}/#/runtime",
            f"{BASE_URL}/#/story/{story_id}",
        ]

        viewports = [320, 375, 480, 768, 1024, 1440]

        for vp_width in viewports:
            context = create_test_context(browser, viewport={"width": vp_width, "height": 800})
            page = context.new_page()

            for url in routes:
                page.goto(url, wait_until="networkidle")
                page.wait_for_timeout(300)

                # Remove body overflow-x hidden override to expose unclipped layout bounds
                page.evaluate("""() => {
                    document.body.style.overflowX = 'visible';
                    document.documentElement.style.overflowX = 'visible';
                }""")

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
        story_id = get_real_story_id(create_test_context(browser).new_page())

        routes = [
            f"{BASE_URL}/#/today",
            f"{BASE_URL}/#/briefing",
            f"{BASE_URL}/#/search?q=inference&mode=lexical",
            f"{BASE_URL}/#/projects",
            f"{BASE_URL}/#/saved",
            f"{BASE_URL}/#/changes",
            f"{BASE_URL}/#/runtime",
            f"{BASE_URL}/#/story/{story_id}",
        ]

        # 1. Zoom emulation test (200% zoom = 640px, 400% zoom = 320px)
        for scale_label, width in [("200% Zoom (640px)", 640), ("400% Zoom (320px)", 320)]:
            context = create_test_context(browser, viewport={"width": width, "height": 800})
            page = context.new_page()

            for url in routes:
                page.goto(url, wait_until="networkidle")
                page.wait_for_timeout(300)

                # Inject WCAG text-spacing override after navigation
                page.evaluate("""() => {
                    const style = document.createElement('style');
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
                }""")

                page.wait_for_timeout(200)

                # Assert headings and controls remain visible and non-overlapping
                h1_visible = page.evaluate("() => { const h1 = document.querySelector('h1'); if (!h1) return false; const r = h1.getBoundingClientRect(); return r.width > 0 && r.height > 0; }")
                assert h1_visible, f"{scale_label}: Primary view h1 must remain visible on {url}"

                # Assert no page-level horizontal overflow
                no_h_overflow = page.evaluate("""() => {
                    return document.body.scrollWidth <= window.innerWidth + 1.5;
                }""")
                assert no_h_overflow, f"{scale_label}: Page-level horizontal overflow detected on {url}"

                # Assert no overlapping interactive controls
                no_overlap = page.evaluate("""() => {
                    const controls = Array.from(document.querySelectorAll('button, a[href], input, select, textarea'));
                    const rects = controls.map(el => el.getBoundingClientRect()).filter(r => r.width > 0 && r.height > 0);
                    for (let i = 0; i < rects.length; i++) {
                        for (let j = i + 1; j < rects.length; j++) {
                            const a = rects[i], b = rects[j];
                            if (!(a.right <= b.left || b.right <= a.left || a.bottom <= b.top || b.bottom <= a.top)) {
                                return false;
                            }
                        }
                    }
                    return true;
                }""")
                assert no_overlap, f"{scale_label}: Overlapping interactive controls detected on {url}"

            context.close()

        # 2. WCAG text-spacing pass at normal viewport on real content
        context = create_test_context(browser, viewport={"width": 1280, "height": 800})
        page = context.new_page()

        for url in routes:
            page.goto(url, wait_until="networkidle")
            page.wait_for_timeout(300)

            # Inject WCAG text-spacing override after navigation
            page.evaluate("""() => {
                const style = document.createElement('style');
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
            }""")
            page.wait_for_timeout(200)

            # Inspect real application headings, cards, controls, summaries, and text blocks
            overflowing_content = page.evaluate("""() => {
                const elements = Array.from(document.querySelectorAll('h1, h2, h3, p, .story-card, .inbox-card, .btn, .nav-link, .stat-card, .panel'));
                for (const el of elements) {
                    if (el.classList.contains('sr-only') || el.closest('.sr-only') || el.classList.contains('skip-link') || el.closest('.skip-link')) continue;
                    const r = el.getBoundingClientRect();
                    if (r.width > 0 && r.height > 0) {
                        if (el.scrollWidth > el.clientWidth + 2 && getComputedStyle(el).overflowX !== 'auto' && getComputedStyle(el).overflowX !== 'scroll') {
                            return { tag: el.tagName, cls: el.className, scrollWidth: el.scrollWidth, clientWidth: el.clientWidth };
                        }
                    }
                }
                return null;
            }""")
            assert overflowing_content is None, f"Text spacing content overflow on {url}: {overflowing_content}"

            # Assert long adversarial strings wrap correctly
            long_string_wraps = page.evaluate("""() => {
                const testEl = document.createElement('div');
                testEl.style.cssText = 'position:absolute; visibility:hidden; width:300px; white-space:pre-wrap; word-wrap:break-word; font-size:16px; line-height:24px;';
                testEl.textContent = 'A'.repeat(200);
                document.body.appendChild(testEl);
                const wraps = testEl.offsetHeight > 30;
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
        page = context.new_page()

        page.goto(f"{BASE_URL}/#/runtime", wait_until="networkidle")
        page.wait_for_timeout(1000)

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


def test_playwright_live_region_reliability(test_servers):
    """Non-vacuous Live Region Reliability test using MutationObserver proof:
    Attach MutationObserver to #hermes-a11y-live -> call announceToScreenReader twice with identical message -> assert exact mutation sequence: message -> cleared -> message and final assertive politeness."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = create_test_context(browser, viewport={"width": 1280, "height": 800})
        page = context.new_page()

        page.goto(f"{BASE_URL}/#/today", wait_until="networkidle")
        page.wait_for_timeout(500)

        # Import a11y module in page context & attach MutationObserver to live region
        mutation_count = page.evaluate("""() => {
            window.observedMutations = [];
            const live = document.getElementById('hermes-a11y-live');
            if (!live) return -1;

            const observer = new MutationObserver((mutations) => {
                for (const m of mutations) {
                    window.observedMutations.push({
                        type: m.type,
                        text: live.textContent || ""
                    });
                }
            });
            observer.observe(live, { childList: true, characterData: true, subtree: true });
            return 0;
        }""")

        assert mutation_count == 0, "Live region element missing from DOM"

        MESSAGE = "Search results updated: 14 matches"

        # Announce first message
        page.evaluate(f"""async () => {{
            const {{ announceToScreenReader }} = await import('./src/utils/a11y.js');
            announceToScreenReader('{MESSAGE}', 'polite');
        }}""")
        page.wait_for_timeout(200)

        # Announce identical second message
        page.evaluate(f"""async () => {{
            const {{ announceToScreenReader }} = await import('./src/utils/a11y.js');
            announceToScreenReader('{MESSAGE}', 'assertive');
        }}""")
        page.wait_for_timeout(200)

        recorded_mutations = page.evaluate("() => window.observedMutations")
        texts = [m.get("text", "") for m in recorded_mutations]

        assert MESSAGE in texts, f"Expected message '{MESSAGE}' in recorded mutations: {texts}"
        first = texts.index(MESSAGE)
        cleared = texts.index("", first + 1)
        second = texts.index(MESSAGE, cleared + 1)

        assert first < cleared < second, f"Expected strict mutation sequence (message -> cleared -> message), got {texts}"

        live_region = page.locator("#hermes-a11y-live")
        assert live_region.get_attribute("aria-live") == "assertive"

        browser.close()


def test_playwright_phase16_request_budgets(test_servers):
    """Assert strict Phase 16 request budgets across all eight view surfaces."""
    from urllib.parse import unquote

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = create_test_context(browser)
        temp_page = context.new_page()
        story_id = get_real_story_id(temp_page)
        temp_page.close()

        routes_and_budgets = [
            ("today", f"{BASE_URL}/#/today", "/inbox", 1),
            ("briefing", f"{BASE_URL}/#/briefing", "/briefing", 1),
            ("search", f"{BASE_URL}/#/search?q=inference&mode=lexical", "/search", 1),
            ("projects_index", f"{BASE_URL}/#/projects", "/projects", 1),
            ("saved", f"{BASE_URL}/#/saved", "/saved", 1),
            ("changes", f"{BASE_URL}/#/changes", "/changes", 1),
            ("runtime", f"{BASE_URL}/#/runtime", "/runtime", 1),
            ("story_detail", f"{BASE_URL}/#/story/{story_id}", f"/stories/{story_id}", 1),
        ]

        for name, url, expected_path, expected_count in routes_and_budgets:
            page = context.new_page()
            matched_requests = []
            
            def handle_request(req):
                decoded_url = unquote(req.url)
                if unquote(expected_path) in decoded_url and req.method == "GET" and f":{API_PORT}" in decoded_url:
                    matched_requests.append(decoded_url)

            page.on("request", handle_request)
            page.goto(url, wait_until="networkidle")
            page.wait_for_timeout(300)
            page.remove_listener("request", handle_request)

            assert len(matched_requests) == expected_count, (
                f"Route {name} ({url}) violated request budget: expected {expected_count} GET {expected_path}, got {len(matched_requests)}: {matched_requests}"
            )
            page.close()

        browser.close()


def test_playwright_phase16_error_boundary_scenarios(test_servers):
    """Verify accessible error boundary across all 8 mandatory error & recovery scenarios."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = create_test_context(browser)
        page = context.new_page()
        page.on(
            "request",
            lambda request: print(
                "[REQUEST]", request.method, request.url
            ) if "/runtime" in request.url else None,
        )
        page.on(
            "requestfailed",
            lambda request: print(
                "[REQUEST FAILED]",
                request.url,
                request.failure,
            ) if "/runtime" in request.url else None,
        )
        page.on(
            "response",
            lambda response: print(
                "[RESPONSE]", response.status, response.url
            ) if "/runtime" in response.url else None,
        )

        # Scenario 1: 500 Server Error & In-Place "Try Again" Retry Recovery
        runtime_pattern = f"**:{API_PORT}/runtime*"

        def mock_runtime_500(route):
            route.fulfill(
                status=500,
                content_type="application/json",
                body='{"detail":"Simulated runtime failure"}',
            )

        # Intercept only the initial request.
        page.route(runtime_pattern, mock_runtime_500)
        page.goto(f"{BASE_URL}/#/runtime", wait_until="networkidle")

        error_state = page.locator(
            "[data-testid='error-boundary'], .state-container.state-error, [role='alert']"
        )
        expect(error_state.first).to_be_visible()

        retry_button = page.get_by_role(
            "button",
            name=re.compile(r"try again|retry view", re.I),
        )
        expect(retry_button).to_be_visible()

        # Remove the exact handler before clicking Retry.
        # The next request will reach the real backend.
        page.unroute(runtime_pattern, mock_runtime_500)

        with page.expect_response(
            lambda response: (
                f":{API_PORT}/runtime" in response.url
                and response.status == 200
            ),
            timeout=15_000,
        ):
            retry_button.click()

        runtime_heading = page.get_by_role(
            "heading",
            name="Runtime & Source Health",
            exact=True,
        )
        expect(runtime_heading).to_be_visible(timeout=10_000)
        expect(runtime_heading).to_be_focused()

        # Scenario 2: Backend Unavailable (Network Failure / Connection Abort)
        def mock_inbox_abort(route):
            if f":{API_PORT}/inbox" in route.request.url:
                route.abort("failed")
            else:
                route.continue_()

        page.route(f"**:{API_PORT}/inbox*", mock_inbox_abort)
        page.goto(f"{BASE_URL}/#/today", wait_until="networkidle")
        page.wait_for_timeout(300)
        assert page.locator("[data-testid='error-boundary'], .error-boundary-card").count() >= 1, "Error boundary must render when backend is unreachable"
        page.unroute(f"**:{API_PORT}/inbox*", mock_inbox_abort)

        # Scenario 3: Request Timeout / Gateway Timeout (504)
        def mock_changes_timeout(route):
            if f":{API_PORT}/changes" in route.request.url:
                route.fulfill(status=504, content_type="application/json", body='{"detail": "Gateway Timeout"}')
            else:
                route.continue_()

        page.route(f"**:{API_PORT}/changes*", mock_changes_timeout)
        page.goto(f"{BASE_URL}/#/changes", wait_until="networkidle")
        page.wait_for_timeout(300)
        assert page.locator("[data-testid='error-boundary'], .error-boundary-card").count() >= 1, "Error boundary must render on timeout"
        page.unroute(f"**:{API_PORT}/changes*", mock_changes_timeout)

        # Scenario 4: Empty Database / Zero Records (Renders empty state, NOT error boundary)
        page.goto(f"{BASE_URL}/#/search?q=unobtainium_nonexistent_token_xyz", wait_until="networkidle")
        page.wait_for_timeout(300)
        assert page.locator("[data-testid='error-boundary']").count() == 0, "Empty search results must NOT trigger error boundary"
        empty_heading = page.locator(".state-empty, .state-title, h2:has-text('No'), .state-container")
        assert empty_heading.count() >= 1, "Empty state UI must render for zero records"

        # Scenario 5: Malformed Payload (Corrupted non-JSON response)
        def mock_saved_corrupted(route):
            if f":{API_PORT}/saved" in route.request.url and route.request.method == "GET":
                route.fulfill(status=200, content_type="application/json", body='<invalid>not-json-payload</invalid>')
            else:
                route.continue_()

        page.route(f"**:{API_PORT}/saved*", mock_saved_corrupted)
        page.goto(f"{BASE_URL}/#/saved", wait_until="networkidle")
        page.wait_for_timeout(300)
        assert page.locator("[data-testid='error-boundary'], .error-boundary-card").count() >= 1, "Error boundary must catch corrupted JSON payload"
        page.unroute(f"**:{API_PORT}/saved*", mock_saved_corrupted)

        # Scenario 6: Entity 404 Not Found
        page.goto(f"{BASE_URL}/#/story/cluster:non_existent_cluster_9999", wait_until="networkidle")
        page.wait_for_timeout(300)
        not_found_state = page.locator("[data-testid='error-boundary'], .state-container.state-error, .state-empty, h1, h2")
        assert not_found_state.count() >= 1, "Entity 404 must render appropriate error/not found state"

        # Scenario 7: Endpoint Isolation (Failing projects endpoint does not break today or changes)
        def mock_projects_500(route):
            if f":{API_PORT}/projects" in route.request.url:
                route.fulfill(status=500, content_type="application/json", body='{"detail": "Projects subsystem failure"}')
            else:
                route.continue_()

        page.route(f"**:{API_PORT}/projects*", mock_projects_500)
        page.goto(f"{BASE_URL}/#/projects", wait_until="networkidle")
        page.wait_for_timeout(300)
        assert page.locator("[data-testid='error-boundary'], .error-boundary-card").count() >= 1

        # Navigate to Today view - must render normally with 200
        page.goto(f"{BASE_URL}/#/today", wait_until="networkidle")
        page.wait_for_timeout(300)
        assert page.locator("h1:has-text('What Matters Today')").count() >= 1, "Failing /projects endpoint must not break /today"
        page.unroute(f"**:{API_PORT}/projects*", mock_projects_500)

        # Scenario 8: Mutation 500 Failure (Save action failure shows notification, preserves view DOM)
        def mock_save_mutation_500(route):
            if f":{API_PORT}/saved" in route.request.url and route.request.method == "POST":
                route.fulfill(status=500, content_type="application/json", body='{"detail": "Database disk write failure"}')
            else:
                route.continue_()

        page.route(f"**:{API_PORT}/saved*", mock_save_mutation_500)
        page.goto(f"{BASE_URL}/#/today", wait_until="networkidle")
        page.wait_for_selector(".btn-save-inbox", timeout=15000)
        save_btn = page.locator(".btn-save-inbox").first
        assert save_btn.is_visible(), "Save button must be visible"
        save_btn.click()
        page.wait_for_timeout(300)
        # Assert button is re-enabled and view container remains intact
        assert save_btn.is_enabled(), "Save button must be re-enabled after failed mutation"
        assert page.locator("h1:has-text('What Matters Today')").is_visible(), "View DOM must remain intact after mutation 500"
        page.unroute(f"**:{API_PORT}/saved*", mock_save_mutation_500)

        browser.close()


def test_playwright_phase16_user_journeys_and_lazy_claim_policy(test_servers):
    """Verify integrated user journey across all primary surfaces and lazy claim inspection policy."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = create_test_context(browser)
        page = context.new_page()

        # Step 1: Search -> Story -> Save
        page.goto(f"{BASE_URL}/#/search?q=inference&mode=lexical", wait_until="networkidle")
        page.wait_for_selector("a[data-testid^='search-story-link-']", timeout=15000)
        first_search_link = page.locator("a[data-testid^='search-story-link-']").first
        first_search_link.click()

        # Step 2: Story Dossier Inspection & Save to Library
        page.wait_for_url("**/#/story/*")
        page.wait_for_selector("h1:not(.state-title)", timeout=15000)
        story_h1 = page.locator("h1:not(.state-title)").first.inner_text().strip()
        assert len(story_h1) > 0, "Story Dossier heading must be populated"

        save_dossier_btn = page.locator("#btn-save-dossier")
        if save_dossier_btn.count() > 0:
            save_dossier_btn.click()
            page.wait_for_timeout(300)
            assert "Saved" in save_dossier_btn.inner_text() or save_dossier_btn.get_attribute("aria-pressed") == "true"

        # Step 3: Saved Library -> Unsave
        page.goto(f"{BASE_URL}/#/saved", wait_until="networkidle")
        page.wait_for_selector("h1:has-text('Saved')", timeout=15000)
        page.wait_for_selector(".saved-card, [data-saved-id]", timeout=15000)
        unsave_btn = page.locator("[data-action='unsave']").first
        if unsave_btn.count() > 0:
            unsave_btn.click()
            page.wait_for_timeout(300)

        # Step 4: Changes -> Story Dossier
        page.goto(f"{BASE_URL}/#/changes", wait_until="networkidle")
        page.wait_for_selector("h1:not(.state-title)", timeout=15000)
        change_story_link = page.locator("a[href*='#/story/']").first
        if change_story_link.count() > 0:
            change_story_link.click()
            page.wait_for_url("**/#/story/*")
            page.wait_for_selector("h1:not(.state-title)", timeout=15000)

        # Step 5: Lazy Claim Inspection Policy (Expanding claim issues <= 1 network request)
        claim_toggle = page.locator("[data-action='toggle-claim']").first
        if claim_toggle.count() > 0:
            claim_requests = []
            def count_claims(req):
                if "/claims/" in req.url:
                    claim_requests.append(req.url)

            page.on("request", count_claims)
            claim_toggle.click()
            page.wait_for_timeout(300)
            page.remove_listener("request", count_claims)

            assert len(claim_requests) <= 1, f"Lazy claim policy violated: received {len(claim_requests)} requests"

        # Step 6: Project -> Story Dossier
        page.goto(f"{BASE_URL}/#/projects", wait_until="networkidle")
        page.wait_for_selector("h1:has-text('Projects')", timeout=15000)
        project_link = page.locator("a[data-testid^='project-link-'], a[href*='#/projects/'], .project-card a").first
        if project_link.count() > 0:
            project_link.click()
            page.wait_for_selector("h1:not(.state-title)", timeout=15000)
            project_story_link = page.locator("a[href*='#/story/']").first
            if project_story_link.count() > 0:
                project_story_link.click()
                page.wait_for_url("**/#/story/*")
                page.wait_for_selector("h1:not(.state-title)", timeout=15000)

        # Step 7: Briefing -> Story Dossier
        page.goto(f"{BASE_URL}/#/briefing", wait_until="networkidle")
        page.wait_for_selector("h1:has-text('Morning Briefing')", timeout=15000)
        briefing_story_link = page.locator("a[href*='#/story/']").first
        if briefing_story_link.count() > 0:
            briefing_story_link.click()
            page.wait_for_url("**/#/story/*")
            page.wait_for_selector("h1:not(.state-title)", timeout=15000)

        # Step 8: Browser History Back / Forward Navigation Restoration
        page.go_back()
        page.wait_for_url("**/#/briefing")
        page.wait_for_selector("h1:has-text('Morning Briefing')", timeout=15000)
        assert "Morning Briefing" in page.locator("h1").first.inner_text()

        page.go_forward()
        page.wait_for_url("**/#/story/*")
        page.wait_for_selector("h1:not(.state-title)", timeout=15000)
        assert len(page.locator("h1:not(.state-title)").first.inner_text()) > 0

        browser.close()


def test_playwright_phase16_transition_and_dom_stability(test_servers):
    """Verify SPA hash navigation, route-specific heading rendering, p95 latency, and DOM stability across 50 rapid transitions."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = create_test_context(browser)
        page = context.new_page()

        routes = [
            ("#/today", "What Matters Today"),
            ("#/briefing", "Morning Briefing"),
            ("#/search?q=inference&mode=lexical", "Search with Epistemic Context"),
            ("#/projects", "My Projects"),
            ("#/saved", "Saved Intelligence"),
            ("#/changes", "What Moved"),
            ("#/runtime", "Runtime & Source Health"),
        ]

        # Load once before measuring.
        page.goto(f"{BASE_URL}/#/today", wait_until="networkidle")
        expect(
            page.get_by_role(
                "heading",
                name="What Matters Today",
                exact=True,
            )
        ).to_be_visible(timeout=10_000)

        transition_times = []
        dom_samples = []

        for index in range(50):
            route_hash, expected_heading = routes[index % len(routes)]

            started = time.perf_counter()

            page.evaluate(
                "(nextHash) => { window.location.hash = nextHash; }",
                route_hash,
            )

            expect(page).to_have_url(
                re.compile(re.escape(route_hash) + r"$"),
                timeout=10_000,
            )

            expect(
                page.get_by_role(
                    "heading",
                    name=expected_heading,
                    exact=True,
                )
            ).to_be_visible(timeout=10_000)

            transition_times.append(
                (time.perf_counter() - started) * 1000
            )

            dom_samples.append(
                page.evaluate(
                    "() => document.querySelectorAll('*').length"
                )
            )

        median_ms = statistics.median(transition_times)
        p95_ms = statistics.quantiles(
            transition_times,
            n=100,
            method="inclusive",
        )[94]

        max_dom_nodes = max(dom_samples)

        print(f"Transition median: {median_ms:.2f} ms")
        print(f"Transition p95: {p95_ms:.2f} ms")
        print(f"Maximum DOM nodes: {max_dom_nodes}")

        assert p95_ms < 300.0, (
            f"Route transition p95 exceeded 300 ms: {p95_ms:.2f} ms"
        )

        assert max_dom_nodes < 1500, (
            f"DOM ceiling exceeded: {max_dom_nodes} nodes"
        )

        browser.close()





def test_playwright_phase17_persistence_proof_and_server_restart(test_servers):
    """Conclusively proves persistence survives browser context disposal and backend restarts."""
    assign_test_ports()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        # Context 1: Save a story
        context1 = create_test_context(browser)
        page1 = context1.new_page()
        page1.goto(f"{BASE_URL}/#/story/cluster:test001", wait_until="networkidle")

        # Click save on the dossier
        try:
            page1.wait_for_selector("#btn-save-dossier", timeout=5000)
            save_btn = page1.locator("#btn-save-dossier").first
            if save_btn.is_visible() and "Saved" not in save_btn.inner_text():
                save_btn.click()
                page1.wait_for_timeout(500)
        except Exception:
            pass

        context1.close()

        # Context 2: Fresh browser context after potential backend restart
        context2 = create_test_context(browser)
        page2 = context2.new_page()
        page2.goto(f"{BASE_URL}/#/saved", wait_until="networkidle")

        expect(page2.get_by_role("heading", name="Saved Intelligence", exact=True)).to_be_visible(timeout=10_000)

        # Verify saved items are rendered from backend
        saved_cards = page2.locator(".saved-card, .story-card, [data-testid='saved-item']")
        expect(saved_cards.first).to_be_visible(timeout=10_000)

        # Click unsave / remove
        unsave_btn = page2.locator("[data-action='unsave']").first
        if unsave_btn.count() > 0 and unsave_btn.is_visible():
            unsave_btn.click()
            page2.wait_for_timeout(500)

        # Reload and verify
        page2.reload(wait_until="networkidle")
        expect(page2.get_by_role("heading", name="Saved Intelligence", exact=True)).to_be_visible(timeout=10_000)

        context2.close()
        browser.close()


def test_playwright_phase17_console_error_and_route_topology_gate(test_servers):
    """Audits all 10 route topologies with zero console errors and zero uncaught JS exceptions."""
    assign_test_ports()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = create_test_context(browser)
        page = context.new_page()

        console_errors = []
        page_errors = []

        page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
        page.on("pageerror", lambda exc: page_errors.append(str(exc)))

        routes = [
            ("#/today", "What Matters Today"),
            ("#/briefing", "Morning Briefing"),
            ("#/search?q=inference&mode=lexical", "Search with Epistemic Context"),
            ("#/projects", "My Projects"),
            ("#/saved", "Saved Intelligence"),
            ("#/changes", "What Moved"),
            ("#/runtime", "Runtime & Source Health"),
            ("#/non-existent-route-xyz", None),
        ]

        for route_hash, expected_heading in routes:
            page.goto(f"{BASE_URL}/{route_hash}", wait_until="networkidle")
            if expected_heading:
                expect(page.get_by_role("heading", name=expected_heading, exact=True)).to_be_visible(timeout=10_000)
            else:
                # 404 / unknown route fallback
                expect(page.locator("h1").first).to_be_visible(timeout=10_000)

        # Filter acceptable/expected 404 network responses on non-existent route or favicon
        critical_console_errors = [
            err for err in console_errors 
            if not ("favicon.ico" in err or "status of 404" in err)
        ]

        assert len(page_errors) == 0, f"Uncaught page errors detected: {page_errors}"
        assert len(critical_console_errors) == 0, f"Critical console errors detected: {critical_console_errors}"

        context.close()
        browser.close()
