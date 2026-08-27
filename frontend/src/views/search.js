/**
 * HERMES Search & Query View
 * Corpus query interface with explicit ranking decomposition and truthfulness preservation.
 * 
 * Epistemic rules:
 * - Search rank score is labeled strictly as Relevance Score / Search Rank, NEVER Verification / Confidence.
 * - Grounded synthesis is cleanly distinguished from raw fallback source excerpts.
 * - Score decomposition explains search ordering only, never truth validity.
 */

import { api } from '../api/endpoints.js';
import { requestManager } from '../state/request-manager.js';
import { getIcon } from '../icons/index.js';
import {
  renderVerificationBadge,
  renderMaturityBadge,
  renderRiskBadge,
  renderSourcePill,
  renderSearchScoreBadge,
  renderProjectRelevanceBadge,
} from '../components/badges.js';
import { renderLoadingState, renderEmptyState, renderErrorState, renderOfflineState } from '../components/ui-states.js';
import { escapeHtml, ensureArray, formatDate } from '../utils/adapters.js';
import { renderSurfaceControls } from '../components/surface-controls.js';


// Cached dynamic sources and projects
let cachedSourcesList = null;
let cachedProjectsList = null;

export async function renderSearchView(container, store, routeParams = {}) {

  const query = routeParams.q !== undefined ? routeParams.q : (store.getState().searchQuery || '');
  const searchMode = routeParams.mode || 'hybrid';
  const selectedSource = routeParams.source || 'all';
  const minMaturity = routeParams.min_maturity || 'all';
  const maxRisk = routeParams.max_risk || 'all';
  const selectedProject = routeParams.project || 'all';
  const days = routeParams.days || 'all';
  const verifiedOnly = routeParams.verified_only === 'true' || routeParams.verified === 'true';
  const showExplain = routeParams.explain === 'true' || routeParams.explain === undefined; // default true for intelligence search

  const isSearched = Boolean(query && query.trim().length > 0);

  let initialHtml = `
    <div class="page-header-container">
      <div>
        <span class="eyebrow">Corpus Discovery</span>
        <h1>Search with Epistemic Context</h1>
        <p class="lead">Search score reflects query relevance and context ranking, not truth validity. Verification, maturity, and risk remain explicit.</p>
      </div>
      <div class="page-header-meta" style="display:flex; flex-direction:column; align-items:flex-end; gap:var(--space-2);">
        <div id="search-refresh-container"></div>
      </div>
    </div>

    <!-- Search Input Bar -->
    <div class="search-bar-container">
      <div class="search-input-wrapper">
        <input type="search" 
               id="search-input-field" 
               class="search-input-field" 
               value="${escapeHtml(query)}" 
               placeholder="Search technologies, claims, benchmarks, or papers (e.g. 'vLLM', 'CUDA 13', 'C++', 'AES-256')…" 
               aria-label="Search intelligence corpus"
               autocomplete="off"
               spellcheck="false"/>
      </div>
      <button class="btn btn-primary" id="btn-search-exec" aria-label="Execute search query">
        ${getIcon('search')} Search
      </button>
      <button class="btn btn-secondary" id="btn-search-reset" title="Reset all filters and query" aria-label="Reset search filters">
        Reset
      </button>
    </div>

    <!-- Filter Control Toolbar -->
    <div class="search-filters-card" role="region" aria-label="Search Filter Controls">
      <div class="search-filters-grid">
        <!-- 1. Search Mode -->
        <div class="filter-field">
          <label for="search-mode-select" class="filter-label">Search Mode</label>
          <select id="search-mode-select" class="select-control" aria-label="Search retrieval mode">
            <option value="hybrid" ${searchMode === 'hybrid' ? 'selected' : ''}>Hybrid (Semantic + Lexical)</option>
            <option value="semantic" ${searchMode === 'semantic' ? 'selected' : ''}>Semantic Vector</option>
            <option value="lexical" ${searchMode === 'lexical' ? 'selected' : ''}>Lexical FTS</option>
          </select>
        </div>

        <!-- 2. Source Filter -->
        <div class="filter-field">
          <label for="search-source-select" class="filter-label">Source Filter</label>
          <select id="search-source-select" class="select-control" aria-label="Filter by source">
            <option value="all" ${selectedSource === 'all' ? 'selected' : ''}>All Ingested Sources</option>
            ${renderSourceOptions(selectedSource)}
          </select>
        </div>

        <!-- 3. Canonical Minimum Maturity -->
        <div class="filter-field">
          <label for="search-min-maturity-select" class="filter-label">Min Maturity</label>
          <select id="search-min-maturity-select" class="select-control" aria-label="Minimum technology maturity stage">
            <option value="all" ${minMaturity === 'all' ? 'selected' : ''}>Any Maturity Stage</option>
            <option value="concept" ${minMaturity === 'concept' ? 'selected' : ''}>Concept (&ge; Stage 1)</option>
            <option value="research" ${minMaturity === 'research' ? 'selected' : ''}>Research (&ge; Stage 2)</option>
            <option value="prototype" ${minMaturity === 'prototype' ? 'selected' : ''}>Prototype (&ge; Stage 3)</option>
            <option value="experimental" ${minMaturity === 'experimental' ? 'selected' : ''}>Experimental (&ge; Stage 4)</option>
            <option value="early_adoption" ${minMaturity === 'early_adoption' ? 'selected' : ''}>Early Adoption (&ge; Stage 5)</option>
            <option value="production_candidate" ${minMaturity === 'production_candidate' ? 'selected' : ''}>Production Candidate (&ge; Stage 6)</option>
            <option value="established" ${minMaturity === 'established' ? 'selected' : ''}>Established (Stage 7)</option>
          </select>
        </div>

        <!-- 4. Max Assessed Risk -->
        <div class="filter-field">
          <label for="search-max-risk-select" class="filter-label" title="Applies to evaluated risk states. Unassessed provenance states remain preserved.">Max Assessed Risk</label>
          <select id="search-max-risk-select" class="select-control" aria-label="Maximum evaluated risk level">
            <option value="all" ${maxRisk === 'all' ? 'selected' : ''}>Any Risk Level</option>
            <option value="low" ${maxRisk === 'low' ? 'selected' : ''}>Low Risk Only (&le; Low)</option>
            <option value="medium" ${maxRisk === 'medium' ? 'selected' : ''}>Medium or Lower (&le; Medium)</option>
            <option value="high" ${maxRisk === 'high' ? 'selected' : ''}>High or Lower (&le; High)</option>
            <option value="critical" ${maxRisk === 'critical' ? 'selected' : ''}>Allow Critical</option>
          </select>
        </div>

        <!-- 5. Project Context Boost -->
        <div class="filter-field">
          <label for="search-project-select" class="filter-label" title="Boosts relevance ranking for active internal engineering project context">Project Context</label>
          <select id="search-project-select" class="select-control" aria-label="Project context relevance boost">
            <option value="all" ${selectedProject === 'all' ? 'selected' : ''}>General Corpus (No Boost)</option>
            ${renderProjectOptions(selectedProject)}
          </select>
        </div>

        <!-- 6. Publication Timeframe -->
        <div class="filter-field">
          <label for="search-days-select" class="filter-label">Timeframe</label>
          <select id="search-days-select" class="select-control" aria-label="Publication date window">
            <option value="all" ${days === 'all' ? 'selected' : ''}>All Historical Records</option>
            <option value="7" ${days === '7' ? 'selected' : ''}>Last 7 days</option>
            <option value="30" ${days === '30' ? 'selected' : ''}>Last 30 days</option>
            <option value="90" ${days === '90' ? 'selected' : ''}>Last 90 days</option>
            <option value="365" ${days === '365' ? 'selected' : ''}>Last 365 days</option>
          </select>
        </div>
      </div>

      <!-- Toggles row -->
      <div class="search-toggles-row">
        <label class="toggle-control-label">
          <input type="checkbox" id="search-verified-only-checkbox" ${verifiedOnly ? 'checked' : ''} />
          <span><strong>Verified Only</strong> (&ge;60% verification score with supported claim)</span>
        </label>

        <label class="toggle-control-label">
          <input type="checkbox" id="search-explain-checkbox" ${showExplain ? 'checked' : ''} />
          <span><strong>Show Ranking Breakdown</strong> (Explain relevance score composition)</span>
        </label>
      </div>
    </div>

    <!-- Live Announcement Region -->
    <div id="search-live-announcer" class="sr-only" role="status" aria-live="polite"></div>

    <!-- Results Area -->
    <div id="search-results-area" class="search-results-region">
      ${!isSearched ? renderEmptyState(
        'Start with an Engineering Query',
        'Enter technical terms, repository names, hardware architectures, or mathematical concepts above to explore verified intelligence.'
      ) : renderLoadingState('Executing hybrid search retrieval across intelligence corpus…')}
    </div>
  `;

  container.innerHTML = initialHtml;

  const refreshContainer = container.querySelector('#search-refresh-container');
  if (refreshContainer) {
    const cleanup = renderSurfaceControls(refreshContainer, {
      scope: 'search_refresh',
      onRefresh: () => {
        if (isSearched) {
          executeSearch();
        }
      },
      syncLabel: 'Sync Data',
    });
    container._viewCleanup = cleanup;
  }

  // DOM Elements
  const inputEl = container.querySelector('#search-input-field');
  const btnSearch = container.querySelector('#btn-search-exec');
  const btnReset = container.querySelector('#btn-search-reset');
  const modeSelect = container.querySelector('#search-mode-select');
  const sourceSelect = container.querySelector('#search-source-select');
  const minMaturitySelect = container.querySelector('#search-min-maturity-select');
  const maxRiskSelect = container.querySelector('#search-max-risk-select');
  const projectSelect = container.querySelector('#search-project-select');
  const daysSelect = container.querySelector('#search-days-select');
  const verifiedOnlyCheck = container.querySelector('#search-verified-only-checkbox');
  const explainCheck = container.querySelector('#search-explain-checkbox');
  const liveAnnouncer = container.querySelector('#search-live-announcer');

  // Pre-fetch dynamic catalogs for sources and projects for filter dropdowns
  await loadFilterCatalogs(sourceSelect, projectSelect, selectedSource, selectedProject);

  function buildHashUrl() {
    const q = inputEl ? inputEl.value : '';
    const params = new URLSearchParams();
    if (q) params.set('q', q);
    if (modeSelect && modeSelect.value !== 'hybrid') params.set('mode', modeSelect.value);
    if (sourceSelect && sourceSelect.value !== 'all') params.set('source', sourceSelect.value);
    if (minMaturitySelect && minMaturitySelect.value !== 'all') params.set('min_maturity', minMaturitySelect.value);
    if (maxRiskSelect && maxRiskSelect.value !== 'all') params.set('max_risk', maxRiskSelect.value);
    if (projectSelect && projectSelect.value !== 'all') params.set('project', projectSelect.value);
    if (daysSelect && daysSelect.value !== 'all') params.set('days', daysSelect.value);
    if (verifiedOnlyCheck && verifiedOnlyCheck.checked) params.set('verified_only', 'true');
    if (explainCheck && !explainCheck.checked) params.set('explain', 'false');

    const qs = params.toString();
    return `#/search${qs ? `?${qs}` : ''}`;
  }

  function triggerSearch() {
    const q = inputEl ? inputEl.value : '';
    store.setState({ searchQuery: q });
    const targetHash = buildHashUrl();
    if (window.location.hash !== targetHash) {
      window.location.hash = targetHash;
    } else if (isSearched) {
      executeSearch();
    }
  }

  function resetSearch() {
    store.setState({ searchQuery: '' });
    window.location.hash = '#/search';
  }

  // Bind Actions
  btnSearch?.addEventListener('click', triggerSearch);
  btnReset?.addEventListener('click', resetSearch);
  inputEl?.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      triggerSearch();
    }
  });

  modeSelect?.addEventListener('change', triggerSearch);
  sourceSelect?.addEventListener('change', triggerSearch);
  minMaturitySelect?.addEventListener('change', triggerSearch);
  maxRiskSelect?.addEventListener('change', triggerSearch);
  projectSelect?.addEventListener('change', triggerSearch);
  daysSelect?.addEventListener('change', triggerSearch);
  verifiedOnlyCheck?.addEventListener('change', triggerSearch);
  explainCheck?.addEventListener('change', triggerSearch);

  // Execute Search if query is active
  if (isSearched) {
    await executeSearch();
  }

  async function executeSearch() {
    const resultsArea = container.querySelector('#search-results-area');
    if (!resultsArea) return;

    const reqGen = requestManager.nextGeneration('search');
    resultsArea.innerHTML = renderLoadingState(`Searching intelligence corpus for “${escapeHtml(query)}”…`);

    try {
      const searchParams = {
        mode: searchMode,
        limit: 30,
        explain: showExplain,
      };

      if (selectedSource !== 'all') searchParams.source = selectedSource;
      if (minMaturity !== 'all') searchParams.min_maturity = minMaturity;
      if (maxRisk !== 'all') searchParams.max_risk = maxRisk;
      if (selectedProject !== 'all') searchParams.project = selectedProject;
      if (days !== 'all') searchParams.days = parseInt(days, 10);
      if (verifiedOnly) searchParams.verified_only = true;

      const response = await api.search(query, searchParams, { generation: reqGen });

      if (!requestManager.isCurrent('search', reqGen)) return;

      store.setConnection('healthy');
      const results = ensureArray(response.results || response);

      if (liveAnnouncer) {
        liveAnnouncer.textContent = `Found ${results.length} search results for ${query}`;
      }

      if (!results.length) {
        resultsArea.innerHTML = renderEmptyState(
          'No Matching Records Found',
          `No intelligence records matched the query “${escapeHtml(query)}” under the active filter set. Try broadening query terms or adjusting maturity/risk constraints.`
        );
      } else {
        resultsArea.innerHTML = `
          <div class="search-results-header">
            <div>
              <h2 class="search-results-title">Results for “${escapeHtml(query)}”</h2>
              <p class="text-muted text-sm" style="margin:0;">
                ${results.length} ranked record${results.length === 1 ? '' : 's'} · provenance &amp; ranking explanation preserved
              </p>
            </div>
          </div>
          <div class="search-results-list">
            ${results.map(renderSearchResultCard).join('')}
          </div>
        `;
      }
    } catch (err) {
      if (!requestManager.isCurrent('search', reqGen) || (err && err.isAborted && !err.isTimeout)) return;

      if (liveAnnouncer) {
        liveAnnouncer.textContent = `Search failed: ${err.message}`;
      }

      if (err.isNetworkError) {
        store.setConnection('offline', err.message);
        resultsArea.innerHTML = renderOfflineState(undefined, err.message);
      } else {
        store.setConnection('degraded', err.message);
        resultsArea.innerHTML = renderErrorState('Search Request Failed', err.message);
      }
    }
  }
}

/**
 * Helper to render options for dynamic source list.
 */
function renderSourceOptions(selected) {
  const sources = cachedSourcesList || [];
  return sources.map(src => {
    const val = typeof src === 'string' ? src : src.id || src.source || src.name || '';
    const label = typeof src === 'string' ? src : src.display_name || src.name || src.id || '';
    if (!val) return '';
    return `<option value="${escapeHtml(val)}" ${selected === val ? 'selected' : ''}>${escapeHtml(label)}</option>`;
  }).join('');
}

/**
 * Helper to render options for projects list.
 */
function renderProjectOptions(selected) {
  const projects = cachedProjectsList || [];
  return projects.map(p => {
    const val = p.id || p.name || '';
    const label = p.name || p.id || '';
    if (!val) return '';
    return `<option value="${escapeHtml(val)}" ${selected === val ? 'selected' : ''}>${escapeHtml(label)}</option>`;
  }).join('');
}

/**
 * Pre-fetch dynamic catalogs for sources and projects without blocking view render.
 */
async function loadFilterCatalogs(sourceSelect, projectSelect, selectedSource = 'all', selectedProject = 'all') {
  if (cachedSourcesList === null) {
    try {
      const res = await api.sources();
      if (res && Array.isArray(res.sources)) {
        cachedSourcesList = res.sources;
        if (sourceSelect) {
          const currentVal = sourceSelect.value || selectedSource;
          sourceSelect.innerHTML = `<option value="all" ${currentVal === 'all' ? 'selected' : ''}>All Ingested Sources</option>${renderSourceOptions(currentVal)}`;
        }
      } else {
        cachedSourcesList = [];
        if (sourceSelect) {
          const currentVal = sourceSelect.value || selectedSource;
          sourceSelect.innerHTML = `<option value="all" ${currentVal === 'all' ? 'selected' : ''}>All Ingested Sources</option>${renderSourceOptions(currentVal)}`;
        }
      }
    } catch {
      cachedSourcesList = [];
      if (sourceSelect) {
        const currentVal = sourceSelect.value || selectedSource;
        sourceSelect.innerHTML = `<option value="all" ${currentVal === 'all' ? 'selected' : ''}>All Ingested Sources</option>${renderSourceOptions(currentVal)}`;
      }
    }
  }
  if (cachedProjectsList === null) {
    try {
      const res = await api.getProjects();
      if (res && Array.isArray(res.projects)) {
        cachedProjectsList = res.projects;
        if (projectSelect) {
          const currentVal = projectSelect.value || selectedProject;
          projectSelect.innerHTML = `<option value="all" ${currentVal === 'all' ? 'selected' : ''}>General Corpus (No Boost)</option>${renderProjectOptions(currentVal)}`;
        }
      } else {
        cachedProjectsList = [];
      }
    } catch {
      cachedProjectsList = [];
    }
  }
}

/**
 * Resets cached source and project catalogs (used for isolated testing).
 */
export function resetSearchFilterCatalogsCache() {
  cachedSourcesList = null;
  cachedProjectsList = null;
}

/**
 * Renders an epistemically rigorous Search Result Card.
 */
export function renderSearchResultCard(item) {
  const entityId = item.entity_id || item.id || '';
  const title = item.title || item.canonical_title || 'Untitled Discovery';
  const verifScore = typeof item.verification_score === 'number' ? item.verification_score : null;
  const claimStatus = item.claim_status ?? null;
  const maturity = item.maturity || null;
  const riskLevel = item.risk || null;
  const riskStatus = item.risk_status ?? null;
  const sources = ensureArray(item.sources);
  const isSynthesized = Boolean(item.is_synthesized);
  const summary = item.summary || null;
  const publishedAt = item.published_at || null;
  const explain = item.explain || null;

  return `
    <article class="search-result-card" data-result-id="${escapeHtml(entityId)}">
      <div class="search-result-header">
        <div class="search-result-title-group">
          <h3 class="search-result-title">
            <a href="#/story/${encodeURIComponent(entityId)}" class="search-result-title-link" data-testid="search-story-link-${escapeHtml(entityId)}" aria-label="Open Story Dossier for ${escapeHtml(title)}">
              ${escapeHtml(title)}
            </a>
          </h3>
          <div class="search-result-submeta">
            ${sources.map(renderSourcePill).join('')}
            ${publishedAt ? `<span class="text-xs text-muted">Discovered: ${escapeHtml(formatDate(publishedAt))}</span>` : ''}
          </div>
        </div>

        <div class="search-score-pill-group">
          ${renderSearchScoreBadge(item.score)}
        </div>
      </div>

      <div class="search-result-meta-row">
        ${renderVerificationBadge(claimStatus, verifScore)}
        ${renderMaturityBadge(maturity)}
        ${renderRiskBadge(riskStatus, riskLevel)}
        ${renderProjectRelevanceBadge(item.project_relevance)}
      </div>

      ${summary ? `
        <div class="${isSynthesized ? 'summary-synthesized' : 'summary-source-excerpt'}">
          <span class="${isSynthesized ? 'summary-tag-synthesized' : 'summary-tag-excerpt'}">
            ${isSynthesized ? 'Grounded Synthesis' : 'Source Excerpt'}
          </span>
          <p class="summary-body">${escapeHtml(summary)}</p>
        </div>
      ` : ''}

      ${explain ? renderRankingDecomposition(explain) : ''}

      <div class="search-result-footer">
        <a href="#/story/${encodeURIComponent(entityId)}" class="btn btn-secondary btn-sm" data-testid="search-open-story-${escapeHtml(entityId)}" aria-label="Investigate Story Dossier for ${escapeHtml(title)}">
          Open Story Dossier &rarr;
        </a>
      </div>
    </article>
  `;
}

/**
 * Renders the score decomposition breakdown panel.
 * Strictly distinguishes genuine numeric zeros from missing, null, or invalid factors.
 */
export function renderRankingDecomposition(explain) {
  if (!explain || typeof explain !== 'object') return '';

  const formatFactor = (val) => {
    if (typeof val === 'number' && Number.isFinite(val)) {
      return val.toFixed(4);
    }
    return '—';
  };

  return `
    <div class="ranking-explain-panel" role="region" aria-label="Search Ranking Explanation">
      <div class="ranking-explain-header">
        <span class="text-xs text-semibold text-primary">Why this ranked here (Search Ranking Explanation)</span>
        <span class="text-xs text-muted">Factors explain search ordering, not epistemic truth</span>
      </div>
      <div class="ranking-factors-grid">
        <div class="factor-item">
          <span class="factor-label">Lexical Match:</span>
          <span class="factor-value mono">${formatFactor(explain.lexical_score)}</span>
        </div>
        <div class="factor-item">
          <span class="factor-label">Semantic Sim:</span>
          <span class="factor-value mono">${formatFactor(explain.semantic_score)}</span>
        </div>
        <div class="factor-item">
          <span class="factor-label">Verification Adj:</span>
          <span class="factor-value mono">${formatFactor(explain.verification_adjustment)}</span>
        </div>
        <div class="factor-item">
          <span class="factor-label">Freshness Adj:</span>
          <span class="factor-value mono">${formatFactor(explain.freshness_adjustment)}</span>
        </div>
        <div class="factor-item">
          <span class="factor-label">Project Boost:</span>
          <span class="factor-value mono">${formatFactor(explain.project_boost)}</span>
        </div>
        <div class="factor-item factor-final">
          <span class="factor-label">Final Rank Score:</span>
          <span class="factor-value mono text-semibold">${formatFactor(explain.final_score)}</span>
        </div>
      </div>
    </div>
  `;
}

