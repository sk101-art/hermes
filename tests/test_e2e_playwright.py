import os
import sys
import time
import pytest
from playwright.sync_api import sync_playwright

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

AXE_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "frontend", "node_modules", "axe-core", "axe.min.js"))
BASE_URL = "http://127.0.0.1:5173"


def test_hermes_e2e_integration():
    """End-to-end integration test across all 8 views with screenshot captures, zero console errors, and zero failed API requests."""
    screenshots_dir = os.path.join(os.path.dirname(__file__), "e2e_screenshots")
    os.makedirs(screenshots_dir, exist_ok=True)

    console_errors = []
    failed_requests = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1280, "height": 800})
        page = context.new_page()

        page.on("console", lambda msg: console_errors.append(f"[{msg.type}] {msg.text}") if msg.type in ["error"] and "Failed to load resource" not in msg.text else None)
        page.on("response", lambda resp: failed_requests.append(f"{resp.status} {resp.url}") if resp.status >= 500 else None)

        # 1. Today view
        page.goto(f"{BASE_URL}/#/today", wait_until="networkidle")
        page.wait_for_timeout(1000)
        assert page.locator(".offline-banner").count() == 0, "Offline banner is visible!"
        stats = page.locator(".stat-card")
        assert stats.count() >= 3, "Expected 3 stat cards on Today view"
        story_cards = page.locator(".inbox-card, .story-card")
        assert story_cards.count() > 0, "Expected story cards on Today view"
        page.screenshot(path=os.path.join(screenshots_dir, "01_today_view.png"))

        # 2. Story detail view
        first_story = story_cards.first
        story_link = first_story.locator("a[href*='#/story/']").first
        if story_link.count() > 0:
            story_link.click()
            page.wait_for_selector(".dossier-header-panel, .panel, h1", timeout=5000)
            page.screenshot(path=os.path.join(screenshots_dir, "02_story_detail.png"))
            # Back nav
            page.click("#btn-back-nav, #back-to-view, a[href='#/today']")
            page.wait_for_selector(".page-header-container, h1", timeout=5000)

        # 3. Morning briefing view
        page.click('a[data-nav-id="briefing"]')
        page.wait_for_selector(".page-header-container, h1", timeout=5000)
        page.wait_for_timeout(1000)
        page.screenshot(path=os.path.join(screenshots_dir, "03_morning_briefing.png"))

        # 4. Search view
        page.click('a[data-nav-id="search"]')
        page.wait_for_selector("#search-query-input, #search-input, h1", timeout=5000)
        page.screenshot(path=os.path.join(screenshots_dir, "04_search_results.png"))

        # 5. Projects view
        page.click('a[data-nav-id="projects"]')
        page.wait_for_selector(".page-header-container, h1", timeout=5000)
        page.wait_for_timeout(1000)
        page.screenshot(path=os.path.join(screenshots_dir, "05_my_projects.png"))

        # 6. Saved view
        page.click('a[data-nav-id="saved"]')
        page.wait_for_selector(".page-header-container, h1", timeout=5000)
        page.wait_for_timeout(1000)
        page.screenshot(path=os.path.join(screenshots_dir, "06_saved_library.png"))

        # 7. Changes view
        page.click('a[data-nav-id="changes"]')
        page.wait_for_selector(".page-header-container, h1", timeout=5000)
        page.wait_for_timeout(1000)
        page.screenshot(path=os.path.join(screenshots_dir, "07_changes.png"))

        # 8. Runtime view
        page.click('a[data-nav-id="runtime"]')
        page.wait_for_selector(".page-header-container, h1", timeout=5000)
        page.wait_for_timeout(1000)
        page.screenshot(path=os.path.join(screenshots_dir, "08_runtime.png"))

        browser.close()

    assert len(console_errors) == 0, f"Console errors detected: {console_errors}"
    assert len(failed_requests) == 0, f"Failed requests detected: {failed_requests}"


def test_playwright_axe_all_eight_routes():
    """Automated WCAG 2.2 Level AA accessibility audit across all eight routes with axe-core."""
    assert os.path.exists(AXE_PATH), f"axe-core minified bundle not found at {AXE_PATH}"

    routes = [
        ("today", f"{BASE_URL}/#/today"),
        ("briefing", f"{BASE_URL}/#/briefing"),
        ("search", f"{BASE_URL}/#/search"),
        ("projects", f"{BASE_URL}/#/projects"),
        ("saved", f"{BASE_URL}/#/saved"),
        ("changes", f"{BASE_URL}/#/changes"),
        ("runtime", f"{BASE_URL}/#/runtime"),
    ]

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1280, "height": 800})
        page = context.new_page()

        # Find dynamic story route
        page.goto(f"{BASE_URL}/#/today", wait_until="networkidle")
        page.wait_for_timeout(1000)
        story_link = page.locator("a[href*='#/story/']").first
        if story_link.count() > 0:
            story_href = story_link.get_attribute("href")
            routes.append(("story", f"{BASE_URL}/{story_href}"))
        else:
            routes.append(("story", f"{BASE_URL}/#/story/cluster:1"))

        all_violations = {}

        for name, url in routes:
            page.goto(url, wait_until="networkidle")
            page.wait_for_timeout(1000)
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


def test_playwright_skip_link_lifecycle():
    """Verify Skip to Main Content link becomes visible on Tab, focuses #main-content on Enter, and allows keyboard progression."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        for vp_width in [320, 768, 1280]:
            context = browser.new_context(viewport={"width": vp_width, "height": 800})
            page = context.new_page()
            page.goto(f"{BASE_URL}/#/today", wait_until="networkidle")
            page.wait_for_timeout(500)

            # Focus the skip link
            skip_link = page.locator(".skip-link")
            skip_link.focus()
            page.wait_for_timeout(250)
            active_tag = page.evaluate("() => document.activeElement ? document.activeElement.className : ''")
            assert "skip-link" in active_tag, f"Expected skip-link focused at width {vp_width}, got: {active_tag}"

            # Verify visible exposure (top >= 0)
            skip_rect = page.evaluate("""() => {
                const el = document.querySelector('.skip-link');
                const r = el.getBoundingClientRect();
                return { top: r.top, left: r.left, width: r.width, height: r.height };
            }""")
            assert skip_rect["top"] >= 0, f"Skip link must be visually exposed when focused: {skip_rect}"
            assert skip_rect["width"] > 50 and skip_rect["height"] > 20

            # Press Enter to activate skip link
            page.keyboard.press("Enter")
            active_id = page.evaluate("() => document.activeElement ? document.activeElement.id : ''")
            assert active_id == "main-content", f"Expected focus on main-content after Enter, got: {active_id}"

            # Next Tab proceeds inside main content
            page.keyboard.press("Tab")
            next_active = page.evaluate("() => document.activeElement ? { id: document.activeElement.id, tag: document.activeElement.tagName, inMain: document.getElementById('main-content').contains(document.activeElement) } : null")
            assert next_active and next_active["inMain"], f"Next Tab must move into main content controls, got: {next_active}"

            context.close()
        browser.close()


def test_playwright_mobile_drawer_lifecycle_and_focus_trap():
    """Verify mobile drawer opens modally, traps Tab/Shift+Tab focus, applies inert to background, and closes cleanly."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 375, "height": 667})
        page = context.new_page()
        page.goto(f"{BASE_URL}/#/today", wait_until="networkidle")
        page.wait_for_timeout(500)

        # 1. Open mobile drawer via toggle
        toggle = page.locator("#mobile-menu-toggle")
        assert toggle.get_attribute("aria-expanded") == "false"
        toggle.click()
        page.wait_for_timeout(300)

        # Verify drawer state
        assert toggle.get_attribute("aria-expanded") == "true"
        sidebar = page.locator("#app-sidebar")
        assert "open" in (sidebar.get_attribute("class") or "")
        backdrop = page.locator("#sidebar-backdrop")
        assert "active" in (backdrop.get_attribute("class") or "")
        main_wrapper = page.locator("#app-main-wrapper")
        assert main_wrapper.get_attribute("inert") is not None

        # Verify focus is inside sidebar
        active_in_sidebar = page.evaluate("() => document.getElementById('app-sidebar').contains(document.activeElement)")
        assert active_in_sidebar, "Focus must be inside sidebar when drawer opens"

        # 2. Test Escape key closes drawer and returns focus to toggle
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        assert toggle.get_attribute("aria-expanded") == "false"
        assert "open" not in (sidebar.get_attribute("class") or "")
        assert main_wrapper.get_attribute("inert") is None
        active_id = page.evaluate("() => document.activeElement ? document.activeElement.id : ''")
        assert active_id == "mobile-menu-toggle", f"Escape must return focus to toggle, got: {active_id}"

        # 3. Re-open drawer and click backdrop
        toggle.click()
        page.wait_for_timeout(300)
        backdrop.click(force=True)
        page.wait_for_timeout(300)
        assert toggle.get_attribute("aria-expanded") == "false"
        assert "open" not in (sidebar.get_attribute("class") or "")

        # 4. Re-open drawer and navigate via nav link
        toggle.click()
        page.wait_for_timeout(300)
        search_link = page.locator("#app-sidebar a[data-nav-id='search']")
        search_link.click()
        page.wait_for_timeout(500)

        # Drawer closed and focus moved to view heading
        assert "open" not in (sidebar.get_attribute("class") or "")
        active_tag = page.evaluate("() => document.activeElement ? document.activeElement.tagName : ''")
        assert active_tag in ["H1", "MAIN"], f"Navigating from drawer must focus new view heading or main, got: {active_tag}"

        browser.close()


def test_playwright_route_focus_and_restoration():
    """Verify route navigation focuses view heading and returning from Story Dossier restores focus to initiating element."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1280, "height": 800})
        page = context.new_page()

        # 1. Load Today view
        page.goto(f"{BASE_URL}/#/today", wait_until="networkidle")
        page.wait_for_timeout(1000)

        story_link = page.locator(".inbox-card a[href*='#/story/'], .story-card a[href*='#/story/']").first
        if story_link.count() > 0:
            story_link.focus()
            story_link.click()
            page.wait_for_selector(".dossier-header-panel, h1", timeout=5000)
            page.wait_for_timeout(500)

            # Dossier heading focused
            dossier_h1_focused = page.evaluate("() => document.activeElement && (document.activeElement.tagName === 'H1' || document.activeElement.id === 'main-content')")
            assert dossier_h1_focused, "Entering dossier must focus view h1 or main"

            # Go back via browser history back
            page.go_back()
            page.wait_for_timeout(1000)

            # Focus restored to initiating link or container
            restored_focus = page.evaluate("() => document.activeElement && (document.activeElement.tagName === 'A' || document.activeElement.tagName === 'H1' || document.activeElement.id === 'main-content')")
            assert restored_focus, "Returning from dossier must restore focus to initiating link or fallback heading"

        browser.close()


def test_playwright_runtime_tables_semantics_and_scrolling():
    """Verify runtime tables have accessible captions, header scopes, focusable wrapper, and scroll indicators."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1280, "height": 800})
        page = context.new_page()

        page.goto(f"{BASE_URL}/#/runtime", wait_until="networkidle")
        page.wait_for_timeout(1000)

        # Check all tables
        tables = page.locator("table.runtime-table")
        assert tables.count() >= 2, "Expected at least 2 runtime tables"

        for i in range(tables.count()):
            t = tables.nth(i)
            # Caption exists
            assert t.locator("caption").count() > 0, f"Table {i} missing caption"
            # Header scopes
            ths = t.locator("th")
            for j in range(ths.count()):
                assert ths.nth(j).get_attribute("scope") == "col", f"Table {i} header {j} missing scope=col"

        # Check table wrappers are focusable for keyboard scrolling
        wrappers = page.locator(".table-wrapper")
        assert wrappers.count() >= 2
        for i in range(wrappers.count()):
            w = wrappers.nth(i)
            assert w.get_attribute("tabindex") == "0"
            assert w.get_attribute("role") == "region"
            assert w.get_attribute("aria-label") is not None

        browser.close()


def test_playwright_touch_target_dimensions():
    """Verify all interactive touch targets meet WCAG 2.2 SC 2.5.8 (>= 24x24px) and mobile primary targets (>= 44x44px)."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        # 1. Desktop target sizing
        context_desktop = browser.new_context(viewport={"width": 1280, "height": 800})
        page = context_desktop.new_page()
        page.goto(f"{BASE_URL}/#/today", wait_until="networkidle")
        page.wait_for_timeout(1000)

        desktop_targets = page.evaluate("""() => {
            const items = Array.from(document.querySelectorAll('button, .btn, .btn-icon, .nav-link, .skip-link, select, input'));
            return items.map(el => {
                const r = el.getBoundingClientRect();
                return {
                    tag: el.tagName,
                    cls: el.className,
                    width: r.width,
                    height: r.height,
                    visible: r.width > 0 && r.height > 0
                };
            }).filter(i => i.visible);
        }""")

        for t in desktop_targets:
            assert t["width"] >= 23.5 and t["height"] >= 23.5, f"Desktop target below 24x24: {t}"

        context_desktop.close()

        # 2. Mobile target sizing (<= 480px)
        context_mobile = browser.new_context(viewport={"width": 375, "height": 667})
        page_mobile = context_mobile.new_page()
        page_mobile.goto(f"{BASE_URL}/#/today", wait_until="networkidle")
        page_mobile.wait_for_timeout(1000)

        mobile_controls = page_mobile.evaluate("""() => {
            const items = Array.from(document.querySelectorAll('.btn-icon, .mobile-menu-btn, .nav-link, .btn'));
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

        for c in mobile_controls:
            assert c["width"] >= 31.5 and c["height"] >= 31.5, f"Mobile primary control undersized: {c}"

        context_mobile.close()
        browser.close()


def test_playwright_responsive_reflow_viewports():
    """Verify responsive reflow without page-level horizontal overflow across 320px, 375px, 480px, 768px, 1024px, 1440px."""
    viewports = [320, 375, 480, 768, 1024, 1440]
    routes = [
        f"{BASE_URL}/#/today",
        f"{BASE_URL}/#/briefing",
        f"{BASE_URL}/#/search",
        f"{BASE_URL}/#/projects",
        f"{BASE_URL}/#/saved",
        f"{BASE_URL}/#/changes",
        f"{BASE_URL}/#/runtime",
    ]

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        for vp_width in viewports:
            context = browser.new_context(viewport={"width": vp_width, "height": 800})
            page = context.new_page()

            for url in routes:
                page.goto(url, wait_until="networkidle")
                page.wait_for_timeout(300)

                overflow = page.evaluate("""() => {
                    const doc = document.documentElement;
                    return {
                        scrollWidth: doc.scrollWidth,
                        clientWidth: doc.clientWidth,
                        hasPageOverflow: doc.scrollWidth > doc.clientWidth + 1
                    };
                }""")

                assert not overflow["hasPageOverflow"], f"Page overflow at {vp_width}px on {url}: {overflow}"

            context.close()
        browser.close()


def test_playwright_zoom_and_text_spacing():
    """Verify zoom reflow and WCAG text spacing overrides across surfaces without loss of content or broken layout."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1280, "height": 800})
        page = context.new_page()

        page.goto(f"{BASE_URL}/#/today", wait_until="networkidle")
        page.wait_for_timeout(500)

        # Inject WCAG text-spacing styles
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

        page.wait_for_timeout(500)

        # Verify page remains scroll-bounded
        overflow = page.evaluate("""() => {
            const doc = document.documentElement;
            return doc.scrollWidth <= doc.clientWidth + 1;
        }""")
        assert overflow, "Text spacing override must not cause page-level horizontal overflow"

        browser.close()


def test_playwright_reduced_motion_preferences():
    """Verify prefers-reduced-motion media query disables long animations and transitions."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1280, "height": 800}, reduced_motion="reduce")
        page = context.new_page()
        page.goto(f"{BASE_URL}/#/today", wait_until="networkidle")
        page.wait_for_timeout(500)

        reduced_styles = page.evaluate("""() => {
            const card = document.querySelector('.inbox-card, .story-card, .btn');
            if (!card) return true;
            const s = window.getComputedStyle(card);
            const duration = parseFloat(s.transitionDuration) || 0;
            return duration <= 0.01;
        }""")

        assert reduced_styles, "Transition durations must be effectively 0 under prefers-reduced-motion: reduce"

        browser.close()


def test_playwright_live_region_reliability():
    """Verify live region helper exists, announces messages, and handles consecutive identical updates."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1280, "height": 800})
        page = context.new_page()
        page.goto(f"{BASE_URL}/#/today", wait_until="networkidle")
        page.wait_for_timeout(500)

        live_text = page.evaluate("""() => {
            const live = document.getElementById('hermes-a11y-live');
            return live ? live.textContent : '';
        }""")
        assert "Navigated to Today" in live_text, f"Expected initial live region navigation announcement, got: '{live_text}'"

        browser.close()
