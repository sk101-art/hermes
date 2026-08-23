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

/**
 * Announces a message to assistive technology via an aria-live region.
 * @param {string} message 
 * @param {'polite'|'assertive'} [politeness='polite']
 */
export function announceToScreenReader(message, politeness = 'polite') {
  if (typeof document === 'undefined') return;

  let liveRegion = document.getElementById('hermes-a11y-live');
  if (!liveRegion) {
    liveRegion = document.createElement('div');
    liveRegion.id = 'hermes-a11y-live';
    liveRegion.className = 'sr-only';
    liveRegion.style.cssText = 'position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0;';
    document.body.appendChild(liveRegion);
  }

  liveRegion.setAttribute('aria-live', politeness);
  liveRegion.setAttribute('aria-atomic', 'true');
  liveRegion.textContent = message;
}

/**
 * Traps focus inside a modal or drawer container.
 * @param {HTMLElement} element 
 * @returns {() => void} Cleanup function
 */
export function trapFocus(element) {
  if (!element) return () => {};

  const focusableEls = element.querySelectorAll(
    'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
  );
  const firstFocusableEl = focusableEls[0];
  const lastFocusableEl = focusableEls[focusableEls.length - 1];

  function handleKeyDown(e) {
    if (e.key === 'Tab') {
      if (e.shiftKey) {
        if (document.activeElement === firstFocusableEl) {
          lastFocusableEl.focus();
          e.preventDefault();
        }
      } else {
        if (document.activeElement === lastFocusableEl) {
          firstFocusableEl.focus();
          e.preventDefault();
        }
      }
    }
  }

  element.addEventListener('keydown', handleKeyDown);
  if (firstFocusableEl) firstFocusableEl.focus();

  return () => {
    element.removeEventListener('keydown', handleKeyDown);
  };
}
