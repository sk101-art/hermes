/**
 * HERMES Accessibility (a11y) Helpers
 * Screen-reader live announcements, keyboard focus management,
 * and ARIA attributes utility.
 */

export const VIEW_TITLES = Object.freeze({
  today: "Today's Intelligence",
  briefing: "Morning Intelligence Briefing",
  search: "Corpus Search & Discovery",
  projects: "Project Intelligence Alignment",
  saved: "Saved Intelligence Library",
  changes: "Intelligence Changes & Transitions",
  runtime: "Engine Runtime & Telemetry",
  story: "Story Dossier",
});

let announcementQueue = Promise.resolve();

function waitForAnnouncementTick() {
  return new Promise((resolve) => {
    setTimeout(resolve, 30);
  });
}

/**
 * Announces a message to assistive technology via an aria-live region.
 * Automatically clears and updates the live region asynchronously to ensure
 * repeated identical announcements are reliably dispatched by screen readers.
 * @param {string} message 
 * @param {'polite'|'assertive'} [politeness='polite']
 * @returns {Promise<void>}
 */
export function announceToScreenReader(message, politeness = 'polite') {
  if (typeof document === 'undefined' || !message) {
    return Promise.resolve();
  }

  const normalizedPoliteness =
    politeness === 'assertive' ? 'assertive' : 'polite';

  announcementQueue = announcementQueue.then(async () => {
    let liveRegion = document.getElementById('hermes-a11y-live');

    if (!liveRegion) {
      liveRegion = document.createElement('div');
      liveRegion.id = 'hermes-a11y-live';
      liveRegion.className = 'sr-only';
      liveRegion.setAttribute('aria-atomic', 'true');
      liveRegion.style.cssText = 'position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0;';
      document.body.appendChild(liveRegion);
    }

    liveRegion.setAttribute('aria-live', normalizedPoliteness);
    liveRegion.textContent = '';

    await waitForAnnouncementTick();

    liveRegion.textContent = message;
  });

  return announcementQueue;
}

/**
 * Returns all currently visible, non-disabled, keyboard-focusable elements inside a container.
 * Evaluates dynamically at query time to support dynamic DOM alterations.
 * @param {HTMLElement} container
 * @returns {HTMLElement[]}
 */
export function getFocusableElements(container) {
  if (!container || typeof container.querySelectorAll !== 'function') return [];

  const selector = [
    'a[href]',
    'button:not([disabled])',
    'input:not([disabled]):not([type="hidden"])',
    'select:not([disabled])',
    'textarea:not([disabled])',
    '[tabindex]:not([tabindex="-1"])',
    '[contenteditable="true"]',
  ].join(', ');

  const nodes = Array.from(container.querySelectorAll(selector));

  return nodes.filter((el) => {
    if (!el) return false;
    if (el.hasAttribute('disabled') || el.getAttribute('aria-disabled') === 'true') return false;
    if (el.getAttribute('tabindex') === '-1') return false;
    if (el.hasAttribute('inert') || (el.closest && el.closest('[inert]'))) return false;
    if (el.getAttribute('aria-hidden') === 'true' || (el.closest && el.closest('[aria-hidden="true"]'))) return false;

    // Check computed visibility if getComputedStyle is available in browser
    if (typeof window !== 'undefined' && typeof window.getComputedStyle === 'function') {
      try {
        const style = window.getComputedStyle(el);
        if (style.display === 'none' || style.visibility === 'hidden' || style.visibility === 'collapse') {
          return false;
        }
      } catch {}
    }

    return true;
  });
}

/**
 * Traps focus inside a modal or drawer container.
 * Features:
 * - Dynamically evaluates focusable elements on keydown.
 * - Handles 0, 1, or N focusable controls safely.
 * - Supports Shift+Tab wrap-around.
 * - Idempotent cleanup function.
 * @param {HTMLElement} element 
 * @param {Object} [options]
 * @param {HTMLElement} [options.initialFocus]
 * @returns {() => void} releaseFocusTrap cleanup function
 */
export function trapFocus(element, options = {}) {
  if (!element || typeof element.addEventListener !== 'function') return () => {};

  let isCleanedUp = false;

  function handleKeyDown(e) {
    if (isCleanedUp) return;
    if (e.key !== 'Tab') return;

    const focusable = getFocusableElements(element);

    if (focusable.length === 0) {
      e.preventDefault();
      if (typeof element.focus === 'function') {
        element.focus();
      }
      return;
    }

    if (focusable.length === 1) {
      e.preventDefault();
      focusable[0].focus();
      return;
    }

    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    const active = typeof document !== 'undefined' ? document.activeElement : null;

    if (e.shiftKey) {
      if (active === first || !element.contains(active)) {
        e.preventDefault();
        last.focus();
      }
    } else {
      if (active === last || !element.contains(active)) {
        e.preventDefault();
        first.focus();
      }
    }
  }

  element.addEventListener('keydown', handleKeyDown);

  // Set initial focus
  if (options.initialFocus && typeof options.initialFocus.focus === 'function' && element.contains(options.initialFocus)) {
    options.initialFocus.focus();
  } else {
    const initialFocusable = getFocusableElements(element);
    if (initialFocusable.length > 0 && typeof initialFocusable[0].focus === 'function') {
      initialFocusable[0].focus();
    } else if (typeof element.focus === 'function') {
      element.setAttribute('tabindex', '-1');
      element.focus();
    }
  }

  return function releaseFocusTrap() {
    if (isCleanedUp) return;
    isCleanedUp = true;
    if (typeof element.removeEventListener === 'function') {
      element.removeEventListener('keydown', handleKeyDown);
    }
  };
}

/**
 * Moves focus to the primary view heading or main content container.
 * @param {HTMLElement} container
 */
export function focusPageHeading(container) {
  if (!container || typeof container.querySelector !== 'function') return;
  const heading = container.querySelector('h1');
  if (heading && typeof heading.focus === 'function') {
    heading.setAttribute('tabindex', '-1');
    heading.focus();
  } else if (typeof container.focus === 'function') {
    container.focus();
  }
}

let releaseDrawerFocusTrap = null;

export const MOBILE_DRAWER_QUERY = '(max-width: 768px)';

export function isMobileViewport() {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
    return false;
  }
  return window.matchMedia(MOBILE_DRAWER_QUERY).matches;
}

/**
 * Synchronizes drawer accessibility attributes based on viewport and open/closed state.
 */
export function syncDrawerAccessibility() {
  if (typeof document === 'undefined') return;

  const sidebar = document.getElementById('app-sidebar');
  const mobileToggle = document.getElementById('mobile-menu-toggle');
  const backdrop = document.getElementById('sidebar-backdrop');
  const mainWrapper = document.getElementById('app-main-wrapper');

  if (!sidebar) return;

  const isMobile = isMobileViewport();
  const isOpen = sidebar.classList.contains('open');

  if (isOpen) {
    sidebar.classList.add('open');
    sidebar.removeAttribute('inert');
    sidebar.setAttribute('aria-hidden', 'false');
    if (backdrop) {
      backdrop.classList.add('active');
      backdrop.setAttribute('aria-hidden', 'false');
    }
    if (mobileToggle) {
      mobileToggle.setAttribute('aria-expanded', 'true');
      mobileToggle.setAttribute('aria-label', 'Close navigation menu');
    }
    if (mainWrapper && typeof mainWrapper.setAttribute === 'function') {
      mainWrapper.setAttribute('inert', '');
    }
  } else if (isMobile) {
    sidebar.classList.remove('open');
    sidebar.setAttribute('inert', '');
    sidebar.setAttribute('aria-hidden', 'true');
    if (backdrop) {
      backdrop.classList.remove('active');
      backdrop.setAttribute('aria-hidden', 'true');
    }
    if (mobileToggle) {
      mobileToggle.setAttribute('aria-expanded', 'false');
      mobileToggle.setAttribute('aria-label', 'Toggle navigation menu');
    }
    if (mainWrapper && typeof mainWrapper.removeAttribute === 'function') {
      mainWrapper.removeAttribute('inert');
    }
  } else {
    // Desktop view: persistent sidebar
    sidebar.classList.remove('open');
    sidebar.removeAttribute('inert');
    sidebar.removeAttribute('aria-hidden');
    if (backdrop) {
      backdrop.classList.remove('active');
      backdrop.setAttribute('aria-hidden', 'true');
    }
    if (mobileToggle) {
      mobileToggle.setAttribute('aria-expanded', 'false');
      mobileToggle.setAttribute('aria-label', 'Toggle navigation menu');
    }
    if (mainWrapper && typeof mainWrapper.removeAttribute === 'function') {
      mainWrapper.removeAttribute('inert');
    }
  }
}

/**
 * Open the mobile navigation drawer with modal focus trapping.
 */
export function openMobileDrawer() {
  if (typeof document === 'undefined') return;

  const sidebar = document.getElementById('app-sidebar');
  if (!sidebar) return;

  sidebar.classList.add('open');
  syncDrawerAccessibility();

  // Release any existing trap first to avoid duplicate listeners
  if (releaseDrawerFocusTrap) {
    releaseDrawerFocusTrap();
    releaseDrawerFocusTrap = null;
  }

  // Trap focus inside sidebar
  releaseDrawerFocusTrap = trapFocus(sidebar);
}

/**
 * Close the mobile navigation drawer and release focus trapping.
 * @param {boolean} [returnFocus=true]
 */
export function closeMobileDrawer(returnFocus = true) {
  if (typeof document === 'undefined') return;

  const sidebar = document.getElementById('app-sidebar');
  const mobileToggle = document.getElementById('mobile-menu-toggle');

  if (!sidebar) return;

  // Release trap first
  if (releaseDrawerFocusTrap) {
    releaseDrawerFocusTrap();
    releaseDrawerFocusTrap = null;
  }

  sidebar.classList.remove('open');
  syncDrawerAccessibility();

  if (returnFocus && mobileToggle && typeof mobileToggle.focus === 'function') {
    mobileToggle.focus();
  }
}

