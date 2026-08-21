/**
 * HERMES My Projects View
 * Local engineering context profiles and dependency match intelligence.
 */

import { api } from '../api/endpoints.js';
import { renderLoadingState, renderEmptyState, renderErrorState, renderOfflineState } from '../components/ui-states.js';
import { escapeHtml, formatDate, ensureArray } from '../utils/adapters.js';

export async function renderProjectsView(container, store) {
  container.innerHTML = renderLoadingState('Loading local engineering projects…');

  try {
    const response = await api.getProjects();
    const projects = ensureArray(response.projects || response);
    store.setViewData('projects', projects);
    store.setConnection('healthy');

    let html = `
      <div class="page-header-container">
        <div>
          <span class="eyebrow">Context Intelligence</span>
          <h1>My Projects</h1>
          <p class="lead">HERMES understands your local engineering context without exposing private source code contents.</p>
        </div>
        <div class="page-header-meta">
          <strong>${projects.length}</strong>
          <span>indexed project${projects.length === 1 ? '' : 's'}</span>
        </div>
      </div>
    `;

    if (!projects.length) {
      html += renderEmptyState(
        'No Projects Configured',
        'HERMES has not indexed any local repository profiles yet. Add project definitions in your workspace to enable automatic relevance matching.'
      );
    } else {
      html += `
        <div class="grid-3">
          ${projects.map((p) => {
            const langs = ensureArray(p.languages);
            const frameworks = ensureArray(p.frameworks);
            const dbs = ensureArray(p.databases);
            const allChips = [...langs, ...frameworks, ...dbs].slice(0, 8);

            return `<article class="project-card-item" aria-label="Project profile: ${escapeHtml(p.name)}">
              <span class="mono text-xs text-muted">${escapeHtml(p.id || 'project')}</span>
              <h3 style="margin-top:var(--space-2);font-size:var(--text-md);">${escapeHtml(p.name)}</h3>
              <p class="text-sm text-muted" style="margin-top:var(--space-1);min-height:38px;">
                ${escapeHtml(p.description || 'Local engineering project profile')}
              </p>
              
              <div class="chip-group">
                ${allChips.map((c) => `<span class="chip">${escapeHtml(c)}</span>`).join('')}
              </div>

              <div class="mono text-xs text-faint" style="margin-top:var(--space-4);padding-top:var(--space-2);border-top:1px solid var(--border-subtle);">
                Last indexed · ${formatDate(p.last_indexed_at || p.updated_at)}
              </div>
            </article>`;
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
      container.innerHTML = renderErrorState('Failed to Load Projects', err.message);
    }
  }
}
