/**
 * HERMES Changes View
 * Longitudinal Intelligence Surface for verification, contradiction, maturity, and risk shifts.
 * Distinguishes genuine intelligence evolution from system-generated maintenance records.
 */

import { api } from '../api/endpoints.js';
import { getIcon } from '../icons/index.js';
import {
  renderLoadingState,
  renderEmptyState,
  renderErrorState,
  renderOfflineState,
} from '../components/ui-states.js';
import {
  escapeHtml,
  formatDate,
  ensureArray,
  toTitleCase,
} from '../utils/adapters.js';

// Canonical ClaimStatus and Maturity taxonomies
export const CANONICAL_CLAIM_STATUSES = {
  strongly_supported: 'Strongly Supported',
  supported: 'Supported',
  weakly_supported: 'Weakly Supported',
  mixed: 'Mixed',
  contradicted: 'Contradicted',
  unverified: 'Unverified',
  superseded: 'Superseded',
  retracted: 'Retracted',
};

export const CANONICAL_MATURITY_STAGES = {
  concept: 'Concept',
  research: 'Research',
  prototype: 'Prototype',
  experimental: 'Experimental',
  early_adoption: 'Early Adoption',
  production_candidate: 'Production Candidate',
  established: 'Established',
};

export const ORIGIN_METADATA = {
  new_evidence: {
    label: 'New Evidence',
    badgeClass: 'badge-origin-evidence',
    isSystem: false,
    description: 'Observed from fresh corroborating or contradictory evidence records.',
  },
  actual_revision: {
    label: 'Actual Revision',
    badgeClass: 'badge-origin-revision',
    isSystem: false,
    description: 'Intelligence re-evaluation produced a revised claim or assessment.',
  },
  new_release: {
    label: 'New Release',
    badgeClass: 'badge-origin-release',
    isSystem: false,
    description: 'Associated software repository or model artifact release.',
  },
  live_update: {
    label: 'Live Update',
    badgeClass: 'badge-origin-live',
    isSystem: false,
    description: 'Autonomous ingestion pipeline update.',
  },
  source_refresh: {
    label: 'Source Refresh',
    badgeClass: 'badge-origin-system',
    isSystem: true,
    description: 'Source metadata refresh without semantic claim mutation.',
  },
  migration: {
    label: 'System Migration',
    badgeClass: 'badge-origin-system',
    isSystem: true,
    description: 'Technical schema migration or legacy data normalization record.',
  },
  backfill_initialization: {
    label: 'Backfill Initialization',
    badgeClass: 'badge-origin-system',
    isSystem: true,
    description: 'Baseline backfill record generated during system bootstrap.',
  },
  recompute: {
    label: 'Engine Recompute',
    badgeClass: 'badge-origin-recompute',
    isSystem: true,
    description: 'Deterministic pipeline score recomputation.',
  },
  manual_rebuild: {
    label: 'Manual Rebuild',
    badgeClass: 'badge-origin-system',
    isSystem: true,
    description: 'Administrative index or cluster rebuild.',
  },
};

/**
 * Resolves the semantic categorization for a change record to ensure truthful domain formatting.
 */
export function getChangeSemanticCategory(changeType = '', entityType = '') {
  const ct = String(changeType || '').toLowerCase();
  const et = String(entityType || '').toLowerCase();

  if (ct.includes('maturity') || et === 'technology_assessment') {
    return 'maturity';
  }
  if (
    ct.includes('claim_status') ||
    ct.includes('verification_') ||
    ct.includes('claim_revision') ||
    ct.includes('claim_retracted') ||
    ct.includes('claim_created') ||
    (et === 'claim' && (ct.includes('status') || ct.includes('verification') || ct.includes('state') || ct === 'claim_revision'))
  ) {
    return 'claim_status';
  }
  return 'generic';
}

/**
 * Formats a value token (status, maturity stage, or score string) into a readable representation.
 * Enforces strict canonical taxonomies for maturity stages and claim statuses.
 */
export function formatTransitionValue(rawVal, context = 'generic', isOld = true) {
  if (rawVal === null || rawVal === undefined || rawVal === '') {
    return isOld
      ? `<span class="transition-not-recorded">Previous state not recorded historically</span>`
      : `<span class="transition-not-recorded">New state unspecified</span>`;
  }

  const str = String(rawVal).trim();

  // Normalize category if changeType or raw context was passed directly
  let category = context;
  if (category !== 'maturity' && category !== 'claim_status' && category !== 'generic') {
    category = getChangeSemanticCategory(context);
  }

  // Check if string is formatted with score, e.g. "status (0.8500)" or "growth (0.72)"
  const scoreMatch = str.match(/^([a-zA-Z0-9_.-]+)\s*\(([0-9.]+)\)$/);
  const token = (scoreMatch ? scoreMatch[1] : str).toLowerCase();
  const scorePct = scoreMatch
    ? (!isNaN(parseFloat(scoreMatch[2]))
        ? ` (${Math.round(parseFloat(scoreMatch[2]) * 100)}%)`
        : ` (${scoreMatch[2]})`)
    : '';

  if (category === 'maturity') {
    if (CANONICAL_MATURITY_STAGES[token]) {
      return `<strong>${escapeHtml(CANONICAL_MATURITY_STAGES[token])}</strong><span class="mono text-xs">${scorePct}</span>`;
    }
    return `<strong>Unrecognized maturity</strong><span class="mono text-xs">${scorePct}</span>`;
  }

  if (category === 'claim_status') {
    if (CANONICAL_CLAIM_STATUSES[token]) {
      return `<strong>${escapeHtml(CANONICAL_CLAIM_STATUSES[token])}</strong><span class="mono text-xs">${scorePct}</span>`;
    }
    return `<strong>Unrecognized claim status</strong><span class="mono text-xs">${scorePct}</span>`;
  }

  // Generic change values (e.g. version numbers, custom state)
  if (scoreMatch) {
    return `<strong>${escapeHtml(toTitleCase(scoreMatch[1]))}</strong><span class="mono text-xs">${scorePct}</span>`;
  }
  return `<strong>${escapeHtml(str)}</strong>`;
}

/**
 * Formats importance level into a standardized label and badge class.
 */
export function formatImportance(importance, importanceLevel) {
  let level = (importanceLevel || '').toLowerCase();
  if (!level) {
    if (typeof importance === 'number') {
      if (importance >= 0.85) level = 'critical';
      else if (importance >= 0.65) level = 'high';
      else if (importance >= 0.35) level = 'medium';
      else level = 'low';
    } else if (typeof importance === 'string') {
      level = importance.toLowerCase();
    } else {
      level = 'low';
    }
  }

  const badgeClass = `importance-${level}`;
  const label = `Importance: ${level.charAt(0).toUpperCase() + level.slice(1)}`;
  return { level, label, badgeClass };
}

/**
 * Assigns a change record to a temporal bucket based on canonical detected_at timestamp.
 */
export function getTemporalGroup(detectedAtStr) {
  if (!detectedAtStr) return 'Earlier';
  try {
    const detected = new Date(detectedAtStr);
    const now = new Date();
    const diffHours = (now - detected) / (1000 * 60 * 60);

    if (diffHours <= 24) return 'Today';
    if (diffHours <= 48) return 'Yesterday';
    if (diffHours <= 168) return 'Past 7 Days';
    return 'Earlier';
  } catch {
    return 'Earlier';
  }
}

/**
 * Renders an individual Change Card.
 */
export function renderChangeCard(change) {
  const changeId = change.id || '';
  const entityType = change.entity_type || 'claim';
  const entityId = change.entity_id || '';
  const clusterId = change.cluster_id || (entityType === 'cluster' ? entityId : null);
  const changeType = change.change_type || 'state_changed';
  const reason = change.reason || 'Tracked longitudinal intelligence change.';
  const rawOld = change.old_value ?? null;
  const rawNew = change.new_value ?? null;
  const detectedAt = change.detected_at || change.created_at;
  const formattedDate = formatDate(detectedAt);

  const originKey = (change.origin || 'live_update').toLowerCase();
  const originInfo = ORIGIN_METADATA[originKey] || {
    label: toTitleCase(originKey),
    badgeClass: 'badge-origin-system',
    isSystem: false,
    description: 'Change record provenance.',
  };

  const imp = formatImportance(change.importance, change.importance_level);
  const isSystemRecord = originInfo.isSystem;

  const category = getChangeSemanticCategory(changeType, entityType);
  const oldHtml = formatTransitionValue(rawOld, category, true);
  const newHtml = formatTransitionValue(rawNew, category, false);

  const changeTitle = toTitleCase(changeType.replace(/_/g, ' '));
  const entityLabel = `${toTitleCase(entityType.replace(/_/g, ' '))}: ${entityId}`;

  return `
    <article class="change-card ${isSystemRecord ? 'change-card-system' : ''}" id="change-card-${escapeHtml(changeId)}" data-change-id="${escapeHtml(changeId)}" data-entity-type="${escapeHtml(entityType)}" data-origin="${escapeHtml(originKey)}">
      <div class="change-card-header">
        <div>
          <h3 class="change-type-title">
            ${escapeHtml(changeTitle)}
            <span class="importance-pill ${imp.badgeClass}" title="Priority level">${escapeHtml(imp.label)}</span>
          </h3>
          <div class="change-meta-row">
            <span class="mono text-xs text-muted">${escapeHtml(entityLabel)}</span>
            <span>&bull;</span>
            <span class="text-xs text-faint" title="Canonical detection time">Detected: ${formattedDate}</span>
          </div>
        </div>

        <div>
          <span class="change-origin-badge ${originInfo.badgeClass}" title="${escapeHtml(originInfo.description)}">
            ${getIcon(isSystemRecord ? 'activity' : 'zap')}
            ${escapeHtml(originInfo.label)}
          </span>
        </div>
      </div>

      <div class="change-transition-box">
        <div class="transition-state">
          <span class="text-xs text-faint text-semibold" style="text-transform:uppercase;margin-right:4px;">Then:</span>
          ${oldHtml}
        </div>
        <span class="transition-arrow">&rarr;</span>
        <div class="transition-state">
          <span class="text-xs text-faint text-semibold" style="text-transform:uppercase;margin-right:4px;">Now:</span>
          ${newHtml}
        </div>
      </div>

      <div class="change-reason-block">
        <div class="text-xs text-semibold text-muted" style="text-transform:uppercase;margin-bottom:2px;">Intelligence Rationale</div>
        <div>${escapeHtml(reason)}</div>
      </div>

      <div class="change-card-footer">
        <div class="mono text-xs text-faint">
          Record ID: ${escapeHtml(changeId)}
        </div>

        <div>
          ${clusterId ? `
            <a href="#/story/${encodeURIComponent(clusterId)}" class="btn btn-secondary btn-sm" aria-label="Open Story Dossier for cluster ${escapeHtml(clusterId)}">
              Open Story Dossier &rarr;
            </a>
          ` : `
            <span class="mono text-xs text-muted">Entity: ${escapeHtml(entityId)}</span>
          `}
        </div>
      </div>
    </article>
  `;
}

/**
 * Main Changes View Renderer
 */
export async function renderChangesView(container, store) {
  let activeRequestId = 0;

  // Filter state
  let currentHours = 168; // default 7 days
  let currentImportance = ''; // all
  let currentProject = '';
  let hideSystemMaintenance = false; // noise control toggle
  let selectedEntityType = 'all';

  container.innerHTML = renderLoadingState('Loading longitudinal changes…');

  // Load available projects for context filtering
  let availableProjects = [];
  try {
    const projRes = await api.getProjects();
    availableProjects = ensureArray(projRes.projects || projRes);
  } catch {
    availableProjects = [];
  }

  async function loadAndRender() {
    const requestId = ++activeRequestId;
    const contentRegion = container.querySelector('#changes-content-region');
    const liveRegion = container.querySelector('#changes-live-region');

    if (contentRegion) {
      contentRegion.innerHTML = renderLoadingState('Fetching state revisions…');
    }

    try {
      const queryParams = {
        hours: currentHours,
        limit: 100,
      };
      if (currentImportance) {
        queryParams.importance_min = currentImportance;
      }
      if (currentProject) {
        queryParams.project = currentProject;
      }

      const response = await api.getChanges(queryParams);

      // Stale request protection
      if (requestId !== activeRequestId) return;

      const rawChanges = ensureArray(response.changes || response);
      store.setViewData('changes', rawChanges);
      store.setConnection('healthy');

      // Apply client-side presentation filters (noise control & entity filter)
      let displayedChanges = rawChanges;
      if (hideSystemMaintenance) {
        displayedChanges = displayedChanges.filter(c => {
          const originKey = (c.origin || 'live_update').toLowerCase();
          const info = ORIGIN_METADATA[originKey];
          return !info || !info.isSystem;
        });
      }

      if (selectedEntityType !== 'all') {
        displayedChanges = displayedChanges.filter(c => (c.entity_type || '').toLowerCase() === selectedEntityType);
      }

      // Group changes temporally
      const groups = {
        'Today': [],
        'Yesterday': [],
        'Past 7 Days': [],
        'Earlier': [],
      };

      displayedChanges.forEach(ch => {
        const grp = getTemporalGroup(ch.detected_at || ch.created_at);
        if (groups[grp]) groups[grp].push(ch);
        else groups['Earlier'].push(ch);
      });

      if (liveRegion) {
        liveRegion.textContent = `Showing ${displayedChanges.length} longitudinal change${displayedChanges.length === 1 ? '' : 's'}.`;
      }

      const totalCountEl = container.querySelector('#changes-total-count');
      if (totalCountEl) {
        totalCountEl.textContent = displayedChanges.length;
      }

      if (!displayedChanges.length) {
        contentRegion.innerHTML = renderEmptyState(
          'No Changes Found',
          'No intelligence changes matched the selected time window, importance threshold, or filters.'
        );
        return;
      }

      let listHtml = `<div class="changes-timeline-region">`;
      const groupNames = ['Today', 'Yesterday', 'Past 7 Days', 'Earlier'];

      groupNames.forEach(grpName => {
        const items = groups[grpName];
        if (items && items.length > 0) {
          listHtml += `
            <section class="changes-group" aria-labelledby="heading-group-${escapeHtml(grpName.replace(/\s+/g, '-'))}">
              <h2 class="changes-group-heading" id="heading-group-${escapeHtml(grpName.replace(/\s+/g, '-'))}">
                ${escapeHtml(grpName)}
                <span class="changes-group-count">${items.length}</span>
              </h2>
              <div class="grid-1" style="gap:var(--space-4);">
                ${items.map(renderChangeCard).join('')}
              </div>
            </section>
          `;
        }
      });
      listHtml += `</div>`;

      contentRegion.innerHTML = listHtml;
    } catch (err) {
      if (requestId !== activeRequestId) return;

      if (err.isNetworkError) {
        store.setConnection('offline', err.message);
        if (contentRegion) contentRegion.innerHTML = renderOfflineState(undefined, err.message);
      } else {
        store.setConnection('degraded', err.message);
        if (contentRegion) contentRegion.innerHTML = renderErrorState('Failed to Load Longitudinal Changes', err.message);
      }
    }
  }

  function renderViewShell() {
    container.innerHTML = `
      <div class="page-header-container">
        <div>
          <span class="eyebrow">Longitudinal Intelligence</span>
          <h1>What Moved</h1>
          <p class="lead">Track verification revisions, contradiction discoveries, maturity shifts, and risk changes over time.</p>
        </div>
        <div class="page-header-meta">
          <strong id="changes-total-count">—</strong>
          <span>recorded changes</span>
        </div>
      </div>

      <!-- Changes Filter & Noise Control Toolbar -->
      <section class="changes-toolbar" aria-label="Changes filter controls">
        <div class="changes-filters-row">
          <div class="form-group" style="margin-bottom:0;">
            <label for="changes-hours-select" class="form-label" style="font-size:var(--text-xs);">Time Window</label>
            <select id="changes-hours-select" class="form-control" style="font-size:var(--text-sm);padding:4px 8px;">
              <option value="24" ${currentHours === 24 ? 'selected' : ''}>Past 24 Hours</option>
              <option value="72" ${currentHours === 72 ? 'selected' : ''}>Past 3 Days</option>
              <option value="168" ${currentHours === 168 ? 'selected' : ''}>Past 7 Days</option>
              <option value="720" ${currentHours === 720 ? 'selected' : ''}>Past 30 Days</option>
            </select>
          </div>

          <div class="form-group" style="margin-bottom:0;">
            <label for="changes-importance-select" class="form-label" style="font-size:var(--text-xs);">Min Importance</label>
            <select id="changes-importance-select" class="form-control" style="font-size:var(--text-sm);padding:4px 8px;">
              <option value="" ${currentImportance === '' ? 'selected' : ''}>All Levels</option>
              <option value="low" ${currentImportance === 'low' ? 'selected' : ''}>Low & Above</option>
              <option value="medium" ${currentImportance === 'medium' ? 'selected' : ''}>Medium & Above</option>
              <option value="high" ${currentImportance === 'high' ? 'selected' : ''}>High & Above</option>
              <option value="critical" ${currentImportance === 'critical' ? 'selected' : ''}>Critical Only</option>
            </select>
          </div>

          ${availableProjects.length > 0 ? `
            <div class="form-group" style="margin-bottom:0;">
              <label for="changes-project-select" class="form-label" style="font-size:var(--text-xs);">Project Relevance</label>
              <select id="changes-project-select" class="form-control" style="font-size:var(--text-sm);padding:4px 8px;">
                <option value="" ${currentProject === '' ? 'selected' : ''}>All Projects</option>
                ${availableProjects.map(p => `
                  <option value="${escapeHtml(p.id)}" ${currentProject === p.id ? 'selected' : ''}>${escapeHtml(p.name)}</option>
                `).join('')}
              </select>
            </div>
          ` : ''}

          <div class="form-group" style="margin-bottom:0;">
            <label for="changes-entity-select" class="form-label" style="font-size:var(--text-xs);">Entity Type</label>
            <select id="changes-entity-select" class="form-control" style="font-size:var(--text-sm);padding:4px 8px;">
              <option value="all" ${selectedEntityType === 'all' ? 'selected' : ''}>All Entities</option>
              <option value="claim" ${selectedEntityType === 'claim' ? 'selected' : ''}>Claims</option>
              <option value="cluster" ${selectedEntityType === 'cluster' ? 'selected' : ''}>Stories / Clusters</option>
              <option value="technology_assessment" ${selectedEntityType === 'technology_assessment' ? 'selected' : ''}>Maturity Assessments</option>
              <option value="technology_state" ${selectedEntityType === 'technology_state' ? 'selected' : ''}>Risk / Tech States</option>
            </select>
          </div>

          <div style="margin-top:auto;">
            <button type="button" class="btn btn-secondary btn-sm" id="btn-reset-changes-filters" aria-label="Reset all filters">
              Reset Filters
            </button>
          </div>
        </div>

        <div class="changes-provenance-row">
          <label class="toggle-control-label" for="chk-hide-system">
            <input type="checkbox" id="chk-hide-system" ${hideSystemMaintenance ? 'checked' : ''} />
            <span>Hide system maintenance records (migration, backfill, recompute)</span>
          </label>
        </div>
      </section>

      <!-- Accessible Live Region -->
      <div id="changes-live-region" class="sr-only" role="status" aria-live="polite"></div>

      <!-- Main Changes List Region -->
      <div id="changes-content-region" class="search-results-region"></div>
    `;

    // Attach Event Listeners
    const hoursSelect = container.querySelector('#changes-hours-select');
    hoursSelect?.addEventListener('change', async (e) => {
      currentHours = parseInt(e.target.value, 10) || 168;
      await loadAndRender();
    });

    const impSelect = container.querySelector('#changes-importance-select');
    impSelect?.addEventListener('change', async (e) => {
      currentImportance = e.target.value;
      await loadAndRender();
    });

    const projSelect = container.querySelector('#changes-project-select');
    projSelect?.addEventListener('change', async (e) => {
      currentProject = e.target.value;
      await loadAndRender();
    });

    const entitySelect = container.querySelector('#changes-entity-select');
    entitySelect?.addEventListener('change', async (e) => {
      selectedEntityType = e.target.value;
      await loadAndRender();
    });

    const hideSysChk = container.querySelector('#chk-hide-system');
    hideSysChk?.addEventListener('change', async (e) => {
      hideSystemMaintenance = e.target.checked;
      await loadAndRender();
    });

    const resetBtn = container.querySelector('#btn-reset-changes-filters');
    resetBtn?.addEventListener('click', async () => {
      currentHours = 168;
      currentImportance = '';
      currentProject = '';
      hideSystemMaintenance = false;
      selectedEntityType = 'all';

      const hSel = container.querySelector('#changes-hours-select');
      if (hSel) hSel.value = '168';
      const impSel = container.querySelector('#changes-importance-select');
      if (impSel) impSel.value = '';
      const projSel = container.querySelector('#changes-project-select');
      if (projSel) projSel.value = '';
      const entSel = container.querySelector('#changes-entity-select');
      if (entSel) entSel.value = 'all';
      const chk = container.querySelector('#chk-hide-system');
      if (chk) chk.checked = false;

      await loadAndRender();
    });
  }

  renderViewShell();
  await loadAndRender();
}

