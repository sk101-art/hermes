import { renderRefreshControl } from './refresh-control.js';

/**
 * Renders the standardized two-control surface header used across all eight
 * Phase 4 surfaces (Today, Briefing, Runtime, Changes, Saved, Projects,
 * Search, Story).
 *
 * Control 1 — "Refresh View": a GET-only reload of the current view's data.
 *   It never mutates backend state; it simply re-fetches and re-renders.
 * Control 2 — "Sync Data": queues a durable backend operation for the
 *   surface's mapped scope and monitors it to completion.
 *
 * @param {HTMLElement} parentElement - Container to render the controls into.
 * @param {Object} config
 * @param {string} config.scope - Durable operation scope for Sync Data
 *   ('daily_refresh', 'health_check', 'recheck', 'saved_hydration',
 *    'project_scan', 'search_refresh', 'story_recheck').
 * @param {string} [config.targetId] - Optional target id (required for
 *   project_scan).
 * @param {Function} [config.onRefresh] - GET-only reload callback for the
 *   Refresh View button. If omitted, the Refresh View button is not rendered.
 * @param {string} [config.syncLabel] - Label for the Sync Data button
 *   (default "Sync Data").
 * @param {string} [config.refreshLabel] - Label for the Refresh View button
 *   (default "Refresh View").
 * @param {Function} [config.onSyncComplete] - Callback when Sync Data finishes
 *   successfully. Defaults to onRefresh when provided.
 * @returns {Function} cleanup - Call to stop any active operation monitoring.
 */
export function renderSurfaceControls(parentElement, config = {}) {
  if (!parentElement) return () => {};

  const {
    scope,
    targetId = null,
    onRefresh = null,
    syncLabel = 'Sync Data',
    refreshLabel = 'Refresh View',
    onSyncComplete = null,
  } = config;

  parentElement.innerHTML = '';
  parentElement.style.display = 'flex';
  parentElement.style.alignItems = 'center';
  parentElement.style.gap = 'var(--space-2)';
  parentElement.style.flexWrap = 'wrap';

  const cleanups = [];

  // Control 1: Refresh View (GET-only, never mutates)
  if (typeof onRefresh === 'function') {
    const refreshBtn = document.createElement('button');
    refreshBtn.type = 'button';
    refreshBtn.className = 'btn btn-secondary btn-sm surface-refresh-btn';
    refreshBtn.textContent = refreshLabel;
    refreshBtn.setAttribute('aria-label', `${refreshLabel}: reload this view's data without changing anything`);
    refreshBtn.addEventListener('click', () => {
      try {
        onRefresh();
      } catch (e) {
        // Refresh View is best-effort; surface errors are handled by the view.
      }
    });
    parentElement.appendChild(refreshBtn);
  }

  // Control 2: Sync Data (durable operation)
  if (scope) {
    const syncWrap = document.createElement('div');
    syncWrap.className = 'surface-sync-wrap';
    syncWrap.style.display = 'inline-flex';
    syncWrap.style.alignItems = 'center';
    syncWrap.style.gap = 'var(--space-2)';
    parentElement.appendChild(syncWrap);

    const syncCleanup = renderRefreshControl(
      syncWrap,
      scope,
      typeof onSyncComplete === 'function' ? onSyncComplete : onRefresh,
      syncLabel,
      targetId ? { targetId } : {}
    );
    if (typeof syncCleanup === 'function') cleanups.push(syncCleanup);
  }

  return () => {
    for (const fn of cleanups) {
      try {
        fn();
      } catch (e) {
        // ignore cleanup errors
      }
    }
  };
}

export default renderSurfaceControls;
