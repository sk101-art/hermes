/**
 * HERMES Saved Intelligence Library View
 * Snapshot-vs-Current Intelligence Experience.
 * Preserves historical intelligence snapshots while comparing with live HERMES intelligence states.
 */

import { api } from '../api/endpoints.js';
import { getIcon } from '../icons/index.js';
import {
  renderVerificationBadge,
  renderMaturityBadge,
  renderRiskBadge,
} from '../components/badges.js';
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
} from '../utils/adapters.js';

export const CANONICAL_MATURITY_LABELS = {
  concept: 'Concept',
  research: 'Research',
  prototype: 'Prototype',
  experimental: 'Experimental',
  early_adoption: 'Early Adoption',
  production_candidate: 'Production Candidate',
  established: 'Established',
};

/**
 * Format human-readable maturity label.
 */
export function getMaturityLabel(stage) {
  if (!stage) return 'Not assessed';
  const canonical = CANONICAL_MATURITY_LABELS[String(stage).toLowerCase()];
  if (canonical) return canonical;
  return String(stage).charAt(0).toUpperCase() + String(stage).slice(1).replace(/_/g, ' ');
}

/**
 * Format human-readable claim status label.
 */
function getClaimStatusLabel(status) {
  if (!status) return 'Not recorded';
  return status.charAt(0).toUpperCase() + status.slice(1).replace(/_/g, ' ');
}

/**
 * Format human-readable risk level label.
 */
function getRiskLevelLabel(level, status) {
  if (status === 'not_assessed') return 'Not assessed';
  if (status === 'insufficient_data') return 'Insufficient data';
  if (!level) return 'Not recorded';
  return level.charAt(0).toUpperCase() + level.slice(1) + ' risk';
}

/**
 * Computes the evolution diff items between THEN snapshot and NOW live state.
 * Only returns diff pills when both historical and current states are genuinely known.
 */
export function computeEvolutionDiff(item) {
  const current = item.current_state || null;
  if (!current) {
    return {
      status: 'unavailable',
      diffs: ['Current intelligence unavailable (cluster inactive)'],
    };
  }

  const diffs = [];

  // 1. Maturity evolution (only when both are known and different)
  if (item.maturity_stage && current.maturity_stage && item.maturity_stage !== current.maturity_stage) {
    diffs.push({
      type: 'evolution',
      label: `Maturity: ${getMaturityLabel(item.maturity_stage)} → ${getMaturityLabel(current.maturity_stage)}`,
    });
  }

  // 2. Claim status evolution (only when both are non-null and different)
  if (item.claim_status && current.claim_status && item.claim_status !== current.claim_status) {
    diffs.push({
      type: 'evolution',
      label: `Claims: ${getClaimStatusLabel(item.claim_status)} → ${getClaimStatusLabel(current.claim_status)}`,
    });
  }

  // 3. Risk evolution (only when both levels are known and different)
  if (item.risk_level && current.risk_level && item.risk_level !== current.risk_level) {
    diffs.push({
      type: 'evolution',
      label: `Risk: ${getRiskLevelLabel(item.risk_level, item.risk_status)} → ${getRiskLevelLabel(current.risk_level, current.risk_status)}`,
    });
  }

  // 4. Significant verification score shift (>= 5%)
  if (
    typeof item.verification_score === 'number' &&
    typeof current.verification_score === 'number'
  ) {
    const diffScore = current.verification_score - item.verification_score;
    if (Math.abs(diffScore) >= 0.05) {
      const sign = diffScore > 0 ? '+' : '';
      const pct = Math.round(diffScore * 100);
      diffs.push({
        type: 'score',
        label: `Verification shift: ${sign}${pct}%`,
      });
    }
  }

  return {
    status: diffs.length > 0 ? 'changed' : 'unchanged',
    diffs,
  };
}

/**
 * Render an individual Saved Card.
 */
export function renderSavedCard(item) {
  const savedId = item.id || '';
  const clusterId = item.story_cluster_id || item.entity_id || '';
  const title = item.title_snapshot || item.title || 'Untitled Item';
  const savedDate = formatDate(item.saved_at || item.created_at);
  const current = item.current_state || null;
  const tags = ensureArray(item.tags);

  const evolution = computeEvolutionDiff(item);

  // THEN (Saved Snapshot) badging
  let thenVerifHtml = '';
  if (item.claim_status) {
    thenVerifHtml = renderVerificationBadge(item.claim_status, item.verification_score);
  } else if (typeof item.verification_score === 'number') {
    thenVerifHtml = `
      <div class="saved-badge-row">
        <span class="semantic-badge badge-verification-unassessed">Saved verification: ${Math.round(item.verification_score * 100)}%</span>
        <span class="text-xs text-faint">Claim status: Not recorded historically</span>
      </div>
    `;
  } else {
    thenVerifHtml = `<span class="text-xs text-faint">Claim status: Not recorded historically</span>`;
  }

  let thenMaturityHtml = '';
  if (item.maturity_stage) {
    thenMaturityHtml = renderMaturityBadge(item.maturity_stage);
  } else {
    thenMaturityHtml = `<span class="text-xs text-faint">Maturity: Not recorded historically</span>`;
  }

  let thenRiskHtml = '';
  if (item.risk_status) {
    thenRiskHtml = renderRiskBadge(item.risk_status, item.risk_level, item.risk_score);
  } else if (typeof item.risk_score === 'number') {
    thenRiskHtml = `
      <div class="saved-badge-row">
        <span class="semantic-badge badge-risk-not_assessed">Saved risk: ${Math.round(item.risk_score * 100)}%</span>
        <span class="text-xs text-faint">Risk status: Not recorded historically</span>
      </div>
    `;
  } else {
    thenRiskHtml = `<span class="text-xs text-faint">Risk status: Not recorded historically</span>`;
  }

  // NOW (Current Intelligence) badging
  let nowVerifHtml = '';
  let nowMaturityHtml = '';
  let nowRiskHtml = '';
  let nowMetricsHtml = '';

  if (current) {
    nowVerifHtml = renderVerificationBadge(current.claim_status, current.verification_score);
    nowMaturityHtml = renderMaturityBadge(current.maturity_stage);
    nowRiskHtml = renderRiskBadge(current.risk_status, current.risk_level, current.risk_score);
    nowMetricsHtml = `
      <div class="mono text-xs text-muted" style="margin-top:var(--space-1);">
        ${current.claims_count || 0} claims · ${current.events_count || 0} events
      </div>
    `;
  }

  return `
    <article class="saved-card" id="saved-card-${escapeHtml(savedId)}" data-saved-id="${escapeHtml(savedId)}" data-cluster-id="${escapeHtml(clusterId)}" data-evolution="${evolution.status}">
      <div class="saved-card-header">
        <div>
          <h2 class="saved-card-title">
            <a href="#/story/${encodeURIComponent(clusterId)}" class="saved-title-link" aria-label="Open Story Dossier for ${escapeHtml(title)}">
              ${escapeHtml(title)}
            </a>
          </h2>
          <div class="mono text-xs text-muted">
            ID: ${escapeHtml(clusterId)} · Saved on ${savedDate}
          </div>
        </div>

        <div class="saved-card-actions">
          <a href="#/story/${encodeURIComponent(clusterId)}" class="btn btn-secondary btn-sm" aria-label="Open Story Dossier for ${escapeHtml(title)}">
            Open Story Dossier &rarr;
          </a>
          <button type="button" class="btn btn-secondary btn-sm btn-unsave" data-action="unsave" data-saved-id="${escapeHtml(savedId)}" data-title="${escapeHtml(title)}" aria-label="Remove ${escapeHtml(title)} from saved library">
            ${getIcon('trash')} Remove
          </button>
        </div>
      </div>

      <!-- Snapshot-vs-Current Comparison Grid -->
      <div class="saved-comparison-grid">
        <!-- THEN: Historical Snapshot -->
        <div class="temporal-box temporal-box-then" aria-label="Historical saved snapshot">
          <div class="temporal-box-header">
            <span class="temporal-label-then">THEN (Saved Snapshot)</span>
            <span class="text-xs text-faint">${savedDate}</span>
          </div>
          <div class="temporal-badges">
            ${thenVerifHtml}
            ${thenMaturityHtml}
            ${thenRiskHtml}
          </div>
        </div>

        <!-- NOW: Live Intelligence State -->
        <div class="temporal-box temporal-box-now" aria-label="Current live intelligence">
          <div class="temporal-box-header">
            <span class="temporal-label-now">NOW (Current Intelligence)</span>
            <span class="text-xs text-muted">Live Corpus</span>
          </div>
          ${current ? `
            <div class="temporal-badges">
              ${nowVerifHtml}
              ${nowMaturityHtml}
              ${nowRiskHtml}
              ${nowMetricsHtml}
            </div>
          ` : `
            <div class="temporal-unavailable" style="padding:var(--space-2) 0;">
              <span class="semantic-badge badge-verification-unassessed">Current intelligence unavailable</span>
              <p class="text-xs text-muted" style="margin:4px 0 0;">Underlying story cluster is no longer active in live index.</p>
            </div>
          `}
        </div>
      </div>

      <!-- Evolution & Change Diff Panel -->
      <div class="saved-diff-panel" aria-label="Evolution status since save">
        <div class="saved-diff-header">
          <span class="text-xs text-semibold text-primary">Intelligence Evolution:</span>
          <span class="text-xs text-muted">Comparison against historical baseline</span>
        </div>
        <div class="diff-chips-row">
          ${evolution.status === 'changed' ? `
            ${evolution.diffs.map(d => `
              <span class="diff-chip ${d.type === 'score' ? 'diff-chip-score' : 'diff-chip-evolution'}">
                ${getIcon('arrowRight')} ${escapeHtml(d.label)}
              </span>
            `).join('')}
          ` : evolution.status === 'unchanged' ? `
            <span class="diff-chip diff-chip-stable">
              ${getIcon('checkCircle')} Intelligence state unchanged since save
            </span>
          ` : `
            <span class="diff-chip diff-chip-unavailable">
              ${getIcon('alertCircle')} Current intelligence unavailable
            </span>
          `}
        </div>
      </div>

      ${item.user_note ? `
        <div class="saved-note-block">
          <strong>Note:</strong> ${escapeHtml(item.user_note)}
        </div>
      ` : ''}

      ${tags.length ? `
        <div class="saved-footer">
          <div class="chip-group" style="margin-top:0;">
            ${tags.map(t => `<span class="chip">${escapeHtml(t)}</span>`).join('')}
          </div>
        </div>
      ` : ''}
    </article>
  `;
}

/**
 * Main Saved Library View Controller
 */
export async function renderSavedView(container, store) {
  container.innerHTML = renderLoadingState('Loading saved intelligence library…');

  try {
    const response = await api.getSavedItems({ limit: 50, include_current: true });
    const items = ensureArray(response.saved_items || response.items || response);
    store.setViewData('saved', items);
    store.setConnection('healthy');

    // Extract unique tags
    const allTags = new Set();
    items.forEach(item => {
      ensureArray(item.tags).forEach(t => allTags.add(t));
    });
    const sortedTags = Array.from(allTags).sort();

    let activeTagFilter = 'all';
    let activeStatusFilter = 'all';

    function renderViewContent() {
      // Filter items
      const filtered = items.filter(item => {
        if (activeTagFilter !== 'all') {
          const itemTags = ensureArray(item.tags).map(t => t.toLowerCase());
          if (!itemTags.includes(activeTagFilter.toLowerCase())) return false;
        }
        if (activeStatusFilter !== 'all') {
          const ev = computeEvolutionDiff(item);
          if (ev.status !== activeStatusFilter) return false;
        }
        return true;
      });

      let html = `
        <div class="page-header-container">
          <div>
            <span class="eyebrow">Personal Intelligence Library</span>
            <h1>Saved Intelligence</h1>
            <p class="lead">Historical snapshots preserve baseline review states alongside live HERMES intelligence evolutions.</p>
          </div>
          <div class="page-header-meta">
            <strong id="saved-total-count">${filtered.length}</strong>
            <span>item${filtered.length === 1 ? '' : 's'} displayed</span>
          </div>
        </div>

        <div id="saved-live-region" class="sr-only" aria-live="polite"></div>

        <!-- Filter & Search Toolbar -->
        <div class="saved-toolbar" role="search" aria-label="Filter saved items">
          <div class="saved-filter-group">
            <label for="saved-tag-filter" class="text-xs text-muted">Tag:</label>
            <select id="saved-tag-filter" class="form-select form-select-sm" aria-label="Filter by tag">
              <option value="all" ${activeTagFilter === 'all' ? 'selected' : ''}>All Tags (${items.length})</option>
              ${sortedTags.map(tag => `
                <option value="${escapeHtml(tag)}" ${activeTagFilter === tag ? 'selected' : ''}>${escapeHtml(tag)}</option>
              `).join('')}
            </select>
          </div>

          <div class="saved-filter-group">
            <label for="saved-status-filter" class="text-xs text-muted">Evolution:</label>
            <select id="saved-status-filter" class="form-select form-select-sm" aria-label="Filter by evolution status">
              <option value="all" ${activeStatusFilter === 'all' ? 'selected' : ''}>All Evolutions</option>
              <option value="changed" ${activeStatusFilter === 'changed' ? 'selected' : ''}>Changed Since Save</option>
              <option value="unchanged" ${activeStatusFilter === 'unchanged' ? 'selected' : ''}>Unchanged</option>
              <option value="unavailable" ${activeStatusFilter === 'unavailable' ? 'selected' : ''}>Unavailable Live</option>
            </select>
          </div>
        </div>
      `;

      if (!filtered.length) {
        if (!items.length) {
          html += renderEmptyState(
            'No Saved Items',
            'Your saved intelligence library is empty. Save story clusters and findings from the Today feed, Search, or Story Dossiers to preserve snapshots and track changes.'
          );
        } else {
          html += renderEmptyState(
            'No Matching Items',
            'No saved items match your active filter criteria.',
            `<button type="button" class="btn btn-secondary btn-sm" id="btn-reset-saved-filters">Reset Filters</button>`
          );
        }
      } else {
        html += `
          <div class="saved-items-list" id="saved-items-container">
            ${filtered.map(renderSavedCard).join('')}
          </div>
        `;
      }

      container.innerHTML = html;
      attachSavedListeners();
    }

    function attachSavedListeners() {
      const tagSelect = container.querySelector('#saved-tag-filter');
      tagSelect?.addEventListener('change', (e) => {
        activeTagFilter = e.target.value;
        renderViewContent();
      });

      const statusSelect = container.querySelector('#saved-status-filter');
      statusSelect?.addEventListener('change', (e) => {
        activeStatusFilter = e.target.value;
        renderViewContent();
      });

      const resetBtn = container.querySelector('#btn-reset-saved-filters');
      resetBtn?.addEventListener('click', () => {
        activeTagFilter = 'all';
        activeStatusFilter = 'all';
        renderViewContent();
      });

      // Delegated listener for Unsave actions
      const itemsContainer = container.querySelector('#saved-items-container');
      itemsContainer?.addEventListener('click', async (e) => {
        const unsaveBtn = e.target.closest('[data-action="unsave"]');
        if (!unsaveBtn) return;

        const savedId = unsaveBtn.getAttribute('data-saved-id');
        const itemTitle = unsaveBtn.getAttribute('data-title') || 'Item';
        const card = container.querySelector(`[data-saved-id="${savedId}"]`);

        if (!savedId) return;

        try {
          unsaveBtn.disabled = true;
          unsaveBtn.innerHTML = `${getIcon('spinner')} Removing…`;

          await api.unsaveItem(savedId);

          // Optimistically remove card from local view array
          const idx = items.findIndex(it => it.id === savedId);
          if (idx !== -1) {
            items.splice(idx, 1);
            store.setViewData('saved', items);
          }

          if (card) {
            card.style.opacity = '0.3';
            card.style.pointerEvents = 'none';
            setTimeout(() => {
              card.remove();
              const countEl = container.querySelector('#saved-total-count');
              if (countEl) {
                const cur = parseInt(countEl.textContent || '0', 10);
                countEl.textContent = Math.max(0, cur - 1);
              }
              const liveRegion = container.querySelector('#saved-live-region');
              if (liveRegion) {
                liveRegion.textContent = `Removed "${itemTitle}" from saved library.`;
              }
              if (!items.length) {
                renderViewContent();
              }
            }, 200);
          }
        } catch (err) {
          unsaveBtn.disabled = false;
          unsaveBtn.innerHTML = `${getIcon('trash')} Remove`;
          const liveRegion = container.querySelector('#saved-live-region');
          if (liveRegion) {
            liveRegion.textContent = `Failed to remove item: ${err.message || 'Unknown error'}`;
          }
          if (typeof window !== 'undefined' && typeof window.alert === 'function') {
            window.alert(`Failed to remove item: ${err.message || 'Unknown error'}`);
          }
        }
      });
    }

    renderViewContent();
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

