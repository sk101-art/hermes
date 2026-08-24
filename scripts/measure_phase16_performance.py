#!/usr/bin/env python3
"""
HERMES Phase 16 Performance Evidence Benchmark.

Records:
- Environment details (OS, Python version, platform, SQLite version)
- Git commit SHA and timestamp
- Database isolated copy hash and dataset record counts
- Cold run latency, Warm run latencies (sample count N=50), min, median (p50), p95, and max
- Output saved to reports/phase16_performance.json
"""

import os
import sys
import time
import json
import shutil
import sqlite3
import tempfile
import platform
import subprocess
from datetime import datetime, timezone
import statistics

# Ensure repository root is on sys.path
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

def get_git_commit():
    try:
        res = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=REPO_ROOT)
        return res.stdout.strip() if res.returncode == 0 else "unknown"
    except Exception:
        return "unknown"

def get_file_sha256(filepath):
    import hashlib
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()

def measure_function_latency(fn, samples=50):
    """Measures cold latency and warm latencies for fn."""
    # Cold run
    t0 = time.perf_counter()
    res = fn()
    t1 = time.perf_counter()
    cold_ms = round((t1 - t0) * 1000.0, 3)

    # Warm runs
    warm_latencies = []
    for _ in range(samples):
        t0 = time.perf_counter()
        fn()
        t1 = time.perf_counter()
        warm_latencies.append((t1 - t0) * 1000.0)

    warm_latencies.sort()
    med_ms = round(statistics.median(warm_latencies), 3)
    p95_ms = round(warm_latencies[int(len(warm_latencies) * 0.95)], 3)
    min_ms = round(min(warm_latencies), 3)
    max_ms = round(max(warm_latencies), 3)

    return {
        "samples": samples,
        "cold_ms": cold_ms,
        "min_ms": min_ms,
        "median_ms": med_ms,
        "p95_ms": p95_ms,
        "max_ms": max_ms
    }

def main():
    print("=" * 70)
    print("HERMES PHASE 16 PERFORMANCE BENCHMARK")
    print("=" * 70)

    commit_sha = get_git_commit()
    prod_db_path = os.path.join(REPO_ROOT, "data", "tech_intel.db")
    prod_db_hash = get_file_sha256(prod_db_path) if os.path.exists(prod_db_path) else "missing"

    # Create temporary isolated benchmark database
    temp_dir = tempfile.mkdtemp(prefix="hermes_perf_")
    bench_db_path = os.path.join(temp_dir, "bench_tech_intel.db")
    shutil.copy2(prod_db_path, bench_db_path)
    os.environ["HERMES_DB_PATH"] = bench_db_path

    # Gather dataset record counts
    conn = sqlite3.connect(bench_db_path)
    cursor = conn.cursor()
    counts = {}
    tables = [
        "events", "story_clusters", "cluster_events", "claims", "evidence",
        "technology_assessments", "technology_states", "projects", "project_matches",
        "daily_briefings", "source_checkpoints", "runtime_jobs"
    ]
    for table in tables:
        try:
            c = cursor.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            counts[table] = c
        except Exception:
            counts[table] = 0
    
    # Get a sample cluster_id and project_id for parameterized endpoints
    try:
        sample_cluster = cursor.execute("SELECT id FROM story_clusters LIMIT 1").fetchone()
        sample_cluster_id = sample_cluster[0] if sample_cluster else "cluster:test001"
    except Exception:
        sample_cluster_id = "cluster:test001"

    try:
        sample_project = cursor.execute("SELECT id FROM projects LIMIT 1").fetchone()
        sample_project_id = sample_project[0] if sample_project else "project:hermes"
    except Exception:
        sample_project_id = "project:hermes"
    conn.close()

    # Import database module and FastAPI test client
    from app.storage.db import Database
    from app.api.server import app
    from fastapi.testclient import TestClient

    db = Database(db_path=bench_db_path)
    client = TestClient(app)

    # 1. Database Batch Queries Benchmark
    print("Benchmarking Database Batch Hydration Methods...")
    clusters_sample = db.get_clusters_by_ids([sample_cluster_id])
    all_cluster_ids = [c.id for c in db.get_top_clusters(limit=50)]
    
    db_benchmarks = {
        "get_claims_by_cluster_ids (N=50)": measure_function_latency(
            lambda: db.get_claims_by_cluster_ids(all_cluster_ids)
        ),
        "get_evidence_by_claim_ids (N=50)": measure_function_latency(
            lambda: db.get_evidence_by_claim_ids(["claim:test001", "claim:test002"])
        ),
        "get_assessments_by_cluster_ids (N=50)": measure_function_latency(
            lambda: db.get_assessments_by_cluster_ids(all_cluster_ids)
        ),
        "get_current_states_by_cluster_ids (N=50)": measure_function_latency(
            lambda: db.get_current_states_by_cluster_ids(all_cluster_ids)
        ),
        "get_project_matches_by_cluster_ids (N=50)": measure_function_latency(
            lambda: db.get_project_matches_by_cluster_ids(all_cluster_ids)
        ),
        "get_event_clusters_batch (N=50)": measure_function_latency(
            lambda: db.get_event_clusters_batch(all_cluster_ids)
        ),
    }

    # 2. FastAPI Endpoints Benchmark
    print("Benchmarking FastAPI Endpoint Handlers...")
    endpoints = [
        ("GET /inbox?limit=40", lambda: client.get("/inbox?limit=40")),
        ("GET /briefing", lambda: client.get("/briefing")),
        ("GET /search?q=inference&mode=lexical", lambda: client.get("/search?q=inference&mode=lexical")),
        ("GET /projects", lambda: client.get("/projects")),
        (f"GET /projects/{sample_project_id}/intelligence", lambda: client.get(f"/projects/{sample_project_id}/intelligence")),
        ("GET /saved?include_current=true&limit=50", lambda: client.get("/saved?include_current=true&limit=50")),
        ("GET /changes?hours=168&limit=50", lambda: client.get("/changes?hours=168&limit=50")),
        ("GET /runtime", lambda: client.get("/runtime")),
        (f"GET /stories/{sample_cluster_id}", lambda: client.get(f"/stories/{sample_cluster_id}")),
    ]

    api_benchmarks = {}
    for ep_name, ep_fn in endpoints:
        print(f"  Measuring {ep_name}...")
        api_benchmarks[ep_name] = measure_function_latency(ep_fn, samples=50)

    # 3. Measure Frontend Bundle Size Metrics
    dist_dir = os.path.join(REPO_ROOT, "frontend", "dist")
    frontend_bundle = {
        "built": os.path.exists(dist_dir),
        "total_js_bytes": 0,
        "total_css_bytes": 0,
        "total_html_bytes": 0,
        "total_bundle_bytes": 0,
        "assets": []
    }
    if os.path.exists(dist_dir):
        for root, _, files in os.walk(dist_dir):
            for file in files:
                fpath = os.path.join(root, file)
                size = os.path.getsize(fpath)
                rel_path = os.path.relpath(fpath, dist_dir).replace("\\", "/")
                frontend_bundle["total_bundle_bytes"] += size
                if file.endswith(".js"):
                    frontend_bundle["total_js_bytes"] += size
                elif file.endswith(".css"):
                    frontend_bundle["total_css_bytes"] += size
                elif file.endswith(".html"):
                    frontend_bundle["total_html_bytes"] += size
                frontend_bundle["assets"].append({"file": rel_path, "bytes": size})

    # 4. Assemble Report Payload
    report = {
        "meta": {
            "title": "HERMES Phase 16 Performance Evidence",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "git_commit": commit_sha,
            "os": platform.platform(),
            "python_version": platform.python_version(),
            "sqlite_version": sqlite3.sqlite_version,
            "database_baseline_sha256": prod_db_hash,
            "table_record_counts": counts
        },
        "database_batch_queries": db_benchmarks,
        "api_endpoints": api_benchmarks,
        "frontend_bundle": frontend_bundle,
    }

    reports_dir = os.path.join(REPO_ROOT, "reports")
    os.makedirs(reports_dir, exist_ok=True)
    report_path = os.path.join(reports_dir, "phase16_performance.json")

    evidence_dir = os.path.join(REPO_ROOT, "evidence", "phase16")
    os.makedirs(evidence_dir, exist_ok=True)
    evidence_path = os.path.join(evidence_dir, "performance_benchmark.json")

    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    with open(evidence_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    # Cleanup temporary benchmark database
    shutil.rmtree(temp_dir, ignore_errors=True)

    print("\nBenchmark successfully complete!")
    print(f"Report saved to: {report_path}")
    print(f"Evidence saved to: {evidence_path}")
    print("\n--- Summary of Median (p50) & p95 Response Times ---")
    for name, m in api_benchmarks.items():
        print(f"  {name:<45} | Cold: {m['cold_ms']:>6.2f}ms | p50: {m['median_ms']:>6.2f}ms | p95: {m['p95_ms']:>6.2f}ms")

if __name__ == "__main__":
    main()
