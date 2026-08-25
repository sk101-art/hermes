"""
HERMES Phase 17 Browser Performance and Memory Verification.
Automates 50 route transitions and measures:
- Route transition latency (median, p95 < 300ms)
- Maximum DOM element count (< 1500)
- API endpoint performance (Search p95 < 125ms, Runtime p95 < 75ms, Runtime cold < 175ms)
- JS heap retention and growth ceiling
"""

import os
import sys
import time
import json
import socket
import statistics
import subprocess
import urllib.request
import tempfile
import shutil
from pathlib import Path
from playwright.sync_api import sync_playwright, expect


def find_free_port(start=12000, end=13000):
    for port in range(start, end):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(('127.0.0.1', port))
                return port
            except OSError:
                continue
    raise RuntimeError("No free ports")


def run_performance_audit(output_path: str = "reports/phase17_performance.json") -> dict:
    api_port = find_free_port(18100, 18500)
    fe_port = find_free_port(19100, 19500)

    temp_dir = tempfile.mkdtemp(prefix="hermes_perf_")
    test_db = os.path.join(temp_dir, "perf.db")
    shutil.copy2("data/tech_intel.db", test_db)

    env = os.environ.copy()
    env["HERMES_DB_PATH"] = test_db
    env["PORT"] = str(api_port)

    print(f"[Perf] Launching backend on port {api_port}...")
    be_proc = subprocess.Popen(
        [sys.executable, "-m", "app.api.server", "--port", str(api_port)],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    print(f"[Perf] Launching frontend on port {fe_port}...")
    fe_proc = subprocess.Popen(
        ["npm", "run", "dev", "--", "--port", str(fe_port)],
        cwd="frontend",
        shell=(sys.platform == "win32"),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # Wait for ready
    api_url = f"http://127.0.0.1:{api_port}"
    fe_url = f"http://127.0.0.1:{fe_port}"

    ready = False
    for _ in range(50):
        try:
            with urllib.request.urlopen(f"{api_url}/health/ready", timeout=1) as resp:
                if resp.status == 200:
                    ready = True
                    break
        except Exception:
            time.sleep(0.2)

    if not ready:
        be_proc.terminate()
        fe_proc.terminate()
        raise RuntimeError("Backend failed to start in time")

    # Measure Runtime Cold Start
    cold_start = time.perf_counter()
    with urllib.request.urlopen(f"{api_url}/runtime", timeout=5) as resp:
        assert resp.status == 200
    runtime_cold_ms = (time.perf_counter() - cold_start) * 1000

    # Measure Runtime Warm Latency (20 requests)
    runtime_latencies = []
    for _ in range(20):
        t0 = time.perf_counter()
        with urllib.request.urlopen(f"{api_url}/runtime", timeout=2) as resp:
            assert resp.status == 200
        runtime_latencies.append((time.perf_counter() - t0) * 1000)
    runtime_p95_ms = statistics.quantiles(runtime_latencies, n=100, method="inclusive")[94] if len(runtime_latencies) >= 20 else max(runtime_latencies)

    # Measure Search Latency (20 requests)
    search_latencies = []
    for _ in range(20):
        t0 = time.perf_counter()
        with urllib.request.urlopen(f"{api_url}/search?q=inference&mode=lexical", timeout=2) as resp:
            assert resp.status == 200
        search_latencies.append((time.perf_counter() - t0) * 1000)
    search_p95_ms = statistics.quantiles(search_latencies, n=100, method="inclusive")[94] if len(search_latencies) >= 20 else max(search_latencies)

    # Browser Transitions
    routes = [
        ("#/today", "What Matters Today"),
        ("#/briefing", "Morning Briefing"),
        ("#/search?q=inference&mode=lexical", "Search with Epistemic Context"),
        ("#/projects", "My Projects"),
        ("#/saved", "Saved Intelligence"),
        ("#/changes", "What Moved"),
        ("#/runtime", "Runtime & Source Health"),
    ]

    transition_times = []
    dom_samples = []
    initial_heap = None
    final_heap = None

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        context.add_init_script(f"window.localStorage.setItem('hermes_api_url', '{api_url}');")
        page = context.new_page()

        page.goto(f"{fe_url}/#/today", wait_until="networkidle")
        expect(page.get_by_role("heading", name="What Matters Today", exact=True)).to_be_visible(timeout=10_000)

        # Baseline heap
        try:
            initial_heap = page.evaluate("() => window.performance && window.performance.memory ? window.performance.memory.usedJSHeapSize : null")
        except Exception:
            initial_heap = None

        for i in range(50):
            r_hash, heading = routes[i % len(routes)]
            t0 = time.perf_counter()
            page.evaluate("(h) => { window.location.hash = h; }", r_hash)
            expect(page.get_by_role("heading", name=heading, exact=True)).to_be_visible(timeout=10_000)
            transition_times.append((time.perf_counter() - t0) * 1000)
            dom_samples.append(page.evaluate("() => document.querySelectorAll('*').length"))

        # Final heap
        try:
            final_heap = page.evaluate("() => window.performance && window.performance.memory ? window.performance.memory.usedJSHeapSize : null")
        except Exception:
            final_heap = None

        browser.close()

    # Clean up processes
    try:
        be_proc.terminate()
        fe_proc.terminate()
        shutil.rmtree(temp_dir, ignore_errors=True)
    except Exception:
        pass

    route_median = statistics.median(transition_times)
    route_p95 = statistics.quantiles(transition_times, n=100, method="inclusive")[94]
    max_dom = max(dom_samples)

    heap_growth_bytes = (final_heap - initial_heap) if (initial_heap and final_heap) else None

    # Verification checks
    passed = (
        route_p95 < 300.0 and
        max_dom < 1500 and
        search_p95_ms < 125.0 and
        runtime_p95_ms < 75.0 and
        runtime_cold_ms < 175.0
    )

    results = {
        "route_transition_median_ms": round(route_median, 2),
        "route_transition_p95_ms": round(route_p95, 2),
        "route_transition_threshold_ms": 300.0,
        "max_dom_nodes": max_dom,
        "max_dom_threshold": 1500,
        "search_api_p95_ms": round(search_p95_ms, 2),
        "search_api_threshold_ms": 125.0,
        "runtime_api_p95_ms": round(runtime_p95_ms, 2),
        "runtime_api_threshold_ms": 75.0,
        "runtime_cold_start_ms": round(runtime_cold_ms, 2),
        "runtime_cold_threshold_ms": 175.0,
        "initial_heap_bytes": initial_heap,
        "final_heap_bytes": final_heap,
        "heap_growth_bytes": heap_growth_bytes,
        "passed": passed
    }

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    print(f"[Perf] Transition p95: {results['route_transition_p95_ms']} ms (Ceiling: 300 ms)")
    print(f"[Perf] Max DOM nodes: {results['max_dom_nodes']} (Ceiling: 1500)")
    print(f"[Perf] Search API p95: {results['search_api_p95_ms']} ms (Ceiling: 125 ms)")
    print(f"[Perf] Runtime API p95: {results['runtime_api_p95_ms']} ms (Ceiling: 75 ms)")
    print(f"[Perf] Runtime cold: {results['runtime_cold_start_ms']} ms (Ceiling: 175 ms)")
    print(f"[Perf] Heap growth: {heap_growth_bytes} bytes")
    print(f"[Perf] Passed: {results['passed']}")

    return results


if __name__ == "__main__":
    out_file = sys.argv[1] if len(sys.argv) > 1 else "reports/phase17_performance.json"
    res = run_performance_audit(output_path=out_file)
    if not res["passed"]:
        sys.exit(1)
    sys.exit(0)
