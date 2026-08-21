/**
 * HERMES Search & Query View
 * Corpus query interface with search mode filtering and grounded provenance.
 */

import { api } from '../api/endpoints.js';
import { getIcon } from '../icons/index.js';
import { renderStoryCard } from '../components/story-card.js';
import { renderLoadingState, renderEmptyState, renderErrorState, renderOfflineState } from '../components/ui-states.js';
import { escapeHtml, ensureArray } from '../utils/adapters.js';

export async function renderSearchView(container, store, routeParams = {}) {
  const query = (routeParams.q !== undefined ? routeParams.q : store.getState().searchQuery) || '';
  const searchMode = routeParams.mode || 'hybrid';
  const verifiedOnly = routeParams.verified === 'true';

  let results = [];
  let isSearched = Boolean(query);
  let searchError = null;

  let initialHtml = `
    <div class="page-header-container">
      <div>
        <span class="eyebrow">Corpus Query</span>
        <h1>Search with Context</h1>
        <p class="lead">Search ranking is a relevance signal, not a truth probability. Provenance and verification stay explicit.</p>
      </div>
    </div>

    <div class="search-bar-container">
      <input type="search" 
             id="search-input-field" 
             class="search-input-field" 
             value="${escapeHtml(query)}" 
             placeholder="Search technologies, claims, projects, or sources (e.g. 'vLLM', 'compiler', 'inference')…" 
             aria-label="Search corpus input"/>
      <button class="btn btn-primary" id="btn-search-exec">
        ${getIcon('search')} Search
      </button>
    </div>

    <div class="filter-row">
      <label for="search-mode-select" class="text-xs text-muted text-semibold">Mode:</label>
      <select id="search-mode-select" class="select-control" aria-label="Search mode">
        <option value="hybrid" ${searchMode === 'hybrid' ? 'selected' : ''}>Hybrid (Semantic + Lexical)</option>
        <option value="semantic" ${searchMode === 'semantic' ? 'selected' : ''}>Semantic Vector</option>
        <option value="lexical" ${searchMode === 'lexical' ? 'selected' : ''}>Lexical FTS</option>
      </select>

      <label for="search-verified-select" class="text-xs text-muted text-semibold" style="margin-left:var(--space-3);">Filter:</label>
      <select id="search-verified-select" class="select-control" aria-label="Verification filter">
        <option value="false" ${!verifiedOnly ? 'selected' : ''}>All Verification States</option>
        <option value="true" ${verifiedOnly ? 'selected' : ''}>Supported / Verified Only</option>
      </select>
    </div>

    <div id="search-results-area">
      ${!isSearched ? renderEmptyState(
        'Start with an Engineering Query',
        'Enter a query above to explore technologies, papers, repository commits, and verified claims across the corpus.'
      ) : renderLoadingState('Searching intelligence corpus…')}
    </div>
  `;

  container.innerHTML = initialHtml;

  // Bind search actions
  const inputEl = container.querySelector('#search-input-field');
  const btnSearch = container.querySelector('#btn-search-exec');
  const modeSelect = container.querySelector('#search-mode-select');
  const verifiedSelect = container.querySelector('#search-verified-select');

  function triggerSearch() {
    const q = inputEl.value.trim();
    const mode = modeSelect.value;
    const verified = verifiedSelect.value === 'true';
    store.setState({ searchQuery: q });
    window.location.hash = `#/search?q=${encodeURIComponent(q)}&mode=${encodeURIComponent(mode)}&verified=${verified}`;
  }

  btnSearch?.addEventListener('click', triggerSearch);
  inputEl?.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') triggerSearch();
  });
  modeSelect?.addEventListener('change', triggerSearch);
  verifiedSelect?.addEventListener('change', triggerSearch);

  // If query is present, perform actual search
  if (isSearched) {
    const resultsArea = container.querySelector('#search-results-area');
    try {
      const response = await api.search(query, {
        mode: searchMode,
        verified_only: verifiedOnly,
      });
      store.setConnection('healthy');
      results = ensureArray(response.results || response);

      if (!results.length) {
        resultsArea.innerHTML = renderEmptyState(
          'No Results Found',
          `No intelligence records matched the query “${escapeHtml(query)}”. Try broadening terms or switching search modes.`
        );
      } else {
        resultsArea.innerHTML = `
          <div class="section-header">
            <div>
              <h2>Results for “${escapeHtml(query)}”</h2>
              <p class="text-muted text-sm" style="margin:0;">
                ${results.length} ranked result${results.length === 1 ? '' : 's'} · provenance preserved
              </p>
            </div>
          </div>
          <div class="grid-2">
            ${results.map(renderStoryCard).join('')}
          </div>
        `;
      }
    } catch (err) {
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
