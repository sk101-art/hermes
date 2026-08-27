/**
 * HERMES Morning Briefing View
 * Distilled engineering digest mapping technical shifts, verification changes, and priority reads.
 * Fully date-addressable with historical snapshot fidelity and bounded execution.
 */

import { api } from '../api/endpoints.js';
import { router } from '../state/router.js';
import { renderLoadingState, renderEmptyState, renderErrorState, renderOfflineState } from '../components/ui-states.js';
import { escapeHtml, formatTime, ensureArray, toTitleCase } from '../utils/adapters.js';
import {
  renderInboxPriorityBadge,
  renderInboxRankBadge,
  renderProjectImpactBadge,
} from '../components/badges.js';
import { renderSurfaceControls } from '../components/surface-controls.js';


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

export const CORRECTION_ITEM_TYPES = new Set(['correction']);
export const WEAKENED_ITEM_TYPES = new Set(['claim_weakened']);

export const CORRECTION_REASON_CODES = new Set([
  'correction',
  'claim_retracted',
  'retraction',
]);

export const CORRECTION_REASON_PREFIXES = [
  'correction:',
  'retraction:',
];

export const WEAKENED_REASON_CODES = new Set([
  'claim_weakened',
  'contradiction_detected',
  'intel_change:verification_weakened',
]);

export const WEAKENED_REASON_PREFIXES = [
  'claim_weakened:',
  'contradiction_detected:',
  'intel_change:verification_weakened:',
];

/**
 * Explicitly tests whether an item possesses an audited correction signal.
 * Rejects loose substring matches.
 */
export function isCorrectionSignal(itemType, reasonCodes = []) {
  if (CORRECTION_ITEM_TYPES.has(itemType)) return true;
  for (const rc of reasonCodes) {
    if (typeof rc !== 'string') continue;
    if (CORRECTION_REASON_CODES.has(rc)) return true;
    if (CORRECTION_REASON_PREFIXES.some((prefix) => rc.startsWith(prefix))) return true;
  }
  return false;
}

/**
 * Explicitly tests whether an item possesses an audited weakening signal.
 * Rejects loose substring matches.
 */
export function isWeakenedSignal(itemType, reasonCodes = []) {
  if (WEAKENED_ITEM_TYPES.has(itemType)) return true;
  for (const rc of reasonCodes) {
    if (typeof rc !== 'string') continue;
    if (WEAKENED_REASON_CODES.has(rc)) return true;
    if (WEAKENED_REASON_PREFIXES.some((prefix) => rc.startsWith(prefix))) return true;
  }
  return false;
}

/**
 * Validates that a value is a strict finite number.
 */
export function isValidFiniteNumber(val) {
  return typeof val === 'number' && Number.isFinite(val);
}

/**
 * Safely format reason codes without inventing truth or verification claims.
 */
export function formatBriefingReasonCode(rc) {
  if (typeof rc !== 'string') return '';
  if (rc.startsWith('verified_claim:')) {
    return `Claim Priority Signal: ${rc.slice(15)}`;
  }
  if (rc.startsWith('correction:')) {
    return `Correction: ${rc.slice(11)}`;
  }
  if (rc.startsWith('retraction:')) {
    return `Retraction: ${rc.slice(11)}`;
  }
  if (rc.startsWith('claim_weakened:')) {
    return `Claim Weakened: ${rc.slice(15)}`;
  }
  if (rc.startsWith('contradiction_detected:')) {
    return `Contradiction Detected: ${rc.slice(23)}`;
  }
  if (rc.startsWith('intel_change:verification_weakened:')) {
    return `Claim Support Weakened: ${rc.slice(35)}`;
  }
  if (rc.startsWith('direct_dependency_match:')) {
    return `Direct Dependency: ${rc.slice(24).replace('project:', '')}`;
  }
  if (rc.startsWith('dependency_match:')) {
    return `Dependency: ${rc.slice(17)}`;
  }
  if (rc.startsWith('project_match:')) {
    return `Project Context: ${toTitleCase(rc.slice(14).replace(/_/g, ' '))}`;
  }
  const mapping = {
    recent_discovery: 'Recent Discovery',
    official_release: 'Official Release',
    high_interest: 'High Interest',
    starred: 'Starred Item',
    direct_project_dep: 'Direct Project Dependency',
    project_tech_match: 'Project Technology Match',
    correction: 'Correction',
    claim_retracted: 'Claim Retracted',
    retraction: 'Retraction',
    claim_weakened: 'Claim Weakened',
    contradiction_detected: 'Contradiction Detected',
    'intel_change:verification_weakened': 'Claim Support Weakened',
    'intel_change:verification_strengthened': 'Claim Support Changed',
  };
  return mapping[rc] || toTitleCase(rc.replace(/_/g, ' '));
}

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
 * Renders state banners from the enriched /briefing payload:
 * quiet day (completed_empty), failed (retry + last-successful link),
 * running progress, partial sources, source contribution, revision note.
 */
export function renderBriefingStateBanner(briefing) {
  const status = briefing.generation_status || 'completed';
  const dailyRun = briefing.daily_run || null;
  const parts = [];

  if (status === 'completed_empty') {
    parts.push(`
      <div class="panel briefing-state-panel briefing-state-quiet" role="status" style="border-left:3px solid var(--state-info, #2563eb);padding:var(--space-6);">
        <h2 style="margin-bottom:var(--space-2);">Quiet Day — No Qualifying Signals</h2>
        <p class="text-muted" style="line-height:var(--leading-relaxed);">
          HERMES completed today's refresh; no signals passed relevance/quality thresholds.
          This is a truthful zero-item snapshot — nothing was padded or fabricated.
        </p>
      </div>
    `);
  } else if (status === 'failed') {
    const failedAt = dailyRun && dailyRun.completed_at ? formatTime(dailyRun.completed_at) : 'an unknown time';
    const errorText = (dailyRun && dailyRun.error_summary) ? dailyRun.error_summary : 'No error details were recorded.';
    const nextRetry = briefing.next_retry_at ? formatTime(briefing.next_retry_at) : '';
    const lastGood = briefing.last_successful_briefing_date;
    parts.push(`
      <div class="panel briefing-state-panel briefing-state-failed" role="alert" style="border-left:3px solid var(--state-danger, #dc2626);padding:var(--space-6);">
        <h2 style="margin-bottom:var(--space-2);">Daily Refresh Failed</h2>
        <p class="text-muted">The daily intelligence cycle for this date failed at <strong>${escapeHtml(failedAt)}</strong>. No briefing snapshot was written for this day.</p>
        <p class="text-sm" style="margin-top:var(--space-2);"><span class="text-semibold">Error:</span> <span class="mono">${escapeHtml(errorText)}</span></p>
        ${nextRetry ? `<p class="text-sm" style="margin-top:var(--space-1);"><span class="text-semibold">Next automatic retry:</span> ${escapeHtml(nextRetry)}</p>` : ''}
        ${lastGood ? `<p class="text-sm" style="margin-top:var(--space-2);">Latest available briefing: <a href="#/briefing?date=${encodeURIComponent(lastGood)}" class="briefing-last-success-link">${escapeHtml(lastGood)}</a></p>` : ''}
      </div>
    `);
  } else if (status === 'running') {
    const opId = (dailyRun && dailyRun.id) || briefing.daily_run_id || '';
    parts.push(`
      <div class="panel briefing-state-panel briefing-state-running" role="status" style="border-left:3px solid var(--state-info, #2563eb);padding:var(--space-6);">
        <h2 style="margin-bottom:var(--space-2);">Daily Refresh In Progress</h2>
        <p class="text-muted">The daily intelligence cycle for this date is currently running. The briefing snapshot will appear when the cycle completes.</p>
        ${opId ? `<p class="text-sm" style="margin-top:var(--space-2);"><span class="text-semibold">Run ID:</span> <span class="mono">${escapeHtml(opId)}</span></p>` : ''}
      </div>
    `);
  }

  if (status === 'partial_sources') {
    const sc = briefing.source_contribution || {};
    const failedSources = ensureArray(sc.sources_failed);
    parts.push(`
      <div class="panel briefing-state-panel briefing-state-partial" role="status" style="border-left:3px solid var(--state-warning, #d97706);padding:var(--space-4);">
        <p class="text-sm"><span class="text-semibold">Partial source coverage:</span> ${failedSources.length ? `the following sources failed during this cycle: ${failedSources.map(s => `<span class="mono">${escapeHtml(s)}</span>`).join(', ')}.` : 'one or more sources failed during this cycle.'} Results may be incomplete.</p>
      </div>
    `);
  }

  // Source contribution summary (counts of polled/skipped/failed)
  const sc = briefing.source_contribution || {};
  const polled = ensureArray(sc.sources_polled);
  const skipped = ensureArray(sc.sources_skipped);
  const failed = ensureArray(sc.sources_failed);
  if (polled.length || skipped.length || failed.length) {
    parts.push(`
      <div class="panel briefing-source-contribution" style="padding:var(--space-4);">
        <h3 class="text-sm text-semibold" style="margin-bottom:var(--space-2);">Source Contribution</h3>
        <div class="text-sm text-muted" style="display:flex;gap:var(--space-4);flex-wrap:wrap;">
          <span>Polled: <strong>${polled.length}</strong></span>
          <span>Skipped: <strong>${skipped.length}</strong></span>
          <span>Failed: <strong>${failed.length}</strong></span>
        </div>
      </div>
    `);
  }

  // Revision note when the snapshot has been revised instead of replaced
  const revisionCount = briefing.revision_count ?? 0;
  if (revisionCount > 0) {
    parts.push(`
      <p class="text-xs text-muted briefing-revision-note">This briefing has been revised ${revisionCount} time${revisionCount === 1 ? '' : 's'} since its original generation. The original snapshot is preserved in revision history.</p>
    `);
  }

  return parts.join('\n');
}

/**
 * Renders an individual briefing snapshot item.
 */
export function renderBriefingItemCard(item) {
  const isLegacy = item.snapshot_status === 'legacy_incomplete';
  const isUnrecognized = item.snapshot_status === 'unrecognized_version';
  const hasStoryLink = Boolean(item.story_available && item.story_cluster_id);
  const reasonCodes = ensureArray(item.reason_codes);
  const matchedProjects = ensureArray(item.matched_project_ids);

  // Check correction and weakening semantics strictly using audited exact codes and prefixes
  const isCorrection = isCorrectionSignal(item.item_type, reasonCodes);
  const isWeakened = isWeakenedSignal(item.item_type, reasonCodes);

  let cardClasses = 'panel briefing-item-card';
  if (isCorrection) cardClasses += ' briefing-card-cautionary';
  if (isWeakened) cardClasses += ' briefing-card-weakened';

  // Title rendering: do NOT synthesize "Untitled snapshot item"
  let titleHtml = '';
  if (item.title) {
    if (hasStoryLink) {
      titleHtml = `<a href="#/story/${encodeURIComponent(item.story_cluster_id)}" class="briefing-title-link" data-testid="briefing-story-link-${escapeHtml(item.inbox_item_id || item.story_cluster_id)}">${escapeHtml(item.title)}</a>`;
    } else {
      titleHtml = `<span class="text-semibold text-foreground">${escapeHtml(item.title)}</span>`;
    }
  } else {
    titleHtml = `<span class="briefing-missing-notice">Title was not captured in this legacy snapshot</span>`;
  }

  // Summary rendering: do NOT fabricate summary or copy title
  const summaryHtml = item.summary
    ? `<p class="briefing-item-summary">${escapeHtml(item.summary)}</p>`
    : '';

  // Type badge: do NOT default to 'story'
  const typeBadgeHtml = item.item_type
    ? `<span class="briefing-type-tag">${escapeHtml(toTitleCase(item.item_type))}</span>`
    : '';

  // Cautionary tags
  const cautionTagHtml = isCorrection
    ? `<span class="briefing-caution-tag">Correction</span>`
    : isWeakened
    ? `<span class="briefing-weakened-tag">Weakened Support</span>`
    : '';

  // Snapshot status badge
  let snapshotStatusBadge = '';
  if (isLegacy) {
    snapshotStatusBadge = `<span class="briefing-legacy-badge" title="Captured before schema snapshotting; unrecorded fields omitted">Legacy Snapshot</span>`;
  } else if (isUnrecognized) {
    const versionLabel = item.snapshot_version ? ` (${escapeHtml(item.snapshot_version)})` : '';
    snapshotStatusBadge = `<span class="briefing-unrecognized-badge" title="Snapshot format is not recognized; some fields may not display reliably">Unrecognized Snapshot${versionLabel}</span>`;
  }

  // Unrecognized version notice
  const unrecognizedNoticeHtml = isUnrecognized
    ? `<div class="briefing-unrecognized-notice">Snapshot format (${escapeHtml(item.snapshot_version || 'unknown')}) is not recognized. Schema-dependent score fields are omitted.</div>`
    : '';

  // Score badges via shared domain formatters (omitted if unrecognized version or invalid)
  const priorityBadge = !isUnrecognized ? renderInboxPriorityBadge(item.inbox_score) : '';
  const rankBadge = !isUnrecognized ? renderInboxRankBadge(item.rank_score) : '';
  const impactBadge = !isUnrecognized ? renderProjectImpactBadge(item.project_impact_score) : '';

  return `
    <article class="${cardClasses}" data-inbox-id="${escapeHtml(item.inbox_item_id || '')}">
      <div class="briefing-item-header">
        <span class="briefing-pos-badge" aria-label="Item #${item.position}">#${item.position}</span>
        ${typeBadgeHtml}
        ${cautionTagHtml}
        ${snapshotStatusBadge}
        <h3 class="briefing-item-title" style="display:inline;margin:0;font-size:inherit;font-weight:inherit;">${titleHtml}</h3>
      </div>

      ${summaryHtml}
      ${unrecognizedNoticeHtml}

      <div class="briefing-item-meta-row">
        ${priorityBadge}
        ${rankBadge}
        ${impactBadge}

        ${reasonCodes.map(rc => `<span class="briefing-reason-pill" data-reason-code="${escapeHtml(String(rc))}">${escapeHtml(formatBriefingReasonCode(String(rc)))}</span>`).join('')}

        ${matchedProjects.map(pid => `
          <a href="#/projects/${encodeURIComponent(pid)}" class="briefing-project-pill" title="Matched Project">
            <span>↳ ${escapeHtml(pid)}</span>
          </a>
        `).join('')}

        ${
          hasStoryLink
            ? `<div style="margin-left:auto;"><a href="#/story/${encodeURIComponent(item.story_cluster_id)}" class="btn btn-secondary btn-xs" data-testid="briefing-open-story-${escapeHtml(item.inbox_item_id || item.story_cluster_id)}">Open Story Dossier →</a></div>`
            : item.story_cluster_id
            ? `<div style="margin-left:auto;"><span class="text-xs text-muted briefing-story-unavailable">Story unavailable</span></div>`
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

  // Shell-first: paint the route header (h1) synchronously before any await so
  // hash transitions resolve quickly; content fills in after the fetch.
  container.innerHTML = `
    <div class="page-header-container">
      <div>
        <span class="eyebrow">Daily Intelligence</span>
        <h1>Morning Briefing</h1>
        <p class="lead">A date-addressable engineering read: what deserved attention, why it was selected, and historical intelligence snapshots.</p>
      </div>
      <div class="page-header-meta" style="display:flex; flex-direction:column; align-items:flex-end; gap:var(--space-2);">
        ${renderDateToolbar(activeDate, todayIso)}
        <div id="briefing-refresh-container"></div>
      </div>
    </div>
    <div class="briefing-content-area">
      ${renderLoadingState(`Loading morning briefing digest for ${escapeHtml(activeDate)}…`)}
    </div>
  `;

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

    const hasItems = (briefing.total_items > 0) || (orderedSections.some(secKey => sections[secKey] && sections[secKey].length > 0));
    const briefingDateStr = briefing.briefing_date || activeDate;
    const generationStatus = briefing.generation_status || 'completed';
    const isRunOnlyState = generationStatus === 'failed' || generationStatus === 'running';

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
    } else if (generationStatus === 'completed_empty') {
      // Quiet-day panel is rendered via the state banner; no padding.
      sectionsHtml = '';
    } else if (!isRunOnlyState) {
      sectionsHtml = `
        <div class="panel" style="padding:var(--space-8);text-align:center;">
          <p class="text-muted">No items recorded in this briefing digest.</p>
        </div>
      `;
    }

    let announcerText = `Briefing for ${briefingDateStr} loaded with ${briefing.total_items ?? 0} items.`;
    if (generationStatus === 'completed_empty') {
      announcerText = `Daily refresh for ${briefingDateStr} completed with no qualifying signals.`;
    } else if (generationStatus === 'failed') {
      announcerText = `Daily refresh for ${briefingDateStr} failed. Showing failure details and retry information.`;
    } else if (generationStatus === 'running') {
      announcerText = `Daily refresh for ${briefingDateStr} is in progress.`;
    }

    const stateBannerHtml = renderBriefingStateBanner(briefing);
    const summaryPanelHtml = isRunOnlyState ? '' : `
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

        <div class="briefing-disclosure-notice">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
            <circle cx="12" cy="12" r="10"></circle>
            <line x1="12" y1="16" x2="12" y2="12"></line>
            <line x1="12" y1="8" x2="12.01" y2="8"></line>
          </svg>
          <span>This briefing is a stored snapshot generated from HERMES intelligence available at the displayed generation time. Current Story Dossiers may have changed since then.</span>
        </div>

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
    `;

    const html = `
      <div id="briefing-announcer" class="sr-only" aria-live="polite" aria-atomic="true">
        ${announcerText}
      </div>

      <div class="page-header-container">
        <div>
          <span class="eyebrow">Daily Intelligence</span>
          <h1>Morning Briefing</h1>
          <p class="lead">A date-addressable engineering read: what deserved attention, why it was selected, and historical intelligence snapshots.</p>
        </div>
        <div class="page-header-meta" style="display:flex; flex-direction:column; align-items:flex-end; gap:var(--space-2);">
          ${renderDateToolbar(briefingDateStr, todayIso)}
          <div id="briefing-refresh-container"></div>
        </div>
      </div>

      ${stateBannerHtml}

      ${summaryPanelHtml}

      <div class="briefing-content-area">
        ${sectionsHtml}
      </div>
    `;

    container.innerHTML = html;
    bindBriefingEvents(container, todayIso);

    const refreshContainer = container.querySelector('#briefing-refresh-container');
    if (refreshContainer) {
      const cleanup = renderSurfaceControls(refreshContainer, {
        scope: 'daily_refresh',
        onRefresh: () => renderBriefingView(container, store, params),
        syncLabel: 'Sync Data',
      });
      container._viewCleanup = cleanup;
    }

  } catch (err) {
    // Navigation aborted the in-flight fetch: the container now belongs to
    // the next view, so never write a stale error state into it.
    if (err && err.isAborted && !err.isTimeout) return;
    if (requestToken !== activeBriefingRequestToken) return;

    if (err.isNetworkError) {
      store.setConnection('offline', err.message);
      container.innerHTML = renderOfflineState(undefined, err.message, () => renderBriefingView(container, store, params));
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
          <div class="page-header-meta" style="display:flex; flex-direction:column; align-items:flex-end; gap:var(--space-2);">
            ${renderDateToolbar(activeDate, todayIso)}
            <div id="briefing-refresh-container"></div>
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

      const refreshContainer = container.querySelector('#briefing-refresh-container');
      if (refreshContainer) {
        const cleanup = renderSurfaceControls(refreshContainer, {
          scope: 'daily_refresh',
          onRefresh: () => renderBriefingView(container, store, params),
          syncLabel: 'Sync Data',
        });
        container._viewCleanup = cleanup;
      }
    } else if (err.status === 422) {
      // Invalid date format or impossible date
      const invalidDateHtml = `
        <div id="briefing-announcer" class="sr-only" aria-live="polite" aria-atomic="true">
          Invalid briefing date: ${escapeHtml(activeDate)}.
        </div>

        <div class="page-header-container">
          <div>
            <span class="eyebrow">Daily Intelligence</span>
            <h1>Morning Briefing</h1>
            <p class="lead">A date-addressable engineering read: what deserved attention, why it was selected, and historical intelligence snapshots.</p>
          </div>
          <div class="page-header-meta">
            ${renderDateToolbar(todayIso, todayIso)}
          </div>
        </div>

        <div class="panel" style="padding:var(--space-8);text-align:center;margin-top:var(--space-4);border-left:3px solid var(--state-danger);">
          <h2 style="margin-bottom:var(--space-2);">Invalid Briefing Date</h2>
          <p class="text-muted" style="max-width:560px;margin:0 auto var(--space-4) auto;">
            The requested date <strong>${escapeHtml(activeDate)}</strong> is not a valid calendar date (format: YYYY-MM-DD). Please select a valid date using the controls above.
          </p>
          <div style="display:flex;gap:var(--space-3);justify-content:center;">
            <button class="btn btn-primary btn-sm briefing-today-btn">Go to Today</button>
          </div>
        </div>
      `;
      container.innerHTML = invalidDateHtml;
      bindBriefingEvents(container, todayIso);
    } else {
      store.setConnection('degraded', err.message);
      container.innerHTML = renderErrorState('Failed to Load Morning Briefing', err.message, () => renderBriefingView(container, store, params));
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
