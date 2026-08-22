/**
 * HERMES Morning Briefing View
 * Distilled engineering digest mapping technical shifts, verification changes, and priority reads.
 * Fully date-addressable with historical snapshot fidelity and bounded execution.
 */

import { api } from '../api/endpoints.js';
import { router } from '../state/router.js';
import { renderLoadingState, renderEmptyState, renderErrorState, renderOfflineState } from '../components/ui-states.js';
import { escapeHtml, formatTime, ensureArray, toTitleCase } from '../utils/adapters.js';

let activeBriefingRequestToken = 0;

export const SECTION_HEADERS = {
  corrections_updates: 'What Changed / Corrections',
  must_know: 'Must Know',
  project_relevant: 'Relevant to Your Projects',
  systems_compilers: 'Systems / Compilers / Acceleration',
  storage_databases: 'Storage / Databases / Vector Search',
  research: 'Research & Benchmarks',
  ai_ml: 'AI / Machine Learning',
  developer_tooling: 'Developer Tooling',
  watchlist: 'Watchlist',
};

export const SECTION_ORDER = [
  'corrections_updates',
  'must_know',
  'project_relevant',
  'systems_compilers',
  'storage_databases',
  'research',
  'ai_ml',
  'developer_tooling',
  'watchlist',
];

/**
 * Format a Date object to YYYY-MM-DD in UTC.
 */
function formatDateUtc(date) {
  const y = date.getUTCFullYear();
  const m = String(date.getUTCMonth() + 1).padStart(2, '0');
  const d = String(date.getUTCDate()).padStart(2, '0');
  return `${y}-${m}-${d}`;
}

/**
 * Add / subtract days from a YYYY-MM-DD string.
 */
function shiftDateStr(dateStr, days) {
  try {
    const parts = dateStr.split('-');
    if (parts.length !== 3) return dateStr;
    const dt = new Date(Date.UTC(parseInt(parts[0], 10), parseInt(parts[1], 10) - 1, parseInt(parts[2], 10)));
    dt.setUTCDate(dt.getUTCDate() + days);
    return formatDateUtc(dt);
  } catch (e) {
    return dateStr;
  }
}

/**
 * Renders the date toolbar controls.
 */
function renderDateToolbar(activeDate, todayIso) {
  const isToday = activeDate === todayIso;
  const isFuture = activeDate > todayIso;
  const prevDate = shiftDateStr(activeDate, -1);
  const nextDate = shiftDateStr(activeDate, 1);

  return `
    <div class="briefing-toolbar" role="toolbar" aria-label="Briefing date navigation">
      <button class="btn btn-secondary btn-sm briefing-prev-btn" data-target-date="${escapeHtml(prevDate)}" aria-label="Previous day: ${escapeHtml(prevDate)}">
        ← Prev
      </button>
      <input
        type="date"
        id="briefing-date-input"
        class="input input-sm briefing-date-input"
        value="${escapeHtml(activeDate)}"
        max="${escapeHtml(todayIso)}"
        aria-label="Select briefing date"
      />
      <button
        class="btn btn-secondary btn-sm briefing-next-btn"
        data-target-date="${escapeHtml(nextDate)}"
        aria-label="Next day: ${escapeHtml(nextDate)}"
        ${isToday || isFuture ? 'disabled' : ''}
      >
        Next →
      </button>
      <button
        class="btn btn-secondary btn-sm briefing-today-btn"
        aria-label="Jump to today"
        ${isToday ? 'disabled' : ''}
      >
        Today
      </button>
    </div>
  `;
}

/**
 * Renders an individual briefing snapshot item.
 */
function renderBriefingItemCard(item) {
  const isLegacy = item.snapshot_status === 'legacy_incomplete';
  const hasStoryLink = Boolean(item.story_available && item.story_cluster_id);
  const title = item.title || 'Untitled snapshot item';
  const summary = item.summary || title;
  const itemType = item.item_type || 'story';
  const reasonCodes = ensureArray(item.reason_codes);
  const matchedProjects = ensureArray(item.matched_project_ids);

  // Truthful score rendering (priority vs ranking vs project impact)
  const inboxScoreStr = item.inbox_score !== null && item.inbox_score !== undefined
    ? `Priority: ${Number(item.inbox_score).toFixed(2)}`
    : 'Priority: unrated';

  const rankScoreStr = item.rank_score !== null && item.rank_score !== undefined
    ? `Rank: ${Number(item.rank_score).toFixed(2)}`
    : null;

  const projectImpactStr = item.project_impact_score !== null && item.project_impact_score !== undefined
    ? `Project Impact: ${Number(item.project_impact_score).toFixed(2)}`
    : null;

  return `
    <article class="panel briefing-item-card" data-inbox-id="${escapeHtml(item.inbox_item_id || '')}">
      <div class="briefing-item-header">
        <span class="briefing-pos-badge" aria-label="Item #${item.position}">#${item.position}</span>
        <span class="briefing-type-tag">${escapeHtml(toTitleCase(itemType))}</span>
        ${isLegacy ? `<span class="briefing-legacy-badge" title="Captured before schema snapshotting; unrecorded fields omitted">Legacy Snapshot</span>` : ''}
        ${
          hasStoryLink
            ? `<a href="#/story/${encodeURIComponent(item.story_cluster_id)}" class="briefing-title-link">${escapeHtml(title)}</a>`
            : `<span class="text-semibold text-foreground">${escapeHtml(title)}</span>`
        }
      </div>

      <p class="briefing-item-summary">${escapeHtml(summary)}</p>

      <div class="briefing-item-meta-row">
        <span class="briefing-score-badge" title="Daily briefing surfacing priority">${escapeHtml(inboxScoreStr)}</span>
        ${rankScoreStr ? `<span class="briefing-score-badge text-muted" title="Feed ranking score">${escapeHtml(rankScoreStr)}</span>` : ''}
        ${projectImpactStr ? `<span class="briefing-impact-badge" title="Project relevance score">${escapeHtml(projectImpactStr)}</span>` : ''}

        ${reasonCodes.map(rc => `<span class="briefing-reason-pill">${escapeHtml(rc)}</span>`).join('')}

        ${matchedProjects.map(pid => `
          <a href="#/projects/${encodeURIComponent(pid)}" class="briefing-project-pill" title="Matched Project">
            <span>↳ ${escapeHtml(pid)}</span>
          </a>
        `).join('')}

        ${
          hasStoryLink
            ? `<div style="margin-left:auto;"><a href="#/story/${encodeURIComponent(item.story_cluster_id)}" class="btn btn-secondary btn-xs">Open Story Dossier →</a></div>`
            : item.story_cluster_id
            ? `<div style="margin-left:auto;"><span class="text-xs text-muted">Story cluster not currently active</span></div>`
            : ''
        }
      </div>
    </article>
  `;
}

/**
 * Main view renderer for Morning Briefing.
 */
export async function renderBriefingView(container, store, params = {}) {
  const requestToken = ++activeBriefingRequestToken;
  const todayIso = formatDateUtc(new Date());
  const requestedDate = params && params.date ? params.date.trim() : '';
  const activeDate = requestedDate || todayIso;

  container.innerHTML = renderLoadingState(`Loading morning briefing digest for ${escapeHtml(activeDate)}…`);

  try {
    const apiParams = requestedDate ? { date: requestedDate } : {};
    const briefing = await api.getBriefing(apiParams);

    // Stale response guard
    if (requestToken !== activeBriefingRequestToken) return;

    store.setViewData('briefing', briefing);
    store.setConnection('healthy');

    const sections = briefing.sections || {};
    const orderedSections = briefing.ordered_sections && briefing.ordered_sections.length > 0
      ? briefing.ordered_sections
      : SECTION_ORDER.filter(secKey => sections[secKey] && sections[secKey].length > 0);

    const hasItems = briefing.total_items > 0 || orderedSections.length > 0;
    const briefingDateStr = briefing.briefing_date || activeDate;

    let sectionsHtml = '';
    if (hasItems) {
      for (const secKey of orderedSections) {
        const secItems = ensureArray(sections[secKey]);
        if (secItems.length === 0) continue;
        const headerTitle = SECTION_HEADERS[secKey] || toTitleCase(secKey);

        sectionsHtml += `
          <section class="briefing-section-container" aria-labelledby="section-heading-${escapeHtml(secKey)}">
            <h2 id="section-heading-${escapeHtml(secKey)}" class="briefing-section-title">
              <span>${escapeHtml(headerTitle)}</span>
              <span class="text-xs text-muted font-normal">(${secItems.length})</span>
            </h2>
            <div class="briefing-items-grid">
              ${secItems.map(it => renderBriefingItemCard(it)).join('')}
            </div>
          </section>
        `;
      }
    } else {
      sectionsHtml = `
        <div class="panel" style="padding:var(--space-8);text-align:center;">
          <p class="text-muted">No items recorded in this briefing digest.</p>
        </div>
      `;
    }

    const html = `
      <div id="briefing-announcer" class="sr-only" aria-live="polite" aria-atomic="true">
        Briefing for ${escapeHtml(briefingDateStr)} loaded with ${briefing.total_items ?? 0} items.
      </div>

      <div class="page-header-container">
        <div>
          <span class="eyebrow">Daily Intelligence</span>
          <h1>Morning Briefing</h1>
          <p class="lead">A date-addressable engineering read: what deserved attention, why it was selected, and historical intelligence snapshots.</p>
        </div>
        <div class="page-header-meta">
          ${renderDateToolbar(briefingDateStr, todayIso)}
        </div>
      </div>

      <div class="briefing-summary-panel">
        <div style="display:flex;align-items:baseline;justify-content:space-between;gap:var(--space-4);flex-wrap:wrap;">
          <div>
            <span class="eyebrow">${escapeHtml(briefingDateStr)} Digest</span>
            <h2 style="margin:var(--space-1) 0;">Executive Summary</h2>
          </div>
          <div class="text-xs text-muted">
            <span>Generated ${formatTime(briefing.generated_at)}</span>
            ${briefing.content_hash ? ` · <span class="mono" title="SHA-256: ${escapeHtml(briefing.content_hash)}">Hash: ${escapeHtml(briefing.content_hash.slice(0, 8))}…</span>` : ''}
          </div>
        </div>

        <p style="margin-top:var(--space-3);line-height:var(--leading-relaxed);white-space:pre-line;">
          ${escapeHtml(briefing.summary_text || 'No summary text was generated for this briefing.')}
        </p>

        <div class="briefing-stats-row">
          <div class="briefing-stat-pill">
            <span>Total Items:</span>
            <span class="briefing-stat-val">${briefing.total_items ?? 0}</span>
          </div>
          <div class="briefing-stat-pill">
            <span>Must Know:</span>
            <span class="briefing-stat-val">${briefing.high_priority_count ?? 0}</span>
          </div>
          <div class="briefing-stat-pill">
            <span>Project Relevant:</span>
            <span class="briefing-stat-val">${briefing.project_relevant_count ?? 0}</span>
          </div>
        </div>
      </div>

      <div class="briefing-content-area">
        ${sectionsHtml}
      </div>
    `;

    container.innerHTML = html;
    bindBriefingEvents(container, todayIso);

  } catch (err) {
    if (requestToken !== activeBriefingRequestToken) return;

    if (err.isNetworkError) {
      store.setConnection('offline', err.message);
      container.innerHTML = renderOfflineState(undefined, err.message);
    } else if (err.status === 404) {
      // Briefing not found for date
      const notFoundHtml = `
        <div id="briefing-announcer" class="sr-only" aria-live="polite" aria-atomic="true">
          No briefing found for ${escapeHtml(activeDate)}.
        </div>

        <div class="page-header-container">
          <div>
            <span class="eyebrow">Daily Intelligence</span>
            <h1>Morning Briefing</h1>
            <p class="lead">A date-addressable engineering read: what deserved attention, why it was selected, and historical intelligence snapshots.</p>
          </div>
          <div class="page-header-meta">
            ${renderDateToolbar(activeDate, todayIso)}
          </div>
        </div>

        <div class="panel" style="padding:var(--space-8);text-align:center;margin-top:var(--space-4);">
          <h2 style="margin-bottom:var(--space-2);">No Briefing Snapshot Found</h2>
          <p class="text-muted" style="max-width:560px;margin:0 auto var(--space-4) auto;">
            No daily briefing snapshot was recorded for <strong>${escapeHtml(activeDate)}</strong>. Choose another date using the date selector above or return to today's briefing.
          </p>
          <div style="display:flex;gap:var(--space-3);justify-content:center;">
            <button class="btn btn-primary btn-sm briefing-today-btn">Go to Today</button>
            <button class="btn btn-secondary btn-sm briefing-prev-btn" data-target-date="${escapeHtml(shiftDateStr(activeDate, -1))}">View Previous Day</button>
          </div>
        </div>
      `;
      container.innerHTML = notFoundHtml;
      bindBriefingEvents(container, todayIso);
    } else {
      store.setConnection('degraded', err.message);
      container.innerHTML = renderErrorState('Failed to Load Morning Briefing', err.message);
    }
  }
}

/**
 * Binds toolbar interactive events.
 */
function bindBriefingEvents(container, todayIso) {
  const dateInput = container.querySelector('#briefing-date-input');
  if (dateInput) {
    dateInput.addEventListener('change', (e) => {
      const selected = e.target.value;
      if (selected) {
        if (selected === todayIso) {
          router.navigate('briefing');
        } else {
          router.navigate(`briefing?date=${encodeURIComponent(selected)}`);
        }
      }
    });
  }

  const prevBtns = container.querySelectorAll('.briefing-prev-btn');
  prevBtns.forEach(btn => {
    btn.addEventListener('click', () => {
      const targetDate = btn.getAttribute('data-target-date');
      if (targetDate) {
        router.navigate(`briefing?date=${encodeURIComponent(targetDate)}`);
      }
    });
  });

  const nextBtns = container.querySelectorAll('.briefing-next-btn');
  nextBtns.forEach(btn => {
    btn.addEventListener('click', () => {
      const targetDate = btn.getAttribute('data-target-date');
      if (targetDate) {
        if (targetDate === todayIso) {
          router.navigate('briefing');
        } else {
          router.navigate(`briefing?date=${encodeURIComponent(targetDate)}`);
        }
      }
    });
  });

  const todayBtns = container.querySelectorAll('.briefing-today-btn');
  todayBtns.forEach(btn => {
    btn.addEventListener('click', () => {
      router.navigate('briefing');
    });
  });
}
