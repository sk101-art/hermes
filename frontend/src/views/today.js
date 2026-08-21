/**
 * HERMES Today Inbox View
 * Daily intelligence feed grouped by priority section with progressive disclosure.
 */

import { api } from '../api/endpoints.js';
import { renderStoryCard } from '../components/story-card.js';
import { renderLoadingState, renderEmptyState, renderErrorState, renderOfflineState } from '../components/ui-states.js';
import { escapeHtml, formatDate, ensureArray, toTitleCase } from '../utils/adapters.js';

export async function renderTodayView(container, store) {
  container.innerHTML = renderLoadingState('Loading daily intelligence feed…');

  try {
    const payload = await api.getInbox({ limit: 40 });
    store.setViewData('today', payload);
    store.setConnection('healthy');

    const items = ensureArray(payload.inbox_items || payload.items || payload);
    const sections = {};
    for (const item of items) {
      const sec = item.section || 'must_know';
      if (!sections[sec]) sections[sec] = [];
      sections[sec].push(item);
    }

    const todayDateStr = formatDate(new Date().toISOString());
    const unseenCount = items.filter((i) => i.state === 'unseen').length;
    const projectMatchCount = items.filter((i) => (i.matched_project_ids && i.matched_project_ids.length) || i.project_impact_score > 0).length;

    let html = `
      <div class="page-header-container">
        <div>
          <span class="eyebrow">Daily Intelligence</span>
          <h1>What Matters Today</h1>
          <p class="lead">A calibrated view of technical developments, weighted by evidence, relevance, and change.</p>
        </div>
        <div class="page-header-meta">
          <strong>${items.length}</strong>
          <span>active signals · ${todayDateStr}</span>
        </div>
      </div>

      <div class="hero-stats-grid">
        <div class="stat-card">
          <div class="stat-label">Signal Surface</div>
          <div class="stat-value">${items.length}</div>
          <div class="stat-detail">items in today’s inbox</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">Unseen</div>
          <div class="stat-value">${unseenCount}</div>
          <div class="stat-detail">ready for engineering review</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">Project Matches</div>
          <div class="stat-value">${projectMatchCount}</div>
          <div class="stat-detail">matched to your local projects</div>
        </div>
      </div>
    `;

    const sectionEntries = Object.entries(sections);
    if (!sectionEntries.length) {
      html += renderEmptyState(
        'No Intelligence Signals Available',
        'Ingestion has not populated the today feed yet. Run ingestion or refresh to check for updates.'
      );
    } else {
      for (const [sectionKey, sectionItems] of sectionEntries) {
        html += `
          <div class="section-header">
            <div>
              <h2>${escapeHtml(toTitleCase(sectionKey))}</h2>
              <p class="text-muted text-sm" style="margin:0;">
                ${sectionItems.length} signal${sectionItems.length === 1 ? '' : 's'} · ordered by relevance
              </p>
            </div>
          </div>
          <div class="grid-2">
            ${sectionItems.map(renderStoryCard).join('')}
          </div>
        `;
      }
    }

    container.innerHTML = html;
  } catch (err) {
    if (err.isNetworkError) {
      store.setConnection('offline', err.message);
      container.innerHTML = renderOfflineState(undefined, err.message);
    } else {
      store.setConnection('degraded', err.message);
      container.innerHTML = renderErrorState('Failed to Load Inbox Feed', err.message);
    }
  }
}
