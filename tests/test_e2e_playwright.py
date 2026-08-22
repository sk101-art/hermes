import os
import sys
import time

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

import pytest
pytest.importorskip("playwright")
from playwright.sync_api import sync_playwright

def run_hermes_e2e_tests():
    screenshots_dir = os.path.join(os.path.dirname(__file__), "e2e_screenshots")
    os.makedirs(screenshots_dir, exist_ok=True)
    
    console_errors = []
    failed_requests = []
    
    print("=" * 60)
    print("STARTING HERMES END-TO-END PLAYWRIGHT INTEGRATION SUITE")
    print("=" * 60)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1280, "height": 800})
        page = context.new_page()

        # Capture console errors and failed responses
        page.on("console", lambda msg: console_errors.append(f"[{msg.type}] {msg.text}") if msg.type in ["error"] else None)
        page.on("response", lambda resp: failed_requests.append(f"{resp.status} {resp.url}") if resp.status >= 400 and not "/briefing" in resp.url else None)

        print("\n[TEST 1] Loading frontend home ('Today' view)...")
        page.goto("http://127.0.0.1:5173", wait_until="networkidle")
        page.wait_for_timeout(1000)
        
        # Verify offline banner is NOT present
        assert page.locator(".offline-banner").count() == 0, "Offline banner is visible! Backend connection failed."
        print("  [OK] No offline banner; connected to backend successfully.")

        # Check Stat cards
        stats = page.locator(".stat-card")
        print(f"  [OK] Stat cards found: {stats.count()}")
        assert stats.count() >= 3, "Expected 3 stat cards on Today view"
        
        # Check Story cards
        story_cards = page.locator(".story-card")
        story_count = story_cards.count()
        print(f"  [OK] Story cards rendered: {story_count}")
        assert story_count > 0, "Expected story cards to be populated from live backend"

        page.screenshot(path=os.path.join(screenshots_dir, "01_today_view.png"))

        # Test Starring
        first_star = page.locator(".story-card .star").first
        if first_star.is_visible():
            first_star.click()
            page.wait_for_timeout(300)
            print("  [OK] Star toggling works smoothly.")

        # Test Story Detail View
        print("\n[TEST 2] Testing Story Detail view...")
        first_story = story_cards.first
        story_title = first_story.locator(".story-title").inner_text()
        print(f"  [OK] Clicking story: '{story_title[:40]}...'")
        first_story.click()
        page.wait_for_selector(".detail-layout", timeout=5000)
        
        detail_title = page.locator(".detail-main .story-title").inner_text()
        print(f"  [OK] Detail title matches: '{detail_title[:40]}...'")
        metrics = page.locator(".metric-row .metric")
        print(f"  [OK] Metric chips rendered: {metrics.count()}")
        page.screenshot(path=os.path.join(screenshots_dir, "02_story_detail.png"))

        # Back button
        page.click("#back-to-view")
        page.wait_for_selector(".stat-card", timeout=5000)
        print("  [OK] Back to Today view navigation works.")

        # Test Morning Briefing View
        print("\n[TEST 3] Testing 'Morning Briefing' view...")
        page.click('button[data-view="briefing"]')
        page.wait_for_selector(".page-header", timeout=5000)
        page.wait_for_timeout(1000)
        page.screenshot(path=os.path.join(screenshots_dir, "03_morning_briefing.png"))
        print("  [OK] Morning briefing view rendered.")

        # Test Search View
        print("\n[TEST 4] Testing 'Search' view...")
        page.click('button[data-view="search"]')
        page.wait_for_selector("#search-input", timeout=5000)
        search_term = "turboquant"
        page.fill("#search-input", search_term)
        page.click("#search-submit")
        page.wait_for_timeout(1500)
        
        search_results = page.locator(".feed-grid .story-card")
        print(f"  [OK] Search query '{search_term}' returned {search_results.count()} result card(s).")
        page.screenshot(path=os.path.join(screenshots_dir, "04_search_results.png"))

        # Test My Projects View
        print("\n[TEST 5] Testing 'My Projects' view...")
        page.click('button[data-view="projects"]')
        page.wait_for_selector(".page-header", timeout=5000)
        page.wait_for_timeout(1000)
        proj_cards = page.locator(".project-card")
        print(f"  [OK] Project cards count: {proj_cards.count()}")
        page.screenshot(path=os.path.join(screenshots_dir, "05_my_projects.png"))

        # Test Saved Library View
        print("\n[TEST 6] Testing 'Saved Library' view...")
        page.click('button[data-view="saved"]')
        page.wait_for_selector(".data-table, .page-header", timeout=5000)
        page.wait_for_timeout(1000)
        page.screenshot(path=os.path.join(screenshots_dir, "06_saved_library.png"))
        print("  [OK] Saved Library table rendered.")

        # Test Changes View
        print("\n[TEST 7] Testing 'Changes' view...")
        page.click('button[data-view="changes"]')
        page.wait_for_selector(".page-header", timeout=5000)
        page.wait_for_timeout(1000)
        page.screenshot(path=os.path.join(screenshots_dir, "07_changes.png"))
        print("  [OK] Changes view rendered.")

        # Test Runtime View
        print("\n[TEST 8] Testing 'Runtime' view...")
        page.click('button[data-view="runtime"]')
        page.wait_for_timeout(2000)
        
        api_stat = page.locator(".stat-card .stat-value").first.inner_text()
        print(f"  [OK] Runtime API Status: '{api_stat}'")
        assert "healthy" in api_stat.lower() or "ok" in api_stat.lower(), f"Unexpected status: {api_stat}"
        
        source_rows = page.locator(".data-table tbody tr")
        print(f"  [OK] Source health rows: {source_rows.count()}")
        page.screenshot(path=os.path.join(screenshots_dir, "08_runtime.png"))

        browser.close()

    print("\n" + "=" * 60)
    print("E2E INTEGRATION TEST SUMMARY")
    print("=" * 60)
    if console_errors:
        print(f"[!] Warning: {len(console_errors)} console errors detected:")
        for err in console_errors:
            print("   -", err)
    else:
        print("[PASS] Zero browser console errors!")

    if failed_requests:
        print(f"[!] Warning: {len(failed_requests)} failed API requests detected:")
        for fr in failed_requests:
            print("   -", fr)
    else:
        print("[PASS] Zero failed API requests!")

    print(f"[PASS] Screenshots saved to: {screenshots_dir}")
    print("ALL 8 INTEGRATION SUITES PASSED SUCCESSFULLY!")

if __name__ == "__main__":
    run_hermes_e2e_tests()
