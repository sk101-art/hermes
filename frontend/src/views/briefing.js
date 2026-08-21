/**
 * HERMES Morning Briefing View
 * Distilled engineering digest mapping technical shifts, verification changes, and priority reads.
 */

import { api } from '../api/endpoints.js';
import { renderLoadingState, renderEmptyState, renderErrorState, renderOfflineState } from '../components/ui-states.js';
import { escapeHtml, formatTime, ensureArray, toTitleCase } from '../utils/adapters.js';

export async function renderBriefingView(container, store) {
  container.innerHTML = renderLoadingState('Loading morning briefing digest…');

  try {
    const briefing = await api.getBriefing();
    store.setViewData('briefing', briefing);
    store.setConnection('healthy');

    const sections = briefing.sections || {};
    const hasSections = Object.keys(sections).length > 0;

    let html = `
      <div class="page-header-container">
        <div>
          <span class="eyebrow">Morning Briefing</span>
          <h1>The Day, Distilled</h1>
          <p class="lead">A serious engineering read: what changed, what strengthened, and what deserves your attention next.</p>
        </div>
        <div class="page-header-meta">
          <strong>${briefing.total_items ?? '—'}</strong>
          <span>briefing items · Generated ${formatTime(briefing.generated_at)}</span>
        </div>
      </div>

      <div class="panel" style="padding:var(--space-6);margin-bottom:var(--space-6);">
        <span class="eyebrow">${escapeHtml(briefing.briefing_date || 'Today')}</span>
        <h2>A concise map of the signal</h2>
        <p style="margin-top:var(--space-2);max-width:800px;">
          ${escapeHtml(briefing.summary_text || 'No briefing summary is available for this date. Run the morning briefing job to generate a fresh digest.')}
        </p>
      </div>

      <div class="section-header">
        <div>
          <h2>Briefing Sections</h2>
          <p class="text-muted text-sm" style="margin:0;">Each section links back to underlying inbox signals and their verified evidence.</p>
        </div>
      </div>

      <div class="table-wrapper">
        <table class="data-table">
          <thead>
            <tr>
              <th scope="col">Section</th>
              <th scope="col">Items</th>
              <th scope="col">Priority Category</th>
            </tr>
          </thead>
          <tbody>
            ${hasSections
              ? Object.entries(sections).map(([secKey, secItems]) => {
                  const isHighPriority = /must|project|critical/i.test(secKey);
                  return `<tr>
                    <td class="text-semibold">${escapeHtml(toTitleCase(secKey))}</td>
                    <td class="mono">${ensureArray(secItems).length}</td>
                    <td>
                      <span class="semantic-badge ${isHighPriority ? 'badge-verification-supported' : 'badge-verification-unverified'}">
                        ${isHighPriority ? 'Read First' : 'Monitor'}
                      </span>
                    </td>
                  </tr>`;
                }).join('')
              : `<tr><td colspan="3" class="text-muted" style="text-align:center;padding:var(--space-8);">No briefing sections returned by the backend.</td></tr>`
            }
          </tbody>
        </table>
      </div>
    `;

    container.innerHTML = html;
  } catch (err) {
    if (err.isNetworkError) {
      store.setConnection('offline', err.message);
      container.innerHTML = renderOfflineState(undefined, err.message);
    } else {
      store.setConnection('degraded', err.message);
      container.innerHTML = renderErrorState('Failed to Load Morning Briefing', err.message);
    }
  }
}
