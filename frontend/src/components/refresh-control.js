import { operationManager } from '../state/operation-manager.js';

/**
 * Renders a standardized, durable refresh control button and status message.
 * @param {HTMLElement} parentElement - Where to render the control
 * @param {string} scope - The operation scope ('daily_refresh', 'project_scan', etc.)
 * @param {Function} [onComplete] - Callback triggered when the refresh finishes successfully
 * @param {string} [label] - Button label (default "Sync Data"; e.g. "Run Daily Refresh")
 * @param {Object} [options] - Extra startRefresh options (e.g. { targetId } for project_scan)
 */
export function renderRefreshControl(parentElement, scope, onComplete = null, label = 'Sync Data', options = {}) {
  if (!parentElement) return () => {};

  const btnId = `btn-refresh-${scope}`;
  const statusId = `status-refresh-${scope}`;

  const initiallyActive = operationManager.isActive(scope);

  parentElement.innerHTML = `
    <div class="refresh-control-container flex items-center gap-4" style="display:inline-flex;align-items:center;flex-wrap:wrap;gap:var(--space-2);">
      <button type="button" id="${btnId}" class="btn btn-sm btn-outline" aria-label="${label}" ${initiallyActive ? 'disabled' : ''} style="display:inline-flex;align-items:center;gap:var(--space-1);">
        <span class="refresh-icon">🔄</span>
        <span class="refresh-label">${label}</span>
      </button>
      <span id="${statusId}" class="refresh-status text-sm text-muted" role="status" aria-live="polite" style="font-size:var(--text-sm);margin-left:var(--space-2);"></span>
    </div>
  `;

  const btn = parentElement.querySelector(`#${btnId}`);
  const statusEl = parentElement.querySelector(`#${statusId}`);

  function updateStatus(state) {
    if (!statusEl || !btn) return;

    if (state.status === 'queued') {
      btn.disabled = true;
      statusEl.style.color = 'var(--warning-color, #d97706)';
      statusEl.textContent = state.message || (state.daemonWarning
        ? 'Queued — waiting for the background daemon to pick it up...'
        : 'Queued in background...');
    } else if (state.status === 'running') {
      btn.disabled = true;
      statusEl.style.color = 'var(--info-color, #2563eb)';
      statusEl.textContent = 'Syncing data...';
    } else if (state.status === 'partial') {
      btn.disabled = true;
      statusEl.style.color = 'var(--warning-color, #d97706)';
      statusEl.textContent = 'Syncing (partial results so far)...';
    } else if (state.status === 'reconnecting') {
      btn.disabled = true;
      statusEl.style.color = 'var(--warning-color, #d97706)';
      statusEl.textContent = state.message || 'Reconnecting to the API...';
    } else if (state.status === 'completed') {
      btn.disabled = false;
      statusEl.style.color = 'var(--success-color, #16a34a)';
      statusEl.textContent = 'Sync complete';
      setTimeout(() => {
        if (statusEl && statusEl.textContent === 'Sync complete') {
          statusEl.textContent = '';
        }
      }, 3000);
      if (onComplete) onComplete(state.operation);
    } else if (state.status === 'failed') {
      btn.disabled = false;
      statusEl.style.color = 'var(--danger-color, #dc2626)';
      statusEl.textContent = `Sync failed: ${state.error || 'Unknown error'}`;
    } else {
      btn.disabled = false;
      statusEl.textContent = '';
    }
  }

  const unsubscribe = operationManager.subscribe(scope, updateStatus);

  if (initiallyActive) {
    // Resume monitoring if it was paused by a route transition — the backend
    // operation kept running; we only re-attach polling here.
    operationManager.resumeMonitoring(scope);
    updateStatus({ status: 'running' });
  }

  btn.addEventListener('click', async () => {
    try {
      btn.disabled = true;
      await operationManager.startRefresh(scope, null, options);
    } catch (err) {
      console.error("Failed to start refresh:", err);
      updateStatus({ status: 'failed', error: err.message || String(err) });
    }
  });

  return () => {
    unsubscribe();
  };
}
