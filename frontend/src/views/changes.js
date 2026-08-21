/**
 * HERMES Changes View
 * Longitudinal delta tracker for verification, contradiction, maturity, and release shifts.
 */

import { api } from '../api/endpoints.js';
import { renderLoadingState, renderEmptyState, renderErrorState, renderOfflineState } from '../components/ui-states.js';
import { escapeHtml, formatDate, ensureArray, toTitleCase } from '../utils/adapters.js';

export async function renderChangesView(container, store) {
  container.innerHTML = renderLoadingState('Loading longitudinal changes…');

  try {
    const response = await api.getChanges({ hours: 168, limit: 40 });
    const changes = ensureArray(response.changes || response);
    store.setViewData('changes', changes);
    store.setConnection('healthy');

    let html = `
      <div class="page-header-container">
        <div>
          <span class="eyebrow">Longitudinal Signal</span>
          <h1>What Moved</h1>
          <p class="lead">Track verification revisions, contradiction discoveries, maturity advancements, and risk changes.</p>
        </div>
        <div class="page-header-meta">
          <strong>${changes.length}</strong>
          <span>recorded change${changes.length === 1 ? '' : 's'} · past 7 days</span>
        </div>
      </div>
    `;

    if (!changes.length) {
      html += renderEmptyState(
        'No Recent Changes Detected',
        'No verified state changes, claim revisions, or maturity shifts were recorded in the last 7 days.'
      );
    } else {
      html += `
        <div class="panel">
          ${changes.map((c) => {
            const changeType = c.change_type || c.entity_type || 'State Change';
            const reason = c.reason || 'Tracked state change detected';
            const oldValue = c.old_value || '—';
            const newValue = c.new_value || '—';
            const changeDate = formatDate(c.created_at || c.detected_at);
            const isHighImportance = (typeof c.importance === 'number' && c.importance >= 0.75);

            return `<div class="change-row-item">
              <div>
                <span class="mono text-xs text-bold" style="color:var(--accent-primary);text-transform:uppercase;">
                  ${escapeHtml(toTitleCase(changeType))}
                </span>
                <div class="text-xs text-faint" style="margin-top:2px;">${changeDate}</div>
              </div>

              <div>
                <div class="text-sm text-semibold">${escapeHtml(reason)}</div>
                <div class="mono text-xs text-muted" style="margin-top:4px;">
                  <span class="text-faint">${escapeHtml(oldValue)}</span>
                  <span style="margin:0 6px;">→</span>
                  <span class="text-bold" style="color:var(--ink-primary);">${escapeHtml(newValue)}</span>
                </div>
              </div>

              <div>
                <span class="semantic-badge ${isHighImportance ? 'badge-verification-supported' : 'badge-verification-unverified'}">
                  ${isHighImportance ? 'High Impact' : 'Observed'}
                </span>
              </div>
            </div>`;
          }).join('')}
        </div>
      `;
    }

    container.innerHTML = html;
  } catch (err) {
    if (err.isNetworkError) {
      store.setConnection('offline', err.message);
      container.innerHTML = renderOfflineState(undefined, err.message);
    } else {
      store.setConnection('degraded', err.message);
      container.innerHTML = renderErrorState('Failed to Load State Changes', err.message);
    }
  }
}
