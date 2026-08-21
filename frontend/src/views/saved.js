/**
 * HERMES Saved Library View
 * Longitudinal saved intelligence library backed authoritatively by the Phase 4 /saved contract.
 * Zero fake localStorage stars or unpersisted local mocks.
 */

import { api } from '../api/endpoints.js';
import { renderVerificationBadge, renderMaturityBadge, renderRiskBadge } from '../components/badges.js';
import { renderLoadingState, renderEmptyState, renderErrorState, renderOfflineState } from '../components/ui-states.js';
import { escapeHtml, formatDate, ensureArray } from '../utils/adapters.js';

export async function renderSavedView(container, store) {
  container.innerHTML = renderLoadingState('Loading saved intelligence library…');

  try {
    const response = await api.getSavedItems({ limit: 50, include_current: true });
    const items = ensureArray(response.saved_items || response.items || response);
    store.setViewData('saved', items);
    store.setConnection('healthy');

    let html = `
      <div class="page-header-container">
        <div>
          <span class="eyebrow">Longitudinal Library</span>
          <h1>Saved Intelligence</h1>
          <p class="lead">Saved snapshots preserve their original state at the time of review alongside current intelligence evolutions.</p>
        </div>
        <div class="page-header-meta">
          <strong>${items.length}</strong>
          <span>saved item${items.length === 1 ? '' : 's'}</span>
        </div>
      </div>
    `;

    if (!items.length) {
      html += renderEmptyState(
        'No Saved Items',
        'Your saved library is empty. Save stories and claims from the Today feed, Search, or Dossier to track them longitudinally.'
      );
    } else {
      html += `
        <div class="table-wrapper">
          <table class="data-table">
            <thead>
              <tr>
                <th scope="col">Snapshot Entity</th>
                <th scope="col">Saved At</th>
                <th scope="col">State at Save</th>
                <th scope="col">Current Live State</th>
                <th scope="col">Tags & Notes</th>
              </tr>
            </thead>
            <tbody>
              ${items.map((item) => {
                const title = item.title_snapshot || item.title || 'Untitled Item';
                const entityId = item.story_cluster_id || item.entity_id || '';
                const savedDate = formatDate(item.saved_at || item.created_at);
                const maturitySnap = item.maturity_snapshot || null;
                const verifSnap = item.verification_snapshot !== undefined ? item.verification_snapshot : null;
                const riskSnap = item.risk_snapshot !== undefined ? item.risk_snapshot : null;

                // Current live state (from include_current=true)
                const current = item.current_state || null;
                let currentVerifBadge = '';
                let currentMaturityBadge = '';
                let currentRiskBadge = '';

                if (current) {
                  if (current.current_verification_score !== undefined || current.current_status) {
                    currentVerifBadge = renderVerificationBadge(current.current_status || (current.current_verification_score !== null ? 'supported' : null), current.current_verification_score);
                  }
                  if (current.current_maturity) {
                    currentMaturityBadge = renderMaturityBadge(current.current_maturity);
                  }
                  if (current.current_risk_status) {
                    currentRiskBadge = renderRiskBadge(current.current_risk_status, current.current_risk_level, null);
                  }
                }

                const tags = ensureArray(item.tags);

                return `<tr>
                  <td>
                    <div class="text-semibold">${escapeHtml(title)}</div>
                    <div class="mono text-xs text-faint" style="margin-top:2px;">${escapeHtml(entityId)}</div>
                  </td>
                  <td class="text-muted text-xs">${savedDate}</td>
                  <td>
                    <div style="display:flex;flex-direction:column;gap:4px;align-items:flex-start;">
                      ${maturitySnap ? renderMaturityBadge(maturitySnap) : ''}
                      ${verifSnap !== null ? renderVerificationBadge('supported', verifSnap) : '<span class="text-xs text-faint">No verif score</span>'}
                      ${riskSnap !== null ? renderRiskBadge('assessed', null, riskSnap) : ''}
                    </div>
                  </td>
                  <td>
                    ${current ? `
                      <div style="display:flex;flex-direction:column;gap:4px;align-items:flex-start;">
                        ${currentMaturityBadge}
                        ${currentVerifBadge}
                        ${currentRiskBadge}
                        ${current.has_changed ? '<span class="semantic-badge badge-verification-weakly_supported">State Changed</span>' : ''}
                      </div>
                    ` : '<span class="text-xs text-muted">Snapshot only</span>'}
                  </td>
                  <td>
                    ${item.user_note ? `<p class="text-xs" style="margin:0 0 4px;font-style:italic;">“${escapeHtml(item.user_note)}”</p>` : ''}
                    <div class="chip-group" style="margin-top:0;">
                      ${tags.map((t) => `<span class="chip">${escapeHtml(t)}</span>`).join('')}
                    </div>
                  </td>
                </tr>`;
              }).join('')}
            </tbody>
          </table>
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
      container.innerHTML = renderErrorState('Failed to Load Saved Library', err.message);
    }
  }
}
