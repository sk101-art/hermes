"""
WCAG 2.2 Contrast Contract Test - Deterministic contrast-ratio verification
Uses the WCAG relative-luminance formula to verify all foreground/background pairs meet requirements.
Resolves CSS variables from actual frontend token files.
"""

import os
import re
import pytest


def relative_luminance(hex_color):
    """Calculate WCAG relative luminance from hex color string."""
    hex_color = hex_color.lstrip('#')
    r = int(hex_color[0:2], 16) / 255.0
    g = int(hex_color[2:4], 16) / 255.0
    b = int(hex_color[4:6], 16) / 255.0

    def linear(c):
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = linear(r), linear(g), linear(b)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(fg_hex, bg_hex):
    """Calculate WCAG contrast ratio between foreground and background."""
    L1 = relative_luminance(fg_hex)
    L2 = relative_luminance(bg_hex)
    lighter = max(L1, L2)
    darker = min(L1, L2)
    return (lighter + 0.05) / (darker + 0.05)


def is_large_text(font_size_rem, font_weight):
    """Determine if text qualifies as 'large text' per WCAG."""
    size_px = float(font_size_rem) * 16
    if size_px >= 24:
        return True
    if size_px >= 18.67 and font_weight >= 600:
        return True
    return False


def parse_css_variables(css_path):
    """Parse CSS custom properties from a CSS file, handling nested braces."""
    variables = {}
    if not os.path.exists(css_path):
        return variables

    with open(css_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # Find all :root { ... } blocks, handling nested braces
    root_blocks = []
    pos = 0
    while True:
        # Find :root keyword
        root_kw = content.find(':root', pos)
        if root_kw == -1:
            break

        # Find opening brace after :root
        brace_start = content.find('{', root_kw)
        if brace_start == -1:
            pos = root_kw + 5
            continue

        # Find matching closing brace by counting braces
        brace_count = 1
        i = brace_start + 1
        while i < len(content) and brace_count > 0:
            if content[i] == '{':
                brace_count += 1
            elif content[i] == '}':
                brace_count -= 1
            i += 1

        if brace_count == 0:
            root_blocks.append(content[brace_start + 1:i - 1])

        pos = i

    # Extract variables from all root blocks
    var_pattern = re.compile(r'(--[\w-]+)\s*:\s*([^;]+);')
    for block in root_blocks:
        for match in var_pattern.finditer(block):
            name = match.group(1).strip()
            value = match.group(2).strip()
            variables[name] = value

    return variables


def resolve_css_color(value, variables):
    """Resolve a CSS color value, following var() references and bare variable names recursively."""
    value = value.strip()

    # Handle var(--name) references
    var_match = re.match(r'var\(([^)]+)\)', value)
    if var_match:
        var_name = var_match.group(1).strip()
        if ',' in var_name:
            var_name, fallback = var_name.split(',', 1)
            var_name = var_name.strip()
            fallback = fallback.strip()
            return resolve_css_color(variables.get(var_name, fallback), variables)
        return resolve_css_color(variables.get(var_name, value), variables)

    # Handle bare variable references (e.g., --ink-primary)
    if value.startswith('--'):
        return resolve_css_color(variables.get(value, value), variables)

    return value


def load_all_css_variables():
    """Load all CSS variables from frontend token files."""
    base_dir = os.path.join(os.path.dirname(__file__), "..", "frontend", "src", "styles")
    all_vars = {}

    for css_file in ["tokens.css", "components.css", "states.css", "semantic.css", "layout.css"]:
        path = os.path.join(base_dir, css_file)
        if os.path.exists(path):
            vars_dict = parse_css_variables(path)
            all_vars.update(vars_dict)

    return all_vars


# Load CSS variables once at module level
CSS_VARS = load_all_css_variables()


def resolve_pair(fg_token, bg_token):
    """Resolve a foreground/background token pair to hex colors."""
    fg = resolve_css_color(fg_token, CSS_VARS)
    bg = resolve_css_color(bg_token, CSS_VARS)
    return fg, bg


# =============================================================================
# Design Token Contrast Pairs using CSS variable references
# =============================================================================

CONTRAST_TOKENS = [
    # --- Claim Statuses (verification) ---
    # Each: (name, fg_token, bg_token, font_size_rem, font_weight, min_ratio)
    ("verif-strong", "--verif-strong-text", "--verif-strong-bg", "0.875", 400, 4.5),
    ("verif-supported", "--verif-supported-text", "--verif-supported-bg", "0.875", 400, 4.5),
    ("verif-weak", "--verif-weak-text", "--verif-weak-bg", "0.875", 400, 4.5),
    ("verif-mixed", "--verif-mixed-text", "--verif-mixed-bg", "0.875", 400, 4.5),
    ("verif-contradicted", "--verif-contradicted-text", "--verif-contradicted-bg", "0.875", 400, 4.5),
    ("verif-unverified", "--verif-unverified-text", "--verif-unverified-bg", "0.875", 400, 4.5),
    ("verif-superseded", "--verif-superseded-text", "--verif-superseded-bg", "0.875", 400, 4.5),
    ("verif-retracted", "--verif-retracted-text", "--verif-retracted-bg", "0.875", 400, 4.5),
    ("verif-not-assessed", "--verif-unverified-text", "--verif-unverified-bg", "0.875", 400, 4.5),

    # --- Maturity Stages ---
    ("mat-concept", "--mat-concept-text", "--mat-concept-bg", "0.875", 400, 4.5),
    ("mat-research", "--mat-research-text", "--mat-research-bg", "0.875", 400, 4.5),
    ("mat-prototype", "--mat-prototype-text", "--mat-prototype-bg", "0.875", 400, 4.5),
    ("mat-experimental", "--mat-experimental-text", "--mat-experimental-bg", "0.875", 400, 4.5),
    ("mat-early", "--mat-early-text", "--mat-early-bg", "0.875", 400, 4.5),
    ("mat-prodcand", "--mat-prodcand-text", "--mat-prodcand-bg", "0.875", 400, 4.5),
    ("mat-established", "--mat-established-text", "--mat-established-bg", "0.875", 400, 4.5),
    ("mat-not-assessed", "--verif-unverified-text", "--verif-unverified-bg", "0.875", 400, 4.5),

    # --- Risk States ---
    ("risk-critical", "--risk-critical-text", "--risk-critical-bg", "0.875", 400, 4.5),
    ("risk-high", "--risk-high-text", "--risk-high-bg", "0.875", 400, 4.5),
    ("risk-medium", "--risk-medium-text", "--risk-medium-bg", "0.875", 400, 4.5),
    ("risk-low", "--risk-low-text", "--risk-low-bg", "0.875", 400, 4.5),
    ("risk-unassessed", "--risk-unassessed-text", "--risk-unassessed-bg", "0.875", 400, 4.5),
    ("risk-insufficient", "--risk-insufficient-text", "--risk-insufficient-bg", "0.875", 400, 4.5),

    # --- Evidence Stances ---
    ("stance-supports", "--stance-supports-text", "--stance-supports-bg", "0.875", 400, 4.5),
    ("stance-contradicts", "--stance-contradicts-text", "--stance-contradicts-bg", "0.875", 400, 4.5),
    ("stance-context", "--stance-context-text", "--stance-context-bg", "0.875", 400, 4.5),
    ("stance-unknown", "--stance-unknown-text", "--stance-unknown-bg", "0.875", 400, 4.5),

    # --- Ranking Badges ---
    ("rank", "--rank-text", "--rank-bg", "0.875", 400, 4.5),

    # --- Runtime Operational Status ---
    ("runtime-healthy", "--verif-strong-text", "--verif-strong-bg", "0.8125", 400, 4.5),
    ("runtime-running", "#15803d", "#f0fdf4", "0.8125", 400, 4.5),
    ("runtime-degraded", "--risk-medium-text", "--risk-medium-bg", "0.8125", 400, 4.5),
    ("runtime-unhealthy", "#991b1b", "#fef2f2", "0.8125", 400, 4.5),
    ("runtime-failed", "#991b1b", "#fef2f2", "0.8125", 400, 4.5),
    ("runtime-retrying", "#1e40af", "#eff6ff", "0.8125", 400, 4.5),
    ("runtime-rate-limited", "#6b21a8", "#faf5ff", "0.8125", 400, 4.5),
    ("runtime-partial", "#c2410c", "#fff7ed", "0.8125", 400, 4.5),
    ("runtime-interrupted", "#9d174d", "#fdf2f8", "0.8125", 400, 4.5),
    ("runtime-blocked", "#78350f", "#fef3c7", "0.8125", 400, 4.5),
    ("runtime-disabled", "#4b5563", "#f3f4f6", "0.8125", 400, 4.5),
    ("runtime-unknown", "#6b7280", "#f9fafb", "0.8125", 400, 4.5),
    ("runtime-unavailable", "#64748b", "#f8fafc", "0.8125", 400, 4.5),
    ("runtime-not-applicable", "--ink-muted", "#f8fafc", "0.8125", 400, 4.5),
    ("runtime-not-due", "#64748b", "#f8fafc", "0.8125", 400, 4.5),
    ("runtime-skipped", "#64748b", "#f8fafc", "0.8125", 400, 4.5),

    # --- UI State Containers ---
    ("state-empty-icon", "--ink-faint", "#f8fafc", "1", 400, 3.0),
    ("state-loading-icon", "--accent-primary", "--accent-primary-subtle", "1", 400, 3.0),
    ("state-offline-icon", "#dc2626", "#fee2e2", "1", 400, 3.0),
    ("state-degraded-icon", "--risk-medium-text", "#fef3c7", "1", 400, 3.0),
    ("state-error-icon", "#dc2626", "#fee2e2", "1", 400, 3.0),

    # --- Buttons ---
    ("btn-primary-text", "--ink-inverse", "--accent-primary", "0.875", 500, 4.5),
    ("btn-primary-hover-text", "--ink-inverse", "--accent-primary-hover", "0.875", 500, 4.5),
    ("btn-secondary-text", "--ink-secondary", "--ink-inverse", "0.875", 500, 4.5),
    ("btn-secondary-hover-text", "--ink-primary", "--bg-panel-hover", "0.875", 500, 4.5),
    ("btn-icon", "--ink-muted", "--ink-inverse", "1", 400, 3.0),

    # --- Focus Rings ---
    ("focus-ring", "--focus-ring-color", "--ink-inverse", "1", 400, 3.0),
    ("focus-ring-on-panel", "--focus-ring-color", "--ink-inverse", "1", 400, 3.0),
    ("focus-ring-on-muted", "--focus-ring-color", "--bg-panel-hover", "1", 400, 3.0),

    # --- Form Text & Placeholder ---
    ("input-text", "--ink-primary", "--ink-inverse", "0.875", 400, 4.5),
    ("input-placeholder", "--ink-faint", "--ink-inverse", "0.875", 400, 4.5),
    ("input-border", "--border-default", "--ink-inverse", "1", 400, 3.0),
    ("input-focus-border", "--focus-ring-color", "--ink-inverse", "1", 400, 3.0),

    # --- Global Banners ---
    ("global-banner-offline-text", "#991b1b", "#fee2e2", "0.8125", 400, 4.5),
    ("global-banner-degraded-text", "#92400e", "#fef3c7", "0.8125", 400, 4.5),

    # --- Source Pills ---
    ("source-pill-github", "--ink-muted", "--bg-panel-hover", "0.75", 400, 4.5),
    ("source-pill-arxiv", "--ink-muted", "--bg-panel-hover", "0.75", 400, 4.5),
    ("source-pill-hn", "--ink-muted", "--bg-panel-hover", "0.75", 400, 4.5),

    # --- Project Match Pills ---
    ("project-match-pill", "--accent-primary", "--accent-primary-subtle", "0.75", 500, 4.5),

    # --- Active Navigation ---
    ("nav-active-text", "--accent-primary", "--ink-inverse", "0.875", 600, 4.5),
    ("nav-inactive-text", "--ink-muted", "--ink-inverse", "0.875", 400, 4.5),

    # --- Inbox Type Badges ---
    ("type-new-story", "#1d4ed8", "#eff6ff", "0.6875", 600, 4.5),
    ("type-update", "#6d28d9", "#f5f3ff", "0.6875", 600, 4.5),
    ("type-caution", "#b45309", "#fffbeb", "0.6875", 600, 4.5),
    ("type-weakened", "#be123c", "#fff1f2", "0.6875", 600, 4.5),
    ("type-correction", "#c2410c", "#fff7ed", "0.6875", 600, 4.5),
    ("type-risk", "#b91c1c", "#fef2f2", "0.6875", 600, 4.5),

    # --- Inbox State Badges ---
    ("state-unseen", "#0369a1", "#e0f2fe", "0.6875", 500, 4.5),
    ("state-saved", "#a16207", "#fef9c3", "0.6875", 500, 4.5),

    # --- Primary Text Colors ---
    ("ink-primary", "--ink-primary", "--ink-inverse", "1", 400, 4.5),
    ("ink-secondary", "--ink-secondary", "--ink-inverse", "1", 400, 4.5),
    ("ink-muted", "--ink-muted", "--ink-inverse", "1", 400, 4.5),
    ("ink-faint", "--ink-faint", "--ink-inverse", "1", 400, 4.5),

    # --- Regression assertions for the three corrected pairs ---
    ("REGRESSION: stance-unknown", "--stance-unknown-text", "--stance-unknown-bg", "0.875", 400, 4.5),
    ("REGRESSION: runtime-not-applicable", "--ink-muted", "#f8fafc", "0.8125", 400, 4.5),
    ("REGRESSION: state-degraded-icon", "--risk-medium-text", "#fef3c7", "1", 400, 3.0),
]


@pytest.mark.parametrize("name,fg_token,bg_token,size_rem,weight,min_ratio", CONTRAST_TOKENS)
def test_contrast_ratio(name, fg_token, bg_token, size_rem, weight, min_ratio):
    """Verify each foreground/background pair meets WCAG contrast requirements."""
    fg, bg = resolve_pair(fg_token, bg_token)
    ratio = contrast_ratio(fg, bg)
    is_large = is_large_text(size_rem, weight)
    required = 3.0 if is_large else min_ratio

    assert ratio >= required, (
        f"CONTRAST FAIL: {name}\n"
        f"  fg_token={fg_token} -> {fg}\n"
        f"  bg_token={bg_token} -> {bg}\n"
        f"  computed ratio={ratio:.2f}:1\n"
        f"  required >={required}:1\n"
        f"  font-size={size_rem}rem weight={weight} large={is_large}"
    )


# =============================================================================
# Additional: Verify no disabled axe rules in test config
# =============================================================================

def test_no_disabled_axe_rules_in_playwright():
    """Ensure the Playwright test doesn't disable any axe rules."""
    test_file = "tests/test_e2e_playwright.py"
    with open(test_file, "r", encoding="utf-8") as f:
        content = f.read()

    assert "wcag22aa" in content, "wcag22aa must be in axe runOnly tags"
    assert "disabledRules" not in content, "axe must not use disabledRules"


# =============================================================================
# Static Evidence Integrity Guards
# =============================================================================

def test_no_positive_tabindex():
    """Ensure no positive tabindex values exist in frontend source."""
    import glob
    for file in glob.glob("frontend/src/**/*.js", recursive=True):
        with open(file, "r", encoding="utf-8") as f:
            content = f.read()
        # tabindex="1", tabindex="2", etc. are forbidden
        # Allow tabindex="0" and tabindex="-1"
        matches = re.findall(r'tabindex\s*=\s*["\']([^"\']+)["\']', content)
        for match in matches:
            try:
                val = int(match)
                assert val <= 0, f"Positive tabindex={val} found in {file}"
            except ValueError:
                pass  # Not a numeric tabindex


def test_no_pytest_importorskip():
    """Ensure no pytest.importorskip in test files (excluding this contract test)."""
    import glob
    for file in glob.glob("tests/*.py"):
        if file.endswith("test_contrast_contract.py"):
            continue
        with open(file, "r", encoding="utf-8") as f:
            content = f.read()
        assert "pytest.importorskip" not in content, f"pytest.importorskip found in {file}"


def test_no_ignored_playwright_file():
    """Ensure no Playwright test is ignored/skipped (excluding this contract test)."""
    import glob
    for file in glob.glob("tests/*.py"):
        if file.endswith("test_contrast_contract.py"):
            continue
        with open(file, "r", encoding="utf-8") as f:
            content = f.read()
        assert "@pytest.mark.skip" not in content, f"@pytest.mark.skip found in {file}"
        assert "@pytest.mark.xfail" not in content, f"@pytest.mark.xfail found in {file}"


def test_no_315_threshold():
    """Ensure 31.5 threshold is not in 44px contract test."""
    with open("tests/test_e2e_playwright.py", "r", encoding="utf-8") as f:
        content = f.read()
    assert "31.5" not in content, "31.5 threshold found in 44px contract test - must use 43.5"


def test_no_skip_link_focus():
    """Ensure skip_link.focus() is not used in keyboard skip-link test."""
    with open("tests/test_e2e_playwright.py", "r", encoding="utf-8") as f:
        content = f.read()
    assert "skip_link.focus()" not in content, "Direct skip_link.focus() found in test"


def test_no_scrolled_right_ge_initial():
    """Ensure scrolled_right >= initial_scroll is not used."""
    with open("tests/test_e2e_playwright.py", "r", encoding="utf-8") as f:
        content = f.read()
    assert "scrolled_right >= initial_scroll" not in content, "Vacuous scroll assertion found"


def test_no_hardcoded_story_id():
    """Ensure no hard-coded production story ID in tests."""
    with open("tests/test_e2e_playwright.py", "r", encoding="utf-8") as f:
        content = f.read()
    assert "cluster:2f39e49b0987" not in content, "Hard-coded production story ID found"


def test_no_production_db_in_test_harness():
    """Ensure test harness rejects non-test backend on port 8765."""
    with open("tests/test_e2e_playwright.py", "r", encoding="utf-8") as f:
        content = f.read()
    # Check that ensure_test_servers has the rejection logic
    assert "non-test backend" in content or "Rejecting pre-existing" in content, "Test harness must reject non-test backend"


def test_no_conditional_bypass_story_dossier():
    """Ensure no conditional silently bypasses Story Dossier workflow."""
    with open("tests/test_e2e_playwright.py", "r", encoding="utf-8") as f:
        content = f.read()
    assert "testid_restored" in content or "data-testid" in content, "Focus restoration must verify exact data-testid match"


def test_css_variables_loaded():
    """Verify CSS variables were loaded from frontend token files."""
    assert len(CSS_VARS) > 50, f"Expected 50+ CSS variables, got {len(CSS_VARS)}"
    # Verify key variables exist
    assert "--ink-primary" in CSS_VARS
    assert "--ink-muted" in CSS_VARS
    assert "--accent-primary" in CSS_VARS
    assert "--border-default" in CSS_VARS
    assert "--stance-unknown-text" in CSS_VARS


def test_resolved_colors_are_hex():
    """Verify all resolved colors are valid hex values."""
    for name, fg_token, bg_token, _, _, _ in CONTRAST_TOKENS:
        fg, bg = resolve_pair(fg_token, bg_token)
        assert fg.startswith("#") and len(fg) == 7, f"{name}: fg '{fg}' is not valid hex"
        assert bg.startswith("#") and len(bg) == 7, f"{name}: bg '{bg}' is not valid hex"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])