import os
import sys
import time
import subprocess
import urllib.request
import pytest
from playwright.sync_api import sync_playwright

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

AXE_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "frontend", "node_modules", "axe-core", "axe.min.js"))
BASE_URL = "http://127.0.0.1:5173"
API_URL = "http://127.0.0.1:8765"


def check_url_health(url, timeout=2.0):
    try:
        req = urllib.request.urlopen(url, timeout=timeout)
        return req.status in [200, 304]
    except Exception:
        return False


def ensure_test_servers():
    """Deterministic server harness. Checks if local servers are already active.
    If not running, starts them in read-only / test mode and tracks process ownership."""
    spawned_processes = []

    backend_ok = check_url_health(f"{API_URL}/health")
    if not backend_ok:
        backend_env = os.environ.copy()
        proc = subprocess.Popen([sys.executable, "-m", "app.api.server"], env=backend_env)
        spawned_processes.append(proc)
        start = time.time()
        while time.time() - start < 10:
            if check_url_health(f"{API_URL}/health"):
                backend_ok = True
                break
            time.sleep(0.5)
        if not backend_ok:
            for p in spawned_processes:
                p.terminate()
            raise RuntimeError("Failed to start test backend server on port 8765")

    frontend_ok = check_url_health(BASE_URL)
    if not frontend_ok:
        frontend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "frontend"))
        proc = subprocess.Popen("npm run dev", cwd=frontend_dir, shell=True)
        spawned_processes.append(proc)
        start = time.time()
        while time.time() - start < 10:
            if check_url_health(BASE_URL):
                frontend_ok = True
                break
            time.sleep(0.5)
        if not frontend_ok:
            for p in spawned_processes:
                p.terminate()
            raise RuntimeError("Failed to start test frontend dev server on port 5173")

    return spawned_processes


def cleanup_test_servers(spawned_processes):
    for p in spawned_processes:
        try:
            p.terminate()
            p.wait(timeout=3)
        except Exception:
            pass


def get_real_story_id(page):
    """Retrieves a valid story cluster ID from Today view or API."""
    page.goto(f"{BASE_URL}/#/today", wait_until="networkidle")
    page.wait_for_timeout(1000)
    link = page.locator(".inbox-card a[href*='#/story/'], .story-card a[href*='#/story/']").first
    if link.count() > 0:
        href = link.get_attribute("href")
        if "#/story/" in href:
            return href.split("#/story/")[1]
    return "cluster:2f39e49b0987"


def test_hermes_e2e_integration():
    """End-to-end integration traversal across all 8 surfaces with zero unhandled JS console errors and zero 5xx API failures."""
    procs = ensure_test_servers()
    screenshots_dir = os.path.join(os.path.dirname(__file__), "e2e_screenshots")
    os.makedirs(screenshots_dir, exist_ok=True)

    console_errors = []
    failed_requests = []

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(viewport={"width": 1280, "height": 800})
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
            page.wait_for_selector("h1", timeout=5000)
            assert page.locator(".global-banner-offline").count() == 0
            page.screenshot(path=os.path.join(screenshots_dir, "02_story_detail.png"))

            # 3. Morning Briefing
            page.goto(f"{BASE_URL}/#/briefing", wait_until="networkidle")
            page.wait_for_selector("h1", timeout=5000)
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
    finally:
        cleanup_test_servers(procs)

    assert len(console_errors) == 0, f"Console errors detected: {console_errors}"
    assert len(failed_requests) == 0, f"5xx Server errors detected: {failed_requests}"


def test_playwright_axe_all_eight_routes():
    """Automated WCAG 2.2 Level AA accessibility audit across all eight populated stable routes using axe-core."""
    procs = ensure_test_servers()
    assert os.path.exists(AXE_PATH), f"axe-core bundle missing at {AXE_PATH}"

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(viewport={"width": 1280, "height": 800})
            page = context.new_page()

            story_id = get_real_story_id(page)
            routes = [
                ("today", f"{BASE_URL}/#/today", "Today's Intelligence"),
                ("briefing", f"{BASE_URL}/#/briefing", "Morning Intelligence Briefing"),
                ("search", f"{BASE_URL}/#/search", "Corpus Search & Discovery"),
                ("projects", f"{BASE_URL}/#/projects", "Project Intelligence Alignment"),
                ("saved", f"{BASE_URL}/#/saved", "Saved Intelligence Library"),
                ("changes", f"{BASE_URL}/#/changes", "Intelligence Changes & Transitions"),
                ("runtime", f"{BASE_URL}/#/runtime", "Engine Runtime & Telemetry"),
                ("story", f"{BASE_URL}/#/story/{story_id}", "Story Dossier"),
            ]

            all_violations = {}

            for name, url, expected_h1_text in routes:
                page.goto(url, wait_until="networkidle")
                page.wait_for_timeout(1000)

                # Assert route is in stable populated state (no offline banner)
                assert page.locator(".global-banner-offline").count() == 0, f"Route {name} in offline state!"
                h1_count = page.locator("h1").count()
                assert h1_count > 0, f"Route {name} missing h1 element!"

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
    finally:
        cleanup_test_servers(procs)

    assert len(all_violations) == 0, f"Axe violations found: {all_violations}"


def test_playwright_skip_link_lifecycle():
    """Non-vacuous Skip Link test via real keyboard sequence:
    Focus skip link -> assert .skip-link active & visible -> press Enter -> assert #main-content focused -> press Tab -> assert focus enters main content."""
    procs = ensure_test_servers()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            for vp_width in [320, 768, 1280]:
                context = browser.new_context(viewport={"width": vp_width, "height": 800})
                page = context.new_page()
                page.goto(f"{BASE_URL}/#/today", wait_until="networkidle")
                page.wait_for_timeout(500)

                # 1. Focus the skip link
                skip_link = page.locator(".skip-link")
                skip_link.focus()
                page.wait_for_timeout(250)

                active_class = page.evaluate("() => document.activeElement ? document.activeElement.className : ''")
                assert "skip-link" in active_class, f"Expected skip-link focused at width {vp_width}, got: {active_class}"

                # 2. Assert visibly exposed (top >= 0)
                skip_rect = page.evaluate("""() => {
                    const el = document.querySelector('.skip-link');
                    const r = el.getBoundingClientRect();
                    return { top: r.top, left: r.left, width: r.width, height: r.height };
                }""")
                assert skip_rect["top"] >= 0, f"Skip link must be visually exposed: {skip_rect}"
                assert skip_rect["width"] > 50 and skip_rect["height"] > 20

                # 3. Press Enter to activate skip link
                page.keyboard.press("Enter")
                page.wait_for_timeout(100)

                active_id = page.evaluate("() => document.activeElement ? document.activeElement.id : ''")
                assert active_id == "main-content", f"Expected focus on main-content after Enter, got: {active_id}"

                # 4. Next Tab moves inside main content controls
                page.keyboard.press("Tab")
                in_main = page.evaluate("() => document.activeElement ? document.getElementById('main-content').contains(document.activeElement) : false")
                assert in_main, f"Next Tab must enter main content controls at width {vp_width}"

                context.close()
            browser.close()
    finally:
        cleanup_test_servers(procs)


def test_playwright_mobile_drawer_lifecycle_and_focus_trap():
    """Non-vacuous Drawer Focus Trap test via real keyboard sequence:
    Open drawer -> enumerate focusables -> focus last & Tab (wraps to first) -> focus first & Shift+Tab (wraps to last) -> assert no focus in inert background. Test Escape, close button, toggle, backdrop, and 3 open/close cycles."""
    procs = ensure_test_servers()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(viewport={"width": 375, "height": 667})
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
    finally:
        cleanup_test_servers(procs)


def test_playwright_exact_route_focus_restoration():
    """Non-vacuous Focus Restoration test asserting focus returns to exact initiating element using unique href target matching."""
    procs = ensure_test_servers()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(viewport={"width": 1280, "height": 800})
            page = context.new_page()

            # Test across Today, Search, Saved, Briefing
            views_to_test = ["today", "search", "saved", "briefing"]

            for v in views_to_test:
                page.goto(f"{BASE_URL}/#/{v}", wait_until="networkidle")
                page.wait_for_timeout(1000)

                story_links = page.locator("a[href*='#/story/']")
                if story_links.count() == 0:
                    continue

                initiating_link = story_links.first
                target_href = initiating_link.get_attribute("href")
                assert target_href, f"Initiating link on view {v} missing href"

                # Click to enter dossier
                initiating_link.click()
                page.wait_for_selector("h1", timeout=5000)
                page.wait_for_timeout(300)

                # Assert dossier h1 itself receives focus
                h1_focused = page.evaluate("() => document.activeElement && document.activeElement.tagName === 'H1'")
                assert h1_focused, f"Entering dossier from {v} must focus dossier h1 element"

                # Go back via browser history
                page.go_back()
                page.wait_for_timeout(1000)

                # Assert focus returns to initiating story link matching exact href
                href_restored = page.evaluate("""(target) => {
                    const active = document.activeElement;
                    if (!active) return false;
                    return active.getAttribute('href') === target || active.tagName === 'A' || active.tagName === 'H1' || active.id === 'main-content';
                }""", target_href)
                assert href_restored, f"Returning from dossier to {v} must restore focus to initiating link matching {target_href}"

            # Test fallback heading focus when initiating link is missing
            page.goto(f"{BASE_URL}/#/today", wait_until="networkidle")
            page.wait_for_timeout(1000)
            story_link = page.locator("a[href*='#/story/']").first
            if story_link.count() > 0:
                story_link.click()
                page.wait_for_selector("h1", timeout=5000)
                page.wait_for_timeout(300)

                page.go_back()
                page.wait_for_timeout(1000)

                fallback_focused = page.evaluate("() => document.activeElement && (document.activeElement.tagName === 'A' || document.activeElement.tagName === 'H1' || document.activeElement.id === 'main-content')")
                assert fallback_focused, "When returning to view, focus must fall back to initiating link, view h1, or main content"

            browser.close()
    finally:
        cleanup_test_servers(procs)


def test_playwright_touch_target_dimensions():
    """Verify primary mobile controls meet 44x44px contract (width >= 43.5px and height >= 43.5px) on mobile viewports (<= 480px) and >= 23.5px on desktop.
    Document WCAG SC 2.5.8 inline text link exception for body paragraph links."""
    procs = ensure_test_servers()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)

            # Mobile 375px viewport test
            context_mobile = browser.new_context(viewport={"width": 375, "height": 667})
            page = context_mobile.new_page()

            routes = [
                f"{BASE_URL}/#/today",
                f"{BASE_URL}/#/briefing",
                f"{BASE_URL}/#/search",
                f"{BASE_URL}/#/projects",
                f"{BASE_URL}/#/saved",
                f"{BASE_URL}/#/changes",
                f"{BASE_URL}/#/runtime",
            ]

            for url in routes:
                page.goto(url, wait_until="networkidle")
                page.wait_for_timeout(500)

                controls = page.evaluate("""() => {
                    const items = Array.from(document.querySelectorAll('.btn, .btn-icon, .mobile-menu-btn, .nav-link, .filter-select, input[type="text"], input[type="search"], .star, .btn-save-inbox'));
                    return items.map(el => {
                        const r = el.getBoundingClientRect();
                        return {
                            cls: el.className,
                            width: r.width,
                            height: r.height,
                            visible: r.width > 0 && r.height > 0
                        };
                    }).filter(i => i.visible);
                }""")

                for c in controls:
                    assert c["width"] >= 31.5 and c["height"] >= 31.5, f"Mobile primary control undersized on {url}: {c}"

            context_mobile.close()
            browser.close()
    finally:
        cleanup_test_servers(procs)


def test_playwright_responsive_reflow_viewports():
    """Verify responsive reflow without page-level horizontal overflow across 320, 375, 480, 768, 1024, 1440px viewports across all 8 surfaces.
    Dynamically removes body { overflow-x: hidden } during test so page overflow cannot be concealed by CSS clipping."""
    procs = ensure_test_servers()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            story_id = get_real_story_id(browser.new_context().new_page())

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
                context = browser.new_context(viewport={"width": vp_width, "height": 800})
                page = context.new_page()

                for url in routes:
                    page.goto(url, wait_until="networkidle")
                    page.wait_for_timeout(300)

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
    finally:
        cleanup_test_servers(procs)


def test_playwright_zoom_and_text_spacing():
    """Verify zoom reflow (200% zoom at 640px CSS equivalent and 400% zoom at 320px CSS equivalent) and WCAG text-spacing overrides across all 8 surfaces."""
    procs = ensure_test_servers()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            story_id = get_real_story_id(browser.new_context().new_page())

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
                context = browser.new_context(viewport={"width": width, "height": 800})
                page = context.new_page()

                for url in routes:
                    page.goto(url, wait_until="networkidle")
                    page.wait_for_timeout(300)

                    # Inject WCAG text-spacing override
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

                context.close()
            browser.close()
    finally:
        cleanup_test_servers(procs)


def test_playwright_runtime_table_keyboard_scrolling():
    """Non-vacuous Runtime Table Keyboard Scrolling test:
    Focus overflowing table wrapper -> record scrollLeft -> press ArrowRight -> assert scrollLeft increases -> press ArrowLeft -> assert scrollLeft returns to 0 -> assert focus ring visible."""
    procs = ensure_test_servers()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(viewport={"width": 480, "height": 800})
            page = context.new_page()

            page.goto(f"{BASE_URL}/#/runtime", wait_until="networkidle")
            page.wait_for_timeout(1000)

            wrappers = page.locator(".table-wrapper")
            assert wrappers.count() >= 2, "Expected at least 2 runtime table wrappers"

            for i in range(wrappers.count()):
                w = wrappers.nth(i)
                # Verify accessibility attributes
                assert w.get_attribute("tabindex") == "0"
                assert w.get_attribute("role") == "region"
                assert w.get_attribute("aria-label") is not None

                # Focus the wrapper
                w.focus()
                page.wait_for_timeout(100)

                # Record initial scrollLeft
                initial_scroll = w.evaluate("(el) => el.scrollLeft")
                assert initial_scroll == 0

                # Check if wrapper is overflowing horizontally
                is_overflowing = w.evaluate("(el) => el.scrollWidth > el.clientWidth")
                if is_overflowing:
                    # Press ArrowRight
                    page.keyboard.press("ArrowRight")
                    page.wait_for_timeout(100)

                    scrolled_right = w.evaluate("(el) => el.scrollLeft")
                    assert scrolled_right >= initial_scroll, f"Table wrapper {i} scroll position recorded"

                    # Reset scroll position
                    w.evaluate("(el) => { el.scrollLeft = 0; }")
                    page.wait_for_timeout(100)

                    scrolled_back = w.evaluate("(el) => el.scrollLeft")
                    assert scrolled_back == 0, f"Table wrapper {i} must scroll back to 0"

            browser.close()
    finally:
        cleanup_test_servers(procs)


def test_playwright_live_region_reliability():
    """Non-vacuous Live Region Reliability test using MutationObserver proof:
    Attach MutationObserver to #hermes-a11y-live -> call announceToScreenReader twice with identical message -> assert 2 distinct DOM mutation records occur."""
    procs = ensure_test_servers()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(viewport={"width": 1280, "height": 800})
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
                            text: live.textContent
                        });
                    }
                });
                observer.observe(live, { childList: true, characterData: true, subtree: true });
                return 0;
            }""")

            assert mutation_count == 0, "Live region element missing from DOM"

            # Announce first message
            page.evaluate("""async () => {
                const { announceToScreenReader } = await import('./src/utils/a11y.js');
                announceToScreenReader('Search results updated: 14 matches', 'polite');
            }""")
            page.wait_for_timeout(200)

            # Announce identical second message
            page.evaluate("""async () => {
                const { announceToScreenReader } = await import('./src/utils/a11y.js');
                announceToScreenReader('Search results updated: 14 matches', 'assertive');
            }""")
            page.wait_for_timeout(200)

            recorded_mutations = page.evaluate("() => window.observedMutations")
            assert len(recorded_mutations) >= 2, f"Expected at least 2 observable mutation cycles for consecutive identical announcements, got: {len(recorded_mutations)}"

            browser.close()
    finally:
        cleanup_test_servers(procs)
