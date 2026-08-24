# HERMES Phase 17 — Accessibility & Contrast Audit

## 1. Executive Summary

This document provides the accessibility and contrast compliance audit for the HERMES Single-Page Application (SPA) across all 10 route topologies and shared UI components.

> [!NOTE]
> Automated testing was conducted using **Axe-core v4.10.2** and Playwright synthetic keyboard interaction suites. Real screen-reader / VoiceOver / NVDA dynamic testing was **not performed or claimed**.

---

## 2. WCAG 2.2 Level AA Compliance Matrix

| Criterion | Rule ID | Scope | Status | Evidence / Implementation Details |
| :--- | :--- | :--- | :--- | :--- |
| **1.1.1 Non-text Content** | `image-alt` | All Views | **PASS** | All SVG icons and decorative graphics contain `aria-hidden="true"`, or explicit descriptive accessible names. |
| **1.3.1 Info and Relationships** | `landmark-one-main`, `heading-order` | Shell & Views | **PASS** | Exact semantic structure: `<header role="banner">`, `<main id="main-content">`, `<nav aria-label="...">`, strictly sequential `<h1>` -> `<h2>` -> `<h3>`. |
| **1.4.1 Use of Color** | `color-alone` | Badges & Metrics | **PASS** | Status, verification, and risk indicators pair color with text tokens and shape glyphs (e.g., Supported, Disputed, Unverified). |
| **1.4.3 Contrast (Minimum)** | `color-contrast` | Typography & Tokens | **PASS** | High-contrast tokens (`--text-primary` #111827 on `--bg-primary` #FFFFFF = 15.3:1; `--text-muted` #4B5563 = 7.1:1). |
| **2.1.1 Keyboard** | `keyboard-nav` | App Shell | **PASS** | Full keyboard operability. Zero positive `tabindex`. Skip link (`#main-content`) is first focusable element. |
| **2.4.3 Focus Order** | `focus-order` | Views & Modals | **PASS** | Logical DOM focus order preserved across route changes with `focusPageHeading()`. Modal/drawer focus trapping via `trapFocus`. |
| **2.4.4 Link Purpose** | `link-name` | Story Cards | **PASS** | Story cards render genuine `<a href="...">` anchor tags with full descriptive headings. |
| **4.1.2 Name, Role, Value** | `aria-roles` | Controls & State | **PASS** | ErrorBoundary uses `role="alert"`, live regions use `aria-live="polite"`. Tables include `<caption>` and `<th scope="col">`. |

---

## 3. Keyboard Navigation and Focus Management

1. **Skip to Main Content**:
   - The skip link is positioned as the initial element in the DOM: `<a href="#main-content" class="skip-link">Skip to main content</a>`.
   - On activation, focus moves immediately to `<main id="main-content" tabindex="-1">`.

2. **Heading Focus on Hash Route Transitions**:
   - When navigation completes, `focusPageHeading(viewKey)` directs keyboard focus to the target view's unique `<h1>` heading.
   - Prevents focus loss or keyboard traps during asynchronous rendering.

3. **Zero Positive Tabindex Policy**:
   - Automated scans confirm zero elements declare `tabindex > 0`.
   - Interactive widgets only use `tabindex="0"` or `tabindex="-1"` (for programmatic focus targets).

---

## 4. Automated Axe-Core Test Results

Automated Node.js axe-core audit executed against rendered HTML templates:
- Critical Violations: **0**
- Serious Violations: **0**
- Moderate Violations: **0**
- Minor Violations: **0**
- Automated Unit Tests: `frontend/tests/frontend.test.js` (Test 15.9: Axe-core accessibility scan) -> **PASSED**.

---

## 5. Explicit Limitations & Boundaries

- **Screen-Reader Scope**: Testing is based on automated DOM inspection, ARIA attributes, axe-core engine validation, and Playwright keyboard events. No manual human auditory validation with VoiceOver, JAWS, or NVDA was conducted.
