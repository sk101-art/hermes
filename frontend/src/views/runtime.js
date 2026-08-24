/**
 * HERMES Runtime & Source Health View (Phase 13)
 * Authoritative single-request operational surface displaying daemon heartbeat,
 * scheduler jobs, source adapter health, structured diagnostics, and sanitized failure logs.
 */

import { api } from '../api/endpoints.js';
import { requestManager } from '../state/request-manager.js';
import { renderLoadingState, renderEmptyState, renderErrorState, renderOfflineState } from '../components/ui-states.js';
import { escapeHtml, formatDate, formatTime, ensureArray, toTitleCase } from '../utils/adapters.js';
import { focusPageHeading } from '../utils/a11y.js';

function formatFiniteNumber(val, fallback = '—') {
  if (typeof val === 'number' && Number.isFinite(val)) {
    return String(val);
  }
  return fallback;
}

function formatMetricNumber(val, fallback = 'Not recorded') {
  if (typeof val === 'number' && Number.isFinite(val)) {
    return String(val);
  }
  return fallback;
}

function formatNullOrSeconds(val) {
  if (typeof val === 'number' && Number.isFinite(val)) {
    return `${val.toFixed(2)}s`;
  }
  return '—';
}

function formatNullOrTime(isoStr) {
  if (!isoStr) return 'Not recorded';
  try {
    const d = new Date(isoStr);
    if (isNaN(d.getTime())) return 'Not recorded';
    const formatted = `${formatDate(isoStr)} ${formatTime(isoStr)}`;
    if (formatted.includes('NaN') || formatted.includes('Invalid')) return 'Not recorded';
    return `<time datetime="${escapeHtml(isoStr)}">${escapeHtml(formatted)}</time>`;
  } catch {
    return 'Not recorded';
  }
}

function getSourceStatusClass(status) {
  switch (status) {
    case 'healthy':
      return 'runtime-status-healthy';
    case 'retrying':
      return 'runtime-status-retrying';
    case 'rate_limited':
      return 'runtime-status-rate-limited';
    case 'degraded':
      return 'runtime-status-degraded';
    case 'offline':
      return 'runtime-status-offline';
    case 'disabled':
      return 'runtime-status-disabled';
    case 'unavailable':
      return 'runtime-status-unavailable';
    case 'unknown':
    default:
      return 'runtime-status-unknown';
  }
}

function getJobStatusClass(status) {
  switch (status) {
    case 'completed':
      return 'runtime-status-completed';
    case 'running':
      return 'runtime-status-running';
    case 'failed':
      return 'runtime-status-failed';
    case 'partial':
      return 'runtime-status-partial';
    case 'interrupted':
      return 'runtime-status-interrupted';
    case 'blocked':
      return 'runtime-status-blocked';
    case 'not_due':
    case 'skipped':
      return 'runtime-status-not-due';
    case 'not_applicable':
      return 'runtime-status-not-applicable';
    case 'pending':
    default:
      return 'runtime-status-pending';
  }
}

export async function renderRuntimeView(container, store) {
  const reqGen = requestManager.nextGeneration('runtime');
  container.innerHTML = renderLoadingState('Loading runtime health & operational overview…');

  try {
    // Single aggregated operational overview request
    const overview = await api.runtime({ generation: reqGen });

    if (!requestManager.isCurrent('runtime', reqGen)) {
      return; // Discard stale response on rapid view navigation
    }

    store.setViewData('runtime', overview);

    const overallStatus = (overview.status || 'UNKNOWN').toUpperCase();
    const isHealthy = overallStatus === 'HEALTHY';
    const isDegraded = overallStatus === 'DEGRADED';
    store.setConnection(isHealthy ? 'healthy' : (isDegraded ? 'degraded' : 'offline'));

    const daemon = overview.daemon || {};
    const system = overview.system || {};
    const sources = ensureArray(overview.sources || []);
    const jobs = ensureArray(overview.jobs || []);
    const failures = ensureArray(overview.recent_failures || []);
    const sourceIssues = ensureArray(overview.current_source_issues || []);
    const srcCounts = overview.source_summary || {};
    const jobCounts = overview.job_summary || {};
    const freshness = overview.intelligence_freshness || {};
    const todayBriefing = freshness.today_briefing || {};

    let html = `
      <div class="page-header-container">
        <div>
          <span class="eyebrow">Operational Transparency</span>
          <h1>Runtime & Source Health</h1>
          <p class="lead">Trustworthy operational telemetry for the HERMES daemon, scheduler pipeline, and intelligence providers.</p>
        </div>
        <div style="display:flex;align-items:center;gap:var(--space-2);">
          <button type="button" class="btn btn-secondary btn-sm" id="btn-refresh-runtime" aria-label="Refresh operational health">
            Refresh
          </button>
        </div>
      </div>

      <!-- Accessible Live Region -->
      <div class="sr-only" aria-live="polite">
        Operational overview status is ${overallStatus}. Daemon is ${daemon.status || 'stopped'}.
      </div>
    `;

    // Warnings & Notices
    if (overview.warnings && overview.warnings.length) {
      html += `
        <div class="runtime-notice-banner warning" role="region" aria-label="Operational Notices">
          <span style="font-weight:700;">Notice:</span>
          <div>
            ${overview.warnings.map((w) => `<div>${escapeHtml(w)}</div>`).join('')}
          </div>
        </div>
      `;
    }

    if (overview.issues && overview.issues.length) {
      html += `
        <div class="runtime-notice-banner error" role="region" aria-label="Operational Issues">
          <span style="font-weight:700;">Critical Issues:</span>
          <div>
            ${overview.issues.map((iss) => `<div>${escapeHtml(iss)}</div>`).join('')}
          </div>
        </div>
      `;
    }

    // Diagnostics Hero Grid
    html += `
      <div class="runtime-grid-diagnostics">
        <div class="runtime-diag-card">
          <div class="runtime-diag-label">System Health</div>
          <div class="runtime-diag-value">
            <span class="runtime-status-badge ${isHealthy ? 'runtime-status-healthy' : (isDegraded ? 'runtime-status-degraded' : 'runtime-status-unhealthy')}">
              ${escapeHtml(overallStatus)}
            </span>
          </div>
          <div class="text-xs text-muted" style="margin-top:4px;">
            ${system.is_cached ? `Cached (${system.cache_age_seconds}s ago)` : 'Live probe'}
          </div>
        </div>

        <div class="runtime-diag-card">
          <div class="runtime-diag-label">HERMES Daemon</div>
          <div class="runtime-diag-value">
            <span class="runtime-status-badge ${daemon.status === 'running' ? 'runtime-status-running' : (daemon.status === 'stale' ? 'runtime-status-degraded' : 'runtime-status-disabled')}">
              ${escapeHtml((daemon.status || 'stopped').toUpperCase())}
            </span>
            ${daemon.pid ? `<span class="mono text-xs text-muted">PID ${daemon.pid}</span>` : ''}
          </div>
          <div class="text-xs text-muted" style="margin-top:4px;">
            ${daemon.heartbeat_timestamp ? `Heartbeat: ${daemon.heartbeat_age_seconds !== null && daemon.heartbeat_age_seconds !== undefined ? `${daemon.heartbeat_age_seconds}s ago` : formatNullOrTime(daemon.heartbeat_timestamp)}` : 'No daemon heartbeat recorded'}
          </div>
        </div>

        <div class="runtime-diag-card">
          <div class="runtime-diag-label">Effective Timezone</div>
          <div class="runtime-diag-value" style="font-size:var(--text-base);">
            ${escapeHtml(overview.effective_timezone || 'UTC')}
          </div>
          <div class="text-xs text-muted mono" style="margin-top:4px;">
            ${escapeHtml(overview.scheduler_time || '')}
          </div>
        </div>

        <div class="runtime-diag-card">
          <div class="runtime-diag-label">Database & Storage</div>
          <div class="runtime-diag-value" style="font-size:var(--text-base);">
            ${escapeHtml(system.database || 'ok')}
          </div>
          <div class="text-xs text-muted" style="margin-top:4px;">
            Disk: ${system.disk_free_mb !== null && system.disk_free_mb !== undefined ? `${system.disk_free_mb} MB free` : '—'} (${escapeHtml(system.disk_status || 'ok')})
          </div>
        </div>
      </div>
    `;

    // Section 1: Source Adapters Checkpoints
    html += `
      <div class="runtime-section-header">
        <div>
          <h2 class="runtime-section-title">Source Adapter Checkpoints</h2>
          <span class="text-xs text-muted">Per-provider poll intervals, attempt timestamps, backoff schedule, and failure tracking.</span>
        </div>
        <div class="runtime-summary-chips">
          ${typeof srcCounts.healthy === 'number' ? `<span class="runtime-status-badge runtime-status-healthy">${srcCounts.healthy} Healthy</span>` : ''}
          ${typeof srcCounts.retrying === 'number' && srcCounts.retrying > 0 ? `<span class="runtime-status-badge runtime-status-retrying">${srcCounts.retrying} Retrying</span>` : ''}
          ${typeof srcCounts.rate_limited === 'number' && srcCounts.rate_limited > 0 ? `<span class="runtime-status-badge runtime-status-rate-limited">${srcCounts.rate_limited} Rate-Limited</span>` : ''}
          ${typeof srcCounts.degraded === 'number' && srcCounts.degraded > 0 ? `<span class="runtime-status-badge runtime-status-degraded">${srcCounts.degraded} Degraded</span>` : ''}
          ${typeof srcCounts.disabled === 'number' && srcCounts.disabled > 0 ? `<span class="runtime-status-badge runtime-status-disabled">${srcCounts.disabled} Disabled</span>` : ''}
        </div>
      </div>

      <div class="table-wrapper" tabindex="0" role="region" aria-label="Source Adapter Checkpoints Table">
        <table class="runtime-table" aria-label="Source Adapter Checkpoints">
          <caption class="sr-only">Source Adapter Checkpoints and Provider Telemetry</caption>
          <thead>
            <tr>
              <th scope="col">Source</th>
              <th scope="col">Status</th>
              <th scope="col">Last Attempt</th>
              <th scope="col">Last Success</th>
              <th scope="col">Failures</th>
              <th scope="col">Next Retry / Schedule</th>
              <th scope="col">Latest Sanitized Error</th>
            </tr>
          </thead>
          <tbody>
            ${sources.length ? sources.map((s) => {
              const statusClass = getSourceStatusClass(s.health_status);
              return `<tr>
                <td class="text-semibold">${escapeHtml(s.source)}</td>
                <td>
                  <span class="runtime-status-badge ${statusClass}" title="Source status: ${escapeHtml(s.health_status || 'unknown')}" aria-label="Source status: ${escapeHtml(s.health_status || 'unknown')}">
                    ${escapeHtml((s.health_status || 'unknown').replace('_', ' '))}
                  </span>
                  ${s.failure_threshold_reached ? '<span class="runtime-threshold-tag" title="Failure threshold reached; capped at max backoff">THRESHOLD</span>' : ''}
                </td>
                <td class="mono text-xs">${formatNullOrTime(s.last_attempt_at)}</td>
                <td class="mono text-xs">${formatNullOrTime(s.last_success_at)}</td>
                <td class="mono text-xs">${formatFiniteNumber(s.consecutive_failures)}</td>
                <td class="text-xs">
                  ${s.next_retry_at ? `<span class="mono">${formatTime(s.next_retry_at)}</span> (${s.backoff_seconds ? `${Math.ceil(s.backoff_seconds / 60)}m backoff` : 'due'})` : escapeHtml(s.due_reason || '—')}
                </td>
                <td>
                  ${s.sanitized_error ? `<span class="runtime-sanitized-error" title="${escapeHtml(s.sanitized_error)}">${s.error_category ? `[${escapeHtml(s.error_category)}] ` : ''}${escapeHtml(s.sanitized_error)}</span>` : '<span class="text-muted text-xs">—</span>'}
                </td>
              </tr>`;
            }).join('') : '<tr><td colspan="7" class="text-muted" style="text-align:center;padding:var(--space-6);">No source adapters configured.</td></tr>'}
          </tbody>
        </table>
      </div>
    `;

    // Section 2: Scheduled Pipeline Jobs
    html += `
      <div class="runtime-section-header">
        <div>
          <h2 class="runtime-section-title">Scheduled Runtime Jobs</h2>
          <span class="text-xs text-muted">Autonomous background jobs, prerequisite satisfaction, and execution history.</span>
        </div>
        <div class="runtime-summary-chips">
          ${typeof jobCounts.completed === 'number' ? `<span class="runtime-status-badge runtime-status-completed">${jobCounts.completed} Completed</span>` : ''}
          ${typeof jobCounts.running === 'number' && jobCounts.running > 0 ? `<span class="runtime-status-badge runtime-status-running">${jobCounts.running} Running</span>` : ''}
          ${typeof jobCounts.partial === 'number' && jobCounts.partial > 0 ? `<span class="runtime-status-badge runtime-status-partial">${jobCounts.partial} Partial</span>` : ''}
          ${typeof jobCounts.failed === 'number' && jobCounts.failed > 0 ? `<span class="runtime-status-badge runtime-status-failed">${jobCounts.failed} Failed</span>` : ''}
          ${typeof jobCounts.interrupted === 'number' && jobCounts.interrupted > 0 ? `<span class="runtime-status-badge runtime-status-interrupted">${jobCounts.interrupted} Interrupted</span>` : ''}
          ${typeof jobCounts.blocked === 'number' && jobCounts.blocked > 0 ? `<span class="runtime-status-badge runtime-status-blocked">${jobCounts.blocked} Blocked</span>` : ''}
        </div>
      </div>

      <div class="table-wrapper" tabindex="0" role="region" aria-label="Scheduled Runtime Jobs Table">
        <table class="runtime-table" aria-label="Scheduled Runtime Jobs">
          <caption class="sr-only">Scheduled Runtime Jobs and Background Execution Telemetry</caption>
          <thead>
            <tr>
              <th scope="col">Job Name</th>
              <th scope="col">Status</th>
              <th scope="col">Last Completed</th>
              <th scope="col">Duration</th>
              <th scope="col">Runs / Fails</th>
              <th scope="col">Next Schedule / Blocked Reason</th>
              <th scope="col">Telemetry Timeout</th>
            </tr>
          </thead>
          <tbody>
            ${jobs.length ? jobs.map((j) => {
              const jClass = getJobStatusClass(j.status);
              return `<tr>
                <td class="text-semibold">${escapeHtml(j.job_name)}</td>
                <td>
                  <span class="runtime-status-badge ${jClass}" title="Job status: ${escapeHtml(j.status || 'pending')}" aria-label="Job status: ${escapeHtml(j.status || 'pending')}">
                    ${escapeHtml((j.status || 'pending').replace('_', ' '))}
                  </span>
                </td>
                <td class="mono text-xs">${formatNullOrTime(j.last_completed_at)}</td>
                <td class="mono text-xs">${formatNullOrSeconds(j.duration_seconds)}</td>
                <td class="mono text-xs">${formatFiniteNumber(j.run_count)} / ${formatFiniteNumber(j.failure_count)}</td>
                <td class="text-xs">
                  ${j.blocked_by ? `<span class="text-danger" style="font-weight:600;">Blocked by ${escapeHtml(j.blocked_by)}</span>: ${escapeHtml(j.blocked_reason || '')}` : escapeHtml(j.next_schedule || '—')}
                </td>
                <td class="text-xs text-muted">
                  ${j.configured_timeout_minutes ? `${j.configured_timeout_minutes}m (not enforced)` : '—'}
                </td>
              </tr>`;
            }).join('') : '<tr><td colspan="7" class="text-muted" style="text-align:center;padding:var(--space-6);">No jobs scheduled.</td></tr>'}
          </tbody>
        </table>
      </div>
    `;

    // Section 3: Recent Operational Failures & Current Source Issues
    if (failures.length > 0 || sourceIssues.length > 0) {
      html += `
        <div class="runtime-section-header">
          <div>
            <h2 class="runtime-section-title">Operational Issues & Recent Failures</h2>
            <span class="text-xs text-muted">Isolated execution failures and degraded intelligence providers with sanitized summaries.</span>
          </div>
        </div>

        <div class="table-wrapper" tabindex="0" role="region" aria-label="Recent Operational Issues Table">
          <table class="runtime-table" aria-label="Recent Operational Issues">
            <caption class="sr-only">Recent Operational Issues and Execution Failures</caption>
            <thead>
              <tr>
                <th scope="col">Target</th>
                <th scope="col">Type</th>
                <th scope="col">Status</th>
                <th scope="col">Observed / Started</th>
                <th scope="col">Error Category</th>
                <th scope="col">Sanitized Summary</th>
              </tr>
            </thead>
            <tbody>
              ${sourceIssues.map((si) => `
                <tr>
                  <td class="text-semibold">${escapeHtml(si.source)}</td>
                  <td><span class="text-xs text-muted">SOURCE</span></td>
                  <td><span class="runtime-status-badge ${getSourceStatusClass(si.health_status)}">${escapeHtml(si.health_status)}</span></td>
                  <td class="mono text-xs">${formatNullOrTime(si.last_attempt_at)}</td>
                  <td class="mono text-xs">${escapeHtml(si.error_category || 'unknown')}</td>
                  <td><span class="runtime-sanitized-error">${escapeHtml(si.sanitized_error || 'No summary')}</span></td>
                </tr>
              `).join('')}
              ${failures.map((f) => `
                <tr>
                  <td class="text-semibold">${escapeHtml(f.job_name)}</td>
                  <td><span class="text-xs text-muted">JOB RUN</span></td>
                  <td><span class="runtime-status-badge ${getJobStatusClass(f.status)}">${escapeHtml(f.status)}</span></td>
                  <td class="mono text-xs">${formatNullOrTime(f.started_at)}</td>
                  <td class="mono text-xs">${escapeHtml(f.error_category || 'unknown')}</td>
                  <td><span class="runtime-sanitized-error">${escapeHtml(f.sanitized_error || 'No summary')}</span></td>
                </tr>
              `).join('')}
            </tbody>
          </table>
        </div>
      `;
    }

    // Section 4: Intelligence Freshness & Lifetime Telemetry
    html += `
      <div class="runtime-section-header">
        <div>
          <h2 class="runtime-section-title">Intelligence Freshness & Lifetime Metrics</h2>
          <span class="text-xs text-muted">Daily morning briefing state and lifetime engine execution counters.</span>
        </div>
      </div>

      <div class="runtime-grid-diagnostics" style="margin-bottom:var(--space-8);">
        <div class="runtime-diag-card">
          <div class="runtime-diag-label">Today's Morning Briefing</div>
          <div class="runtime-diag-value">
            <span class="runtime-status-badge ${todayBriefing.generated ? 'runtime-status-healthy' : 'runtime-status-pending'}">
              ${todayBriefing.generated ? 'GENERATED' : 'NOT GENERATED'}
            </span>
          </div>
          <div class="text-xs text-muted" style="margin-top:4px;">
            ${todayBriefing.generated ? `${typeof todayBriefing.total_items === 'number' ? `${todayBriefing.total_items} items` : 'Snapshot'} on ${escapeHtml(todayBriefing.date || '')}` : `Scheduled for ${escapeHtml(todayBriefing.date || '')}`}
          </div>
        </div>

        <div class="runtime-diag-card">
          <div class="runtime-diag-label">Last Ingestion Run</div>
          <div class="runtime-diag-value" style="font-size:var(--text-base);">
            ${freshness.last_successful_ingestion ? formatNullOrTime(freshness.last_successful_ingestion) : 'Never completed'}
          </div>
          <div class="text-xs text-muted" style="margin-top:4px;">
            Sources Polled: ${formatMetricNumber(overview.lifetime_metrics?.sources_polled)}
          </div>
        </div>

        <div class="runtime-diag-card">
          <div class="runtime-diag-label">Lifetime Events Ingested</div>
          <div class="runtime-diag-value">
            ${formatMetricNumber(overview.lifetime_metrics?.events_ingested)}
          </div>
          <div class="text-xs text-muted" style="margin-top:4px;">
            Inbox Items: ${formatMetricNumber(overview.lifetime_metrics?.inbox_items_generated)}
          </div>
        </div>

        <div class="runtime-diag-card">
          <div class="runtime-diag-label">Lifetime Job Outcomes</div>
          <div class="runtime-diag-value" style="font-size:var(--text-sm);">
            <span class="text-success">${formatMetricNumber(overview.lifetime_metrics?.jobs_completed)} ok</span> ·
            <span class="text-danger">${formatMetricNumber(overview.lifetime_metrics?.jobs_failed)} fails</span> ·
            <span class="text-muted">${formatMetricNumber(overview.lifetime_metrics?.jobs_interrupted)} intr</span>
          </div>
          <div class="text-xs text-muted" style="margin-top:4px;">
            Briefings: ${formatMetricNumber(overview.lifetime_metrics?.briefings_generated)}
          </div>
        </div>
      </div>
    `;

    container.innerHTML = html;
    focusPageHeading(container);

    // Attach read-only refresh button handler
    const btnRefresh = container.querySelector('#btn-refresh-runtime');
    if (btnRefresh) {
      btnRefresh.addEventListener('click', () => {
        renderRuntimeView(container, store);
      });
    }
  } catch (err) {
    if (!requestManager.isCurrent('runtime', reqGen) || (err && err.isAborted && !err.isTimeout)) {
      return;
    }
    if (err.isNetworkError) {
      store.setConnection('offline', err.message);
      container.innerHTML = renderOfflineState(undefined, err.message);
    } else {
      store.setConnection('degraded', err.message);
      container.innerHTML = renderErrorState('Failed to Load Runtime Status', err.message);
    }
    const retryBtn = container.querySelector('#retry-btn') || container.querySelector('.btn-retry-view');
    if (retryBtn) {
      retryBtn.addEventListener('click', () => {
        renderRuntimeView(container, store);
      });
    }
  }
}
