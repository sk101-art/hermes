/**
 * HERMES Runtime & Source Health View
 * Operational surface displaying daemon status, source checkpoint metrics, and system diagnostics.
 */

import { api } from '../api/endpoints.js';
import { renderLoadingState, renderEmptyState, renderErrorState, renderOfflineState } from '../components/ui-states.js';
import { escapeHtml, formatDate, formatTime, ensureArray, toTitleCase } from '../utils/adapters.js';

export async function renderRuntimeView(container, store) {
  container.innerHTML = renderLoadingState('Loading runtime health & source checkpoints…');

  try {
    const [health, runtime, sourcesResp] = await Promise.all([
      api.health().catch((e) => ({ status: 'unhealthy', error: e.message })),
      api.runtime().catch(() => ({})),
      api.sources().catch(() => ({ sources: [] })),
    ]);

    const sourceRows = ensureArray(sourcesResp.sources || sourcesResp);
    store.setViewData('runtime', { health, runtime, sources: sourceRows });

    const isHealthy = health.status === 'healthy' || health.status === 'ok';
    store.setConnection(isHealthy ? 'healthy' : 'degraded');

    let html = `
      <div class="page-header-container">
        <div>
          <span class="eyebrow">Operational Surface</span>
          <h1>Runtime & Source Health</h1>
          <p class="lead">A compact view of whether the local intelligence engine is fresh, healthy, and explainable.</p>
        </div>
      </div>

      <div class="hero-stats-grid">
        <div class="stat-card">
          <div class="stat-label">API Health</div>
          <div class="stat-value" style="font-size:var(--text-xl);display:flex;align-items:center;gap:8px;">
            <span class="status-dot ${isHealthy ? 'healthy' : 'degraded'}" aria-hidden="true"></span>
            <span>${escapeHtml(health.status || 'unknown')}</span>
          </div>
          <div class="stat-detail">local FastAPI service</div>
        </div>

        <div class="stat-card">
          <div class="stat-label">Last Ingestion</div>
          <div class="stat-value" style="font-size:var(--text-xl);">
            ${formatTime(runtime.last_ingestion_at || runtime.last_run_at)}
          </div>
          <div class="stat-detail">${formatDate(runtime.last_ingestion_at || runtime.last_run_at)}</div>
        </div>

        <div class="stat-card">
          <div class="stat-label">Configured Sources</div>
          <div class="stat-value">${sourceRows.length}</div>
          <div class="stat-detail">adapters active</div>
        </div>
      </div>

      <div class="section-header">
        <div>
          <h2>Source Adapter Checkpoints</h2>
          <p class="text-muted text-sm" style="margin:0;">Health, success timestamps, and failure counts per intelligence provider.</p>
        </div>
      </div>

      <div class="table-wrapper">
        <table class="data-table">
          <thead>
            <tr>
              <th scope="col">Source Provider</th>
              <th scope="col">Health Status</th>
              <th scope="col">Last Success</th>
              <th scope="col">Consecutive Failures</th>
            </tr>
          </thead>
          <tbody>
            ${sourceRows.length ? sourceRows.map((s) => {
              const srcName = s.source || s.name || 'Unknown Source';
              const hStatus = s.health_status || s.status || 'unknown';
              const isSrcHealthy = hStatus === 'healthy' || hStatus === 'ok';
              const isSrcOffline = hStatus === 'offline' || hStatus === 'failing';

              return `<tr>
                <td class="text-semibold">${escapeHtml(srcName)}</td>
                <td>
                  <span class="semantic-badge ${isSrcHealthy ? 'badge-verification-supported' : (isSrcOffline ? 'badge-verification-contradicted' : 'badge-verification-unverified')}">
                    ${escapeHtml(toTitleCase(hStatus))}
                  </span>
                </td>
                <td class="mono text-xs">${formatDate(s.last_success_at)}</td>
                <td class="mono text-xs">${s.consecutive_failures ?? 0}</td>
              </tr>`;
            }).join('') : `<tr><td colspan="4" class="text-muted" style="text-align:center;padding:var(--space-8);">No source adapters registered.</td></tr>`}
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
      container.innerHTML = renderErrorState('Failed to Load Runtime Status', err.message);
    }
  }
}
