/**
 * HERMES My Projects View
 * Local engineering context profiles and dependency match intelligence.
 * Supports Index View (#/projects) and Deep Detail View (#/projects/{project_id}).
 */

import { api } from '../api/endpoints.js';
import { ensureSessionToken } from '../api/client.js';
import { requestManager } from '../state/request-manager.js';
import { renderLoadingState, renderEmptyState, renderErrorState, renderOfflineState } from '../components/ui-states.js';
import { escapeHtml, formatDate, ensureArray } from '../utils/adapters.js';
import {
  renderProjectRelevanceBadge,
  renderProjectImpactBadge,
} from '../components/badges.js';
import { renderSurfaceControls } from '../components/surface-controls.js';


/**
 * Format match type into human-readable label.
 */
function formatMatchType(type) {
  if (!type) return 'General Related';
  const clean = String(type).trim().toLowerCase();
  const map = {
    technology_overlap: 'Technology Overlap',
    compatible_tool: 'Compatible Tool',
    direct_dependency: 'Direct Dependency',
    storage_relevant: 'Storage Relevant',
    architecture_relevant: 'Architecture Relevant',
    research_relevant: 'Research Relevant',
    general_related: 'General Related',
    vulnerability: 'Vulnerability Match',
    breaking_change: 'Breaking Change Match',
    deprecation: 'Deprecation Match',
  };
  if (map[clean]) return map[clean];
  return clean.split('_').map((w) => w.charAt(0).toUpperCase() + w.slice(1)).join(' ');
}

/**
 * Map a backend relationship_label to a human-readable relationship badge.
 * Weak relationships must be stated as weak — never dressed up.
 */
function formatRelationshipLabel(label) {
  const map = {
    direct_match: ['badge-primary', 'Direct match'],
    architectural_similarity: ['badge-neutral', 'Architectural similarity'],
    potential_alternative: ['badge-neutral', 'Potential alternative'],
    weak_contextual: ['badge-subtle', 'Weak contextual relationship'],
    insufficient_evidence: ['badge-subtle', 'Insufficient evidence'],
  };
  const [cls, text] = map[label] || ['badge-subtle', 'Insufficient evidence'];
  return `<span class="badge ${cls}">${escapeHtml(text)}</span>`;
}

/**
 * Render a list of evidence references (file:line pointers, URLs, claims).
 */
function renderEvidenceRefs(refs) {
  const list = ensureArray(refs);
  if (!list.length) return '';
  return `
    <ul class="evidence-ref-list text-xs text-muted" style="margin:var(--space-1) 0 0 0;padding-left:var(--space-4);">
      ${list.map((ref) => {
        const label = ref.label || 'evidence';
        const detail = ref.detail ? ` — ${escapeHtml(ref.detail)}` : '';
        if (ref.url) {
          return `<li><a href="${escapeHtml(ref.url)}" target="_blank" rel="noopener noreferrer" style="color:var(--accent-primary);">${escapeHtml(label)}</a>${detail}</li>`;
        }
        return `<li><span class="mono">${escapeHtml(label)}</span>${detail}</li>`;
      }).join('')}
    </ul>
  `;
}

/**
 * Render the structured backend advisory (replaces the old formatAdvisory lookup).
 */
function renderRecommendedAction(action) {
  if (!action || !action.action) return '';
  const urgency = action.urgency || 'low';
  const urgencyBadge = urgency === 'high'
    ? '<span class="badge badge-danger">High urgency</span>'
    : urgency === 'medium'
      ? '<span class="badge badge-warning">Medium urgency</span>'
      : '<span class="badge badge-subtle">Low urgency</span>';
  return `
    <div class="recommended-action-box" style="margin-top:var(--space-3);padding:var(--space-3);background:var(--bg-panel-subtle);border-radius:var(--radius-sm);border-left:3px solid var(--accent-primary);">
      <div style="display:flex;justify-content:space-between;align-items:center;gap:var(--space-2);margin-bottom:var(--space-1);">
        <span class="text-xs" style="font-weight:600;color:var(--ink-secondary);">Suggested next step</span>
        ${urgencyBadge}
      </div>
      <p class="text-sm" style="margin:0 0 var(--space-1) 0;font-weight:600;">${escapeHtml(action.action)}</p>
      ${action.rationale ? `<p class="text-xs text-muted" style="margin:0 0 var(--space-2) 0;">${escapeHtml(action.rationale)}</p>` : ''}
      ${ensureArray(action.validation_steps).length ? `
        <div class="text-xs text-muted" style="margin-top:var(--space-1);">
          <strong>Validate:</strong>
          <ul style="margin:var(--space-1) 0 0 0;padding-left:var(--space-4);">
            ${ensureArray(action.validation_steps).map((s) => `<li>${escapeHtml(s)}</li>`).join('')}
          </ul>
        </div>
      ` : ''}
      ${ensureArray(action.caveats).length ? `
        <div class="text-xs text-faint" style="margin-top:var(--space-1);">
          ${ensureArray(action.caveats).map((c) => `<span>⚠ ${escapeHtml(c)}</span>`).join('<br>')}
        </div>
      ` : ''}
    </div>
  `;
}

/**
 * Render a full 9-part explanation match card.
 * Order: What it is → What happened → Why matched → Possible effect →
 * Suggested next step → Evidence (+ limitations).
 */
function renderExplainedMatchCard(m, canonicalId) {
  const expl = m.explanation;
  const isLegacy = !expl || m.explanation_version === 'legacy_unexplained';

  const titleHtml = m.story_available && m.cluster_id
    ? `<a href="#/story/${encodeURIComponent(m.cluster_id)}?project=${encodeURIComponent(canonicalId)}" class="match-title-link" data-testid="projects-match-link-${escapeHtml(m.cluster_id)}" style="color:var(--ink-primary);font-weight:600;text-decoration:none;">${escapeHtml(m.title)}</a>`
    : `<span style="font-weight:600;">${escapeHtml(m.title)}</span> <span class="badge badge-subtle">Story unavailable</span>`;

  if (isLegacy) {
    // Legacy rows have no explanation and must not be presented as actionable.
    return `
      <div class="match-card match-card-legacy" style="padding:var(--space-4);background:var(--bg-panel);border:1px solid var(--border-subtle);border-radius:var(--radius-md);opacity:0.85;">
        <div style="display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:var(--space-2);margin-bottom:var(--space-2);">
          <span class="chip match-type-chip" style="font-weight:500;">${escapeHtml(formatMatchType(m.match_type))}</span>
          <div style="display:flex;gap:var(--space-2);align-items:center;">
            ${formatRelationshipLabel('insufficient_evidence')}
            ${renderProjectRelevanceBadge(m.relevance_score)}
            ${renderProjectImpactBadge(m.impact_score)}
          </div>
        </div>
        <h3 class="match-title" style="margin:0 0 var(--space-2) 0;font-size:var(--text-md);font-weight:inherit;">${titleHtml}</h3>
        <p class="text-xs text-muted" style="margin:0;">
          This match predates the explanation system and has no grounded explanation yet.
          It is shown for reference only and is not presented as actionable. Rescan the project to regenerate it.
        </p>
      </div>
    `;
  }

  const dims = ensureArray(expl.matched_dimensions);
  const effects = ensureArray(expl.potential_effects);
  const limitations = ensureArray(expl.limitations);
  const evidence = ensureArray(expl.evidence_references);

  return `
    <div class="match-card" style="padding:var(--space-4);background:var(--bg-panel);border:1px solid var(--border-subtle);border-radius:var(--radius-md);">
      <!-- 1. What it is -->
      <div style="display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:var(--space-2);margin-bottom:var(--space-2);">
        <div style="display:flex;gap:var(--space-2);align-items:center;flex-wrap:wrap;">
          <span class="chip match-type-chip" style="font-weight:500;">${escapeHtml(formatMatchType(m.match_type))}</span>
          ${formatRelationshipLabel(expl.relationship_label)}
        </div>
        <div style="display:flex;gap:var(--space-2);align-items:center;">
          ${renderProjectRelevanceBadge(m.relevance_score)}
          ${renderProjectImpactBadge(m.impact_score)}
        </div>
      </div>
      <h3 class="match-title" style="margin:0 0 var(--space-1) 0;font-size:var(--text-md);font-weight:inherit;">${titleHtml}</h3>
      ${expl.subject_kind ? `<div class="mono text-xs text-faint" style="margin-bottom:var(--space-2);">${escapeHtml(expl.subject_kind)}</div>` : ''}

      <!-- 2. What happened -->
      ${expl.what_happened ? `
        <div class="match-part" style="margin-bottom:var(--space-2);">
          <div class="text-xs" style="font-weight:600;color:var(--ink-secondary);margin-bottom:var(--space-1);">What happened</div>
          <p class="text-sm" style="margin:0;">${escapeHtml(expl.what_happened)}</p>
        </div>
      ` : ''}

      <!-- 3. Why matched -->
      <div class="match-part" style="margin-bottom:var(--space-2);">
        <div class="text-xs" style="font-weight:600;color:var(--ink-secondary);margin-bottom:var(--space-1);">Why this was matched</div>
        ${expl.relevance_summary ? `<p class="text-sm" style="margin:0 0 var(--space-2) 0;">${escapeHtml(expl.relevance_summary)}</p>` : ''}
        ${dims.length ? `
          <div style="display:flex;flex-direction:column;gap:var(--space-1);">
            ${dims.map((d) => `
              <div class="dimension-row text-xs" style="padding:var(--space-2);background:var(--bg-panel-subtle);border-radius:var(--radius-sm);">
                <strong>${escapeHtml(d.dimension)}</strong>: ${escapeHtml(d.project_value)} ↔ ${escapeHtml(d.intelligence_value)}
                <span class="text-muted"> — ${escapeHtml(d.connection)}</span>
                <span class="badge badge-subtle" style="margin-left:var(--space-1);">${escapeHtml(d.evidence_strength || 'weak')} evidence</span>
              </div>
            `).join('')}
          </div>
        ` : ''}
      </div>

      <!-- 4. Possible effect -->
      ${effects.length ? `
        <div class="match-part" style="margin-bottom:var(--space-2);">
          <div class="text-xs" style="font-weight:600;color:var(--ink-secondary);margin-bottom:var(--space-1);">Possible effect</div>
          <ul style="margin:0;padding-left:var(--space-4);">
            ${effects.map((e) => `
              <li class="text-sm">
                ${escapeHtml(e.effect)}
                <span class="badge badge-subtle" style="margin-left:var(--space-1);">${escapeHtml(e.likelihood || 'possible')} · ${escapeHtml(e.severity || 'low')}</span>
              </li>
            `).join('')}
          </ul>
        </div>
      ` : ''}

      <!-- 5. Suggested next step -->
      ${renderRecommendedAction(expl.recommended_action)}

      <!-- Limitations -->
      ${limitations.length ? `
        <div class="match-part" style="margin-top:var(--space-2);">
          <div class="text-xs text-faint">
            <strong>Limitations:</strong> ${limitations.map(escapeHtml).join(' · ')}
          </div>
        </div>
      ` : ''}

      <!-- 6. Evidence -->
      ${evidence.length ? `
        <div class="match-part" style="margin-top:var(--space-2);">
          <div class="text-xs" style="font-weight:600;color:var(--ink-secondary);margin-bottom:var(--space-1);">Evidence</div>
          ${renderEvidenceRefs(evidence)}
        </div>
      ` : ''}
    </div>
  `;
}

/**
 * Render a severity-oriented engineering concern card using the structured
 * backend advisory (never the removed formatAdvisory lookup).
 */
function renderConcernCard(r, canonicalId) {
  const concernType = r.concern_type || 'unknown';
  const severityMap = {
    vulnerability: ['badge-danger', 'Vulnerability'],
    breaking_change: ['badge-warning', 'Breaking Change'],
    deprecation: ['badge-neutral', 'Deprecation'],
    assessed_risk: ['badge-danger', `Assessed Risk · ${r.risk_level || 'high'}`],
    incompatible_dependency: ['badge-warning', 'Incompatible Dependency'],
    removed_feature: ['badge-warning', 'Removed / Changed Feature'],
    operational_incompat: ['badge-danger', 'Operational Incompatibility'],
    evidence_regression: ['badge-warning', 'Evidence-Backed Regression'],
  };
  const [badgeCls, badgeText] = severityMap[concernType] || ['badge-subtle', concernType];

  const titleHtml = r.story_available && r.cluster_id
    ? `<a href="#/story/${encodeURIComponent(r.cluster_id)}?project=${encodeURIComponent(canonicalId)}" class="concern-title-link" data-testid="projects-concern-link-${escapeHtml(r.cluster_id)}" style="color:var(--ink-primary);font-weight:600;text-decoration:none;">${escapeHtml(r.title)}</a>`
    : `<span style="font-weight:600;">${escapeHtml(r.title)}</span> <span class="badge badge-subtle">Story unavailable</span>`;

  return `
    <div class="concern-card" style="padding:var(--space-4);background:var(--bg-panel);border:1px solid var(--border-subtle);border-radius:var(--radius-md);">
      <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:var(--space-2);margin-bottom:var(--space-2);">
        <div><span class="badge ${badgeCls}">${escapeHtml(badgeText)}</span></div>
        <div style="display:flex;gap:var(--space-2);align-items:center;">
          ${renderProjectImpactBadge(r.impact_score)}
          ${renderProjectRelevanceBadge(r.relevance_score)}
        </div>
      </div>

      <h3 class="concern-title" style="margin:0 0 var(--space-2) 0;font-size:inherit;font-weight:inherit;">${titleHtml}</h3>

      ${r.risk_status ? `
        <div class="mono text-xs text-muted" style="margin-bottom:var(--space-2);">
          Canonical Risk Status: <strong>${escapeHtml(r.risk_status)}</strong>
          ${typeof r.risk_score === 'number' ? ` · Score: ${(r.risk_score * 100).toFixed(0)}%` : ''}
        </div>
      ` : ''}

      <p class="text-xs text-faint" style="margin:0;">
        Surfaced because a concrete concern criterion was met (never from impact score alone).
      </p>
    </div>
  `;
}

/**
 * Render the structured project narrative overview (what it does, capabilities,
 * architecture, components) with evidence references.
 */
function renderNarrativeSection(narrative) {
  if (!narrative) {
    return `
      <section class="project-section" style="margin-bottom:var(--space-6);">
        <h2 style="font-size:var(--text-lg);margin-bottom:var(--space-2);">Project Overview</h2>
        <p class="text-sm text-muted">No structured documentation narrative could be extracted for this project yet. Rescan the project after adding a README.</p>
      </section>
    `;
  }

  const status = narrative.extraction_status || 'unknown';
  const statusBadge = status === 'extracted'
    ? '<span class="badge badge-neutral">Documentation extracted</span>'
    : status === 'partial'
      ? '<span class="badge badge-subtle">Partial extraction</span>'
      : '<span class="badge badge-subtle">No documentation narrative</span>';

  const purpose = narrative.purpose_summary;
  const capabilities = ensureArray(narrative.capability_summaries);
  const architecture = narrative.architecture_summary;
  const components = ensureArray(narrative.primary_components);
  const refs = ensureArray(narrative.evidence_references);
  const userDesc = narrative.user_description;

  return `
    <section class="project-section project-narrative-section" style="margin-bottom:var(--space-6);">
      <div style="display:flex;justify-content:space-between;align-items:baseline;flex-wrap:wrap;gap:var(--space-2);margin-bottom:var(--space-2);">
        <h2 style="font-size:var(--text-lg);margin:0;">Project Overview</h2>
        ${statusBadge}
      </div>
      <p class="text-sm text-muted" style="margin-bottom:var(--space-4);">
        What this project does, extracted from its documentation with source references.
      </p>

      ${userDesc ? `
        <div class="narrative-part" style="margin-bottom:var(--space-3);">
          <div class="text-xs" style="font-weight:600;color:var(--ink-secondary);margin-bottom:var(--space-1);">Your description</div>
          <p class="text-sm" style="margin:0;">${escapeHtml(userDesc)}</p>
        </div>
      ` : ''}

      ${purpose ? `
        <div class="narrative-part" style="margin-bottom:var(--space-3);">
          <div class="text-xs" style="font-weight:600;color:var(--ink-secondary);margin-bottom:var(--space-1);">What it does</div>
          <p class="text-sm" style="margin:0;">${escapeHtml(purpose)}</p>
        </div>
      ` : ''}

      ${capabilities.length ? `
        <div class="narrative-part" style="margin-bottom:var(--space-3);">
          <div class="text-xs" style="font-weight:600;color:var(--ink-secondary);margin-bottom:var(--space-1);">Capabilities</div>
          <ul style="margin:0;padding-left:var(--space-4);">
            ${capabilities.map((c) => `<li class="text-sm">${escapeHtml(c)}</li>`).join('')}
          </ul>
        </div>
      ` : ''}

      ${architecture ? `
        <div class="narrative-part" style="margin-bottom:var(--space-3);">
          <div class="text-xs" style="font-weight:600;color:var(--ink-secondary);margin-bottom:var(--space-1);">Architecture</div>
          <p class="text-sm" style="margin:0;">${escapeHtml(architecture)}</p>
        </div>
      ` : ''}

      ${components.length ? `
        <div class="narrative-part" style="margin-bottom:var(--space-3);">
          <div class="text-xs" style="font-weight:600;color:var(--ink-secondary);margin-bottom:var(--space-1);">Primary components</div>
          <div class="chip-group" style="margin-top:0;">
            ${components.map((c) => `<span class="chip">${escapeHtml(c)}</span>`).join('')}
          </div>
        </div>
      ` : ''}

      ${refs.length ? `
        <div class="narrative-part" style="margin-top:var(--space-2);">
          <div class="text-xs" style="font-weight:600;color:var(--ink-secondary);margin-bottom:var(--space-1);">Source references</div>
          ${renderEvidenceRefs(refs)}
        </div>
      ` : ''}
    </section>
  `;
}

/**
 * Main View Renderer for Projects surface.
 */
export async function renderProjectsView(container, store, routeParams = {}) {
  const projectId = routeParams?.projectId;

  if (projectId) {
    await renderProjectDetailView(container, store, projectId);
  } else {
    await renderProjectIndexView(container, store);
  }
}

/**
 * Renders the Project Folder Access section: approved directories with live
 * status, plus replace / revoke / open-in-Explorer actions.
 */
async function renderFolderAccessSection(container, store) {
  const region = container.querySelector('#folder-access-content');
  if (!region) return;

  try {
    const response = await api.listFolderApprovals();
    const approvals = ensureArray(response.approvals || []);

    if (!approvals.length) {
      region.innerHTML = '<p class="text-sm text-muted">No folders have been approved yet. Use “Add Local Project” above.</p>';
      return;
    }

    const statusBadge = (status) => {
      const map = {
        ok: ['badge-neutral', 'Accessible'],
        missing: ['badge-warning', 'Missing'],
        unreadable: ['badge-warning', 'Unreadable'],
        revoked: ['badge-subtle', 'Revoked'],
      };
      const [cls, label] = map[status] || ['badge-neutral', status || 'Unknown'];
      return `<span class="badge ${cls}">${escapeHtml(label)}</span>`;
    };

    region.innerHTML = `
      <div style="display:flex;flex-direction:column;gap:var(--space-3);">
        ${approvals.map((a, idx) => `
          <div class="folder-access-row" data-path="${escapeHtml(a.path || '')}" data-project-id="${escapeHtml(a.project_id || '')}" style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:var(--space-2);padding:var(--space-3);border:1px solid var(--border-subtle);border-radius:var(--radius-md);background:var(--bg-panel-subtle);">
            <div style="min-width:0;flex:1;">
              <div class="mono text-sm" style="word-break:break-all;">${escapeHtml(a.path || '')}</div>
              <div class="text-xs text-muted" style="margin-top:2px;">
                ${a.project_name ? `Project: ${escapeHtml(a.project_name)}` : ''}
                ${a.approved_at ? ` · Approved ${formatDate(a.approved_at)}` : ''}
              </div>
            </div>
            <div style="display:flex;align-items:center;gap:var(--space-2);flex-wrap:wrap;">
              ${statusBadge(a.status)}
              ${a.state === 'active' ? `
                <button type="button" class="btn btn-xs btn-outline btn-folder-open" data-project-id="${escapeHtml(a.project_id || '')}">Open</button>
                <button type="button" class="btn btn-xs btn-outline btn-folder-replace" data-project-id="${escapeHtml(a.project_id || '')}">Replace…</button>
                <button type="button" class="btn btn-xs btn-outline btn-folder-revoke" data-project-id="${escapeHtml(a.project_id || '')}" style="color:#b91c1c;">Revoke</button>
              ` : ''}
            </div>
          </div>
        `).join('')}
      </div>
    `;

    // Bind actions
    region.querySelectorAll('.btn-folder-open').forEach((btn) => {
      btn.addEventListener('click', async () => {
        try {
          await api.openFolderInExplorer(btn.dataset.projectId);
        } catch (err) {
          alert(`Could not open folder: ${err.message || String(err)}`);
        }
      });
    });

    region.querySelectorAll('.btn-folder-replace').forEach((btn) => {
      btn.addEventListener('click', async () => {
        btn.disabled = true;
        btn.textContent = 'Waiting for dialog…';
        try {
          await ensureSessionToken();
          const sel = await api.selectFolder();
          if (sel && sel.selection_token) {
            await api.replaceFolderApproval(btn.dataset.projectId, sel.selection_token);
          }
          renderProjectIndexView(container, store);
        } catch (err) {
          alert(`Failed to replace folder: ${err.message || String(err)}`);
          btn.disabled = false;
          btn.textContent = 'Replace…';
        }
      });
    });

    region.querySelectorAll('.btn-folder-revoke').forEach((btn) => {
      btn.addEventListener('click', async () => {
        if (!confirm('Revoke folder access? Future scans of this folder will stop. The project and its stored history are preserved.')) return;
        btn.disabled = true;
        try {
          await api.revokeFolderApproval(btn.dataset.projectId);
          renderProjectIndexView(container, store);
        } catch (err) {
          alert(`Failed to revoke access: ${err.message || String(err)}`);
          btn.disabled = false;
        }
      });
    });
  } catch (err) {
    region.innerHTML = `<p class="text-sm text-danger">Failed to load folder approvals: ${escapeHtml(err.message || String(err))}</p>`;
  }
}

/**
 * Renders the Projects Index View listing all active project profiles.
 */
async function renderProjectIndexView(container, store) {
  const reqGen = requestManager.nextGeneration('projects');

  // Shell-first: paint the route header (h1) synchronously before any await so
  // hash transitions resolve quickly; content fills in after the fetch.
  container.innerHTML = `
    <div class="page-header-container">
      <div>
        <span class="eyebrow">Context Intelligence</span>
        <h1>My Projects</h1>
        <p class="lead">HERMES processes local repository source code, configuration, manifests, and documentation to build technology profiles and relevant engineering context.</p>
      </div>
      <div class="page-header-meta" style="display:flex; flex-direction:column; align-items:flex-end; gap:var(--space-2);">
        <div id="projects-refresh-container"></div>
        <div>
          <strong id="projects-active-count">—</strong>
          <span id="projects-active-label">active projects</span>
        </div>
      </div>
    </div>
    <div id="projects-content-region">
      ${renderLoadingState('Loading local engineering projects…')}
    </div>
  `;

  const refreshContainer = container.querySelector('#projects-refresh-container');
  if (refreshContainer) {
    const cleanup = renderSurfaceControls(refreshContainer, {
      scope: 'project_scan',
      onRefresh: () => renderProjectIndexView(container, store),
      syncLabel: 'Sync Data',
    });
    container._viewCleanup = cleanup;
  }

  try {
    const response = await api.getProjects({ params: { active_only: false }, generation: reqGen });
    if (!requestManager.isCurrent('projects', reqGen)) return;

    const projects = ensureArray(response.projects || response);
    store.setViewData('projects', projects);
    store.setConnection('healthy');

    const activeProjects = projects.filter(p => p.is_active);
    const archivedProjects = projects.filter(p => !p.is_active);

    const countEl = container.querySelector('#projects-active-count');
    if (countEl) countEl.textContent = String(activeProjects.length);
    const labelEl = container.querySelector('#projects-active-label');
    if (labelEl) labelEl.textContent = `active project${activeProjects.length === 1 ? '' : 's'}`;

    let html = `
      <div class="privacy-notice" role="note" aria-label="Privacy disclosure" style="margin-bottom:var(--space-5);padding:var(--space-3) var(--space-4);background:var(--bg-panel-subtle);border:1px solid var(--border-subtle);border-radius:var(--radius-md);">
        <p class="text-xs text-muted" style="margin:0;line-height:1.5;">
          <strong>Local Workspace Processing:</strong> HERMES processes supported local source files, configurations, manifests, and documentation, storing extracted text, relative paths, content hashes, derived technology profiles, and local embeddings in your local SQLite database. Sensitive filename patterns (such as <code>.env*</code> and keys) and detected binaries are skipped.
        </p>
      </div>

      <details class="panel" style="margin-bottom:var(--space-5);padding:var(--space-4);" id="add-project-panel">
        <summary style="font-weight:bold;cursor:pointer;user-select:none;">+ Add Local Project</summary>
        <form id="add-project-form" style="margin-top:var(--space-4);display:flex;flex-direction:column;gap:var(--space-3);max-width:560px;">
          <div>
            <label style="display:block;font-size:var(--text-sm);font-weight:bold;margin-bottom:var(--space-1);">Project Folder</label>
            <div style="display:flex;gap:var(--space-2);align-items:center;">
              <button type="button" id="proj-choose-folder" class="btn btn-sm btn-secondary">Choose Folder…</button>
              <output id="proj-path-display" class="mono text-sm" aria-live="polite" style="flex:1;padding:var(--space-2);border:1px solid var(--border-subtle);border-radius:var(--radius-sm);background:var(--bg-panel-subtle);min-height:20px;color:var(--text-muted);">No folder selected</output>
            </div>
            <p class="text-xs text-faint" style="margin-top:var(--space-1);">The folder is chosen through the native Windows dialog. HERMES indexes only the exact folder you approve — never all of Downloads.</p>
          </div>
          <div>
            <label for="proj-name" style="display:block;font-size:var(--text-sm);font-weight:bold;margin-bottom:var(--space-1);">Project Name</label>
            <input type="text" id="proj-name" required placeholder="e.g. My Awesome Web App" class="form-input" style="width:100%;padding:var(--space-2);border:1px solid var(--border-subtle);border-radius:var(--radius-sm);" />
          </div>
          <div>
            <label for="proj-desc" style="display:block;font-size:var(--text-sm);font-weight:bold;margin-bottom:var(--space-1);">Description</label>
            <textarea id="proj-desc" placeholder="e.g. Node/Express backend service" class="form-input" style="width:100%;padding:var(--space-2);border:1px solid var(--border-subtle);border-radius:var(--radius-sm);min-height:60px;"></textarea>
          </div>
          <div id="add-project-error" class="text-sm text-danger" style="display:none;color:var(--danger-color, #dc2626);margin-bottom:var(--space-2);"></div>
          <div>
            <button type="submit" id="proj-submit" class="btn btn-sm btn-primary" disabled>Add & Index Project</button>
          </div>
        </form>
      </details>
    `;

    if (!activeProjects.length) {
      html += renderEmptyState(
        'No Projects Configured',
        'HERMES has not indexed any local repository profiles yet. Add project definitions in your workspace to enable automatic relevance matching.'
      );
    } else {
      html += `
        <h2 class="sr-only">Indexed Projects</h2>
        <div class="grid-3 project-cards-grid">
          ${activeProjects.map((p) => {
            const canonicalId = p.project_id || p.id || '';
            const langs = ensureArray(p.languages);
            const frameworks = ensureArray(p.frameworks);
            const libs = ensureArray(p.libraries);
            const dbs = ensureArray(p.databases);
            const infra = ensureArray(p.infrastructure);
            const models = ensureArray(p.models);
            const tools = ensureArray(p.tools);
            const allChips = [...langs, ...frameworks, ...libs, ...dbs, ...infra, ...models, ...tools].slice(0, 8);
            const matchCount = typeof p.matches_count === 'number' ? p.matches_count : 0;

            return `
              <article class="project-card-item" data-project-id="${escapeHtml(canonicalId)}" aria-labelledby="project-title-${escapeHtml(canonicalId)}">
                <div class="project-card-header" style="display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:var(--space-2);">
                  <span class="mono text-xs text-muted">${escapeHtml(canonicalId)}</span>
                  <span class="badge badge-neutral">Active</span>
                </div>

                <h3 id="project-title-${escapeHtml(canonicalId)}" class="project-card-title" style="margin-top:var(--space-2);font-size:var(--text-md);">
                  <a href="#/projects/${encodeURIComponent(canonicalId)}" class="project-card-link" style="color:var(--ink-primary);text-decoration:none;">
                    ${escapeHtml(p.name)}
                  </a>
                </h3>

                <p class="text-sm text-muted" style="margin-top:var(--space-1);min-height:38px;">
                  ${escapeHtml(p.description || 'Local engineering project profile')}
                </p>

                <div class="chip-group" style="margin-top:var(--space-3);min-height:28px;">
                  ${allChips.map((c) => `<span class="chip">${escapeHtml(c)}</span>`).join('')}
                  ${allChips.length === 0 ? '<span class="text-xs text-faint">No technologies detected</span>' : ''}
                </div>

                <div class="project-card-footer" style="margin-top:var(--space-4);padding-top:var(--space-3);border-top:1px solid var(--border-subtle);display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:var(--space-2);">
                  <span class="mono text-xs text-muted">${matchCount} matched item${matchCount === 1 ? '' : 's'}</span>
                  <span class="mono text-xs text-faint">${p.last_indexed_at ? `Indexed · ${formatDate(p.last_indexed_at)}` : 'Never indexed'}</span>
                </div>
              </article>
            `;
          }).join('')}
        </div>
      `;
    }

    if (archivedProjects.length > 0) {
      html += `
        <section class="archived-projects-section" style="margin-top:var(--space-8);padding-top:var(--space-6);border-top:1px solid var(--border-subtle);">
          <h2 style="font-size:var(--text-lg);margin-bottom:var(--space-3);">Archived Projects</h2>
          <p class="text-sm text-muted" style="margin-bottom:var(--space-4);">
            These projects are archived and excluded from active security/maturity matching.
          </p>
          <div class="grid-3 project-cards-grid">
            ${archivedProjects.map((p) => {
              const canonicalId = p.project_id || p.id || '';
              return `
                <article class="project-card-item archived-card" data-project-id="${escapeHtml(canonicalId)}" aria-labelledby="project-title-${escapeHtml(canonicalId)}" style="opacity: 0.65; cursor: default;">
                  <div class="project-card-header" style="display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:var(--space-2);">
                    <span class="mono text-xs text-muted">${escapeHtml(canonicalId)}</span>
                    <span class="badge badge-subtle">Archived</span>
                  </div>

                  <h3 id="project-title-${escapeHtml(canonicalId)}" class="project-card-title" style="margin-top:var(--space-2);font-size:var(--text-md);">
                    ${escapeHtml(p.name)}
                  </h3>

                  <p class="text-sm text-muted" style="margin-top:var(--space-1);min-height:38px;">
                    ${escapeHtml(p.description || 'Archived project profile')}
                  </p>

                  <div class="project-card-footer" style="margin-top:var(--space-4);padding-top:var(--space-3);border-top:1px solid var(--border-subtle);display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:var(--space-2);">
                    <button type="button" class="btn btn-xs btn-outline btn-restore-project" data-project-id="${escapeHtml(canonicalId)}" style="color:var(--success-color, #16a34a);">
                      Restore
                    </button>
                    <span class="mono text-xs text-faint">${p.last_indexed_at ? `Indexed · ${formatDate(p.last_indexed_at)}` : 'Never'}</span>
                  </div>
                </article>
              `;
            }).join('')}
          </div>
        </section>
      `;
    }

    // Project Folder Access management section (approved roots, revoke,
    // replace, open in Explorer). Filled asynchronously below.
    html += `
      <section class="folder-access-section" style="margin-top:var(--space-8);padding-top:var(--space-6);border-top:1px solid var(--border-subtle);">
        <h2 style="font-size:var(--text-lg);margin-bottom:var(--space-2);">Project Folder Access</h2>
        <p class="text-sm text-muted" style="margin-bottom:var(--space-4);">
          Folders you have explicitly approved for indexing. Revoking access stops future scans but preserves all stored intelligence.
        </p>
        <div id="folder-access-content">${renderLoadingState('Loading approved folders…')}</div>
      </section>
    `;

    const contentRegion = container.querySelector('#projects-content-region');
    if (contentRegion) {
      contentRegion.innerHTML = html;
    } else {
      container.innerHTML = html;
    }

    // Bind add project form: native folder picker + token-based submission.
    const addForm = container.querySelector('#add-project-form');
    if (addForm) {
      let selectionToken = null;

      const chooseBtn = container.querySelector('#proj-choose-folder');
      const pathDisplay = container.querySelector('#proj-path-display');
      const submitBtn = container.querySelector('#proj-submit');
      const nameInput = container.querySelector('#proj-name');
      const errorEl = container.querySelector('#add-project-error');

      const updateSubmitState = () => {
        if (submitBtn) submitBtn.disabled = !(selectionToken && nameInput && nameInput.value.trim());
      };

      if (nameInput) nameInput.addEventListener('input', updateSubmitState);

      if (chooseBtn) {
        chooseBtn.addEventListener('click', async () => {
          if (errorEl) errorEl.style.display = 'none';
          chooseBtn.disabled = true;
          chooseBtn.textContent = 'Waiting for dialog…';
          try {
            await ensureSessionToken();
            const result = await api.selectFolder();
            if (result && result.cancelled) {
              // Clean cancellation: no mutation, keep previous state.
              if (pathDisplay && !selectionToken) pathDisplay.textContent = 'No folder selected';
            } else if (result && result.selection_token) {
              selectionToken = result.selection_token;
              if (pathDisplay) {
                pathDisplay.textContent = result.display_path || result.folder_name || '';
                pathDisplay.style.color = 'var(--ink-primary)';
              }
              // Pre-fill an empty name with the folder name for convenience.
              if (nameInput && !nameInput.value.trim() && result.folder_name) {
                nameInput.value = result.folder_name;
              }
            }
          } catch (err) {
            console.error('Folder selection failed:', err);
            if (errorEl) {
              errorEl.style.display = 'block';
              errorEl.textContent = `Folder selection failed: ${err.message || String(err)}`;
            }
          } finally {
            chooseBtn.disabled = false;
            chooseBtn.textContent = 'Choose Folder…';
            updateSubmitState();
          }
        });
      }

      addForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const name = nameInput ? nameInput.value.trim() : '';
        const description = container.querySelector('#proj-desc').value.trim();

        if (errorEl) errorEl.style.display = 'none';
        if (!selectionToken) {
          if (errorEl) {
            errorEl.style.display = 'block';
            errorEl.textContent = 'Choose a project folder first.';
          }
          return;
        }

        try {
          submitBtn.disabled = true;
          submitBtn.textContent = 'Adding & Scanning...';

          await api.addProject({ name, description, folder_selection_token: selectionToken });
          selectionToken = null;
          renderProjectIndexView(container, store);
        } catch (err) {
          console.error("Failed to add project:", err);
          if (errorEl) {
            errorEl.style.display = 'block';
            errorEl.textContent = `Error: ${err.message || String(err)}`;
          }
          // Token is single-use: force a fresh selection on retry.
          selectionToken = null;
          if (pathDisplay) {
            pathDisplay.textContent = 'No folder selected';
            pathDisplay.style.color = 'var(--text-muted)';
          }
          submitBtn.disabled = true;
          submitBtn.textContent = 'Add & Index Project';
        }
      });
    }

    // Make active project cards keyboard and click operable
    container.querySelectorAll('.project-card-item:not(.archived-card)').forEach((card) => {
      const pId = card.getAttribute('data-project-id');
      if (!pId) return;

      const navigateToProject = () => {
        window.location.hash = `#/projects/${encodeURIComponent(pId)}`;
      };

      card.addEventListener('click', (e) => {
        if (e.target.closest('a') || e.target.closest('button')) return;
        navigateToProject();
      });

      card.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          navigateToProject();
        }
      });
    });

    // Bind restore button click delegation
    container.querySelectorAll('.btn-restore-project').forEach((restoreBtn) => {
      restoreBtn.addEventListener('click', async (e) => {
        e.preventDefault();
        e.stopPropagation();

        const pId = restoreBtn.dataset.projectId;
        if (!pId) return;

        restoreBtn.disabled = true;
        restoreBtn.textContent = 'Restoring...';

        try {
          await api.restoreProject(pId);
          renderProjectIndexView(container, store);
        } catch (err) {
          console.error("Failed to restore project:", err);
          alert(`Failed to restore project: ${err.message || String(err)}`);
          restoreBtn.disabled = false;
          restoreBtn.textContent = 'Restore';
        }
      });
    });

    // Load the Project Folder Access section asynchronously.
    renderFolderAccessSection(container, store);

  } catch (err) {
    if (!requestManager.isCurrent('projects', reqGen) || (err && err.isAborted && !err.isTimeout)) return;

    const contentRegion = container.querySelector('#projects-content-region');
    if (err.isNetworkError) {
      store.setConnection('offline', err.message);
      const offlineHtml = renderOfflineState(() => renderProjectIndexView(container, store), err.message);
      if (contentRegion) contentRegion.innerHTML = offlineHtml;
      else container.innerHTML = offlineHtml;
    } else {
      store.setConnection('degraded', err.message);
      const errorHtml = renderErrorState(
        'Failed to Load Projects',
        err.message,
        `<button class="btn btn-secondary" onclick="window.location.reload()">Retry</button>`
      );
      if (contentRegion) contentRegion.innerHTML = errorHtml;
      else container.innerHTML = errorHtml;
    }
  }
}

/**
 * Renders the Deep Project Detail View with technology profile, story matches,
 * engineering concerns, recent changes, and cross-surface navigation.
 */
async function renderProjectDetailView(container, store, projectId) {
  const reqGen = requestManager.nextGeneration('projects');
  container.innerHTML = renderLoadingState(`Loading intelligence for ${projectId}…`);

  try {
    const intel = await api.getProjectIntelligence(projectId, {}, { generation: reqGen });
    if (!requestManager.isCurrent('projects', reqGen)) return;

    if (!intel) {
      container.innerHTML = renderErrorState(
        'Project Not Found',
        `Project "${escapeHtml(projectId)}" was not found in the indexed repository database.`,
        `<a href="#/projects" class="btn btn-secondary">← Back to Projects</a>`
      );
      return;
    }

    store.setViewData(`project_${projectId}`, intel);
    store.setConnection('healthy');

    const canonicalId = intel.project_id || projectId;
    const name = intel.name || canonicalId;
    const desc = intel.description || 'Local engineering project profile';
    const isActive = intel.is_active !== false;
    const lastIndexed = intel.last_indexed_at;
    const narrative = intel.narrative || null;
    const techProf = intel.technology_profile || {};
    const topMatches = ensureArray(intel.top_matches);
    const risks = ensureArray(intel.risks);
    const changes = ensureArray(intel.recent_changes);
    const intelAvailable = intel.intelligence_available !== false;

    // Technology categories
    const categories = [
      { key: 'languages', label: 'Languages', items: ensureArray(techProf.languages) },
      { key: 'frameworks', label: 'Frameworks', items: ensureArray(techProf.frameworks) },
      { key: 'libraries', label: 'Libraries', items: ensureArray(techProf.libraries) },
      { key: 'databases', label: 'Databases', items: ensureArray(techProf.databases) },
      { key: 'infrastructure', label: 'Infrastructure', items: ensureArray(techProf.infrastructure) },
      { key: 'models', label: 'Models', items: ensureArray(techProf.models) },
      { key: 'tools', label: 'Tools', items: ensureArray(techProf.tools) },
      { key: 'topics', label: 'Topics', items: ensureArray(techProf.topics) },
      { key: 'keywords', label: 'Keywords', items: ensureArray(techProf.keywords) },
    ];
    const populatedCategories = categories.filter((c) => c.items.length > 0);

    let html = `
      <nav class="breadcrumb-nav" style="margin-bottom:var(--space-4);">
        <a href="#/projects" class="btn-ghost text-xs" style="display:inline-flex;align-items:center;gap:var(--space-1);color:var(--ink-secondary);text-decoration:none;">
          ← Back to Projects
        </a>
      </nav>

      <header class="project-detail-header" style="margin-bottom:var(--space-6);padding-bottom:var(--space-5);border-bottom:1px solid var(--border-subtle);">
        <div style="display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:var(--space-3);">
          <div>
            <div style="display:flex;align-items:center;gap:var(--space-2);margin-bottom:var(--space-1);">
              <span class="eyebrow">Project Intelligence</span>
              <span class="badge ${isActive ? 'badge-neutral' : 'badge-warning'}">${isActive ? 'Active Profile' : 'Inactive Profile'}</span>
            </div>
            <h1 style="font-size:var(--text-xl);margin:0 0 var(--space-2) 0;">${escapeHtml(name)}</h1>
            <span class="mono text-xs text-muted" style="display:inline-block;margin-bottom:var(--space-2);">${escapeHtml(canonicalId)}</span>
            <p class="lead" style="margin:0 0 var(--space-3) 0;max-width:720px;">${escapeHtml(desc)}</p>
          </div>

          <div class="project-header-meta" style="text-align:right;">
            <div id="project-detail-refresh-container" style="margin-bottom:var(--space-2);"></div>
            <div class="mono text-xs text-muted">${lastIndexed ? `Indexed · ${formatDate(lastIndexed)}` : 'Never indexed'}</div>
            <div class="mono text-xs text-faint" style="margin-top:var(--space-1);">${topMatches.length} matched intelligence items</div>
          </div>
        </div>

        <!-- Cross-Surface Quick Navigation Bar -->
        <div class="project-cross-nav" style="margin-top:var(--space-4);display:flex;flex-wrap:wrap;gap:var(--space-2);align-items:center;">
          <a href="#/today?project=${encodeURIComponent(canonicalId)}" class="btn btn-sm btn-secondary">
            Open in Today Inbox →
          </a>
          <a href="#/search?project=${encodeURIComponent(canonicalId)}" class="btn btn-sm btn-secondary">
            Search Project Context →
          </a>
          <a href="#/changes?project=${encodeURIComponent(canonicalId)}" class="btn btn-sm btn-secondary">
            View Project Changes →
          </a>

          <!-- Scan Button -->
          ${isActive ? `
            <button type="button" class="btn btn-sm btn-outline btn-scan-project" data-project-id="${escapeHtml(canonicalId)}">
              Rescan Project
            </button>
            <button type="button" class="btn btn-sm btn-ghost btn-archive-project" data-project-id="${escapeHtml(canonicalId)}" style="color:var(--danger-color, #dc2626);">
              Archive Project
            </button>
          ` : `
            <button type="button" class="btn btn-sm btn-ghost btn-restore-project" data-project-id="${escapeHtml(canonicalId)}" style="color:var(--success-color, #16a34a);">
              Restore Project
            </button>
          `}
        </div>
      </header>

      <!-- 1. Structured Project Narrative Overview (what it does) -->
      ${renderNarrativeSection(narrative)}

      <!-- 2. Structured Technology Profile -->
      <section class="project-section" style="margin-bottom:var(--space-6);">
        <h2 style="font-size:var(--text-lg);margin-bottom:var(--space-2);">Detected Technology Profile</h2>
        <p class="text-sm text-muted" style="margin-bottom:var(--space-4);">
          Structured engineering technologies, frameworks, dependencies, and keywords detected from project manifests.
        </p>

        ${
          populatedCategories.length === 0
            ? '<p class="text-sm text-muted">No technology categories detected for this project profile.</p>'
            : `
              <div class="grid-3 technology-categories-grid" style="gap:var(--space-3);">
                ${populatedCategories.map((cat) => `
                  <div class="tech-category-card" style="padding:var(--space-3) var(--space-4);background:var(--bg-panel);border:1px solid var(--border-subtle);border-radius:var(--radius-md);">
                    <div class="mono text-xs text-faint" style="text-transform:uppercase;letter-spacing:0.05em;margin-bottom:var(--space-2);">${escapeHtml(cat.label)} (${cat.items.length})</div>
                    <div class="chip-group" style="margin-top:0;">
                      ${cat.items.map((it) => `<span class="chip">${escapeHtml(it)}</span>`).join('')}
                    </div>
                  </div>
                `).join('')}
              </div>
            `
        }
      </section>

      <!-- 3. Potential Engineering Concerns (severity-oriented) -->
      <section class="project-section" style="margin-bottom:var(--space-6);">
        <div style="display:flex;justify-content:space-between;align-items:baseline;flex-wrap:wrap;gap:var(--space-2);margin-bottom:var(--space-2);">
          <h2 style="font-size:var(--text-lg);margin:0;">Potential Engineering Concerns</h2>
          <span class="mono text-xs text-muted">${risks.length} detected</span>
        </div>
        <p class="text-sm text-muted" style="margin-bottom:var(--space-4);">
          Vulnerabilities, breaking changes, deprecations, incompatible dependencies, removed features,
          operational incompatibilities, evidence-backed regressions, and verified canonical risks.
          High impact score alone is never treated as a concern.
        </p>

        ${
          risks.length === 0
            ? '<div class="empty-sub-section" style="padding:var(--space-4);background:var(--bg-panel-subtle);border:1px solid var(--border-subtle);border-radius:var(--radius-md);"><p class="text-sm text-muted" style="margin:0;">No verified engineering concerns detected for this project profile.</p></div>'
            : `
              <div class="concerns-list" style="display:flex;flex-direction:column;gap:var(--space-3);">
                ${risks.map((r) => renderConcernCard(r, canonicalId)).join('')}
              </div>
            `
        }
      </section>

      <!-- 4. Relevant Intelligence Story Matches (explained) -->
      <section class="project-section" style="margin-bottom:var(--space-6);">
        <div style="display:flex;justify-content:space-between;align-items:baseline;flex-wrap:wrap;gap:var(--space-2);margin-bottom:var(--space-2);">
          <h2 style="font-size:var(--text-lg);margin:0;">Relevant Intelligence Matches</h2>
          <span class="mono text-xs text-muted">${topMatches.length} matches</span>
        </div>
        <p class="text-sm text-muted" style="margin-bottom:var(--space-4);">
          Current intelligence stories matching this project's technology stack and engineering context,
          each with a grounded explanation of why it was matched.
        </p>

        ${
          topMatches.length === 0
            ? '<div class="empty-sub-section" style="padding:var(--space-4);background:var(--bg-panel-subtle);border:1px solid var(--border-subtle);border-radius:var(--radius-md);"><p class="text-sm text-muted" style="margin:0;">No intelligence matches currently recorded for this project profile.</p></div>'
            : `
              <div class="matches-list" style="display:flex;flex-direction:column;gap:var(--space-3);">
                ${topMatches.map((m) => renderExplainedMatchCard(m, canonicalId)).join('')}
              </div>
            `
        }
      </section>

      <!-- Recent Project Changes -->
      <section class="project-section" style="margin-bottom:var(--space-6);">
        <div style="display:flex;justify-content:space-between;align-items:baseline;flex-wrap:wrap;gap:var(--space-2);margin-bottom:var(--space-2);">
          <h2 style="font-size:var(--text-lg);margin:0;">Recent Project Changes</h2>
          <span class="mono text-xs text-muted">${changes.length} past 7d</span>
        </div>
        <p class="text-sm text-muted" style="margin-bottom:var(--space-4);">
          State transitions and intelligence updates in matching technologies over the past 7 days.
        </p>

        ${
          changes.length === 0
            ? '<div class="empty-sub-section" style="padding:var(--space-4);background:var(--bg-panel-subtle);border:1px solid var(--border-subtle);border-radius:var(--radius-md);"><p class="text-sm text-muted" style="margin:0;">No recent technology changes detected for this project profile in the last 7 days.</p></div>'
            : `
              <div class="changes-list" style="display:flex;flex-direction:column;gap:var(--space-3);">
                ${changes.map((ch) => {
                  const detected = ch.detected_at || ch.created_at;
                  const origin = ch.origin || 'system';
                  const importance = ch.importance_level || ch.importance || 'medium';

                  return `
                    <div class="change-card" style="padding:var(--space-4);background:var(--bg-panel);border:1px solid var(--border-subtle);border-radius:var(--radius-md);">
                      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:var(--space-2);">
                        <div style="display:flex;gap:var(--space-2);align-items:center;">
                          <span class="origin-pill origin-${escapeHtml(origin)} text-xs mono">${escapeHtml(origin)}</span>
                          <span class="badge badge-${escapeHtml(importance)}">${escapeHtml(importance)}</span>
                        </div>
                        <span class="mono text-xs text-faint">${detected ? formatDate(detected) : ''}</span>
                      </div>

                      ${ch.old_value && ch.new_value ? `
                        <div class="transition-row" style="margin-bottom:var(--space-2);padding:var(--space-2);background:var(--bg-panel-subtle);border-radius:var(--radius-sm);font-family:var(--font-mono);font-size:var(--text-xs);">
                          <span style="color:var(--danger);">${escapeHtml(ch.old_value)}</span>
                          <span style="margin:0 var(--space-2);">→</span>
                          <span style="color:var(--success);font-weight:600;">${escapeHtml(ch.new_value)}</span>
                        </div>
                      ` : ''}

                      <p class="text-sm" style="margin:0 0 var(--space-2) 0;">${escapeHtml(ch.description || '')}</p>

                      ${ch.cluster_id ? `
                        <div style="margin-top:var(--space-2);">
                          <a href="#/story/${encodeURIComponent(ch.cluster_id)}" class="mono text-xs" data-testid="projects-change-link-${escapeHtml(ch.cluster_id)}" style="color:var(--accent-primary);text-decoration:none;">
                            View Story Dossier →
                          </a>
                        </div>
                      ` : ''}
                    </div>
                  `;
                }).join('')}
              </div>
            `
        }
      </section>

      <!-- Truthful Empty Intelligence State -->
      ${
        !intelAvailable && topMatches.length === 0 && risks.length === 0 && changes.length === 0
          ? `
            <div class="empty-intelligence-banner" style="margin-top:var(--space-6);padding:var(--space-5);background:var(--bg-panel-subtle);border:1px dashed var(--border-strong);border-radius:var(--radius-lg);text-align:center;">
              <h3 style="margin:0 0 var(--space-2) 0;font-size:var(--text-md);">No Project Intelligence Recorded Yet</h3>
              <p class="text-sm text-muted" style="margin:0;max-width:540px;display:inline-block;">
                No matching intelligence items, engineering concerns, or recent changes are currently recorded for this project profile. As HERMES ingests developments matching its detected technologies, they will automatically appear here.
              </p>
            </div>
          `
          : ''
      }
    `;

    container.innerHTML = html;

    const refreshContainer = container.querySelector('#project-detail-refresh-container');
    if (refreshContainer) {
      const cleanup = renderSurfaceControls(refreshContainer, {
        scope: 'project_scan',
        targetId: canonicalId,
        onRefresh: () => renderProjectDetailView(container, store, canonicalId),
        syncLabel: 'Sync Data',
      });
      container._viewCleanup = cleanup;
    }

    const scanBtn = container.querySelector('.btn-scan-project');
    const archiveBtn = container.querySelector('.btn-archive-project');
    const restoreBtn = container.querySelector('.btn-restore-project');

    if (scanBtn) {
      scanBtn.addEventListener('click', async () => {
        const pId = scanBtn.dataset.projectId;
        if (!pId) return;

        scanBtn.disabled = true;
        scanBtn.textContent = 'Scanning...';
        try {
          await api.scanProject(pId);
          renderProjectDetailView(container, store, pId);
        } catch (err) {
          console.error("Failed to scan project:", err);
          alert(`Failed to scan project: ${err.message || String(err)}`);
          scanBtn.disabled = false;
          scanBtn.textContent = 'Rescan Project';
        }
      });
    }

    if (archiveBtn) {
      archiveBtn.addEventListener('click', async () => {
        const pId = archiveBtn.dataset.projectId;
        if (!pId) return;

        const confirmed = window.confirm("Are you sure you want to soft-archive this project? It will be excluded from active scans and matches.");
        if (!confirmed) return;

        archiveBtn.disabled = true;
        archiveBtn.textContent = 'Archiving...';
        try {
          await api.archiveProject(pId);
          renderProjectDetailView(container, store, pId);
        } catch (err) {
          console.error("Failed to archive project:", err);
          alert(`Failed to archive project: ${err.message || String(err)}`);
          archiveBtn.disabled = false;
          archiveBtn.textContent = 'Archive Project';
        }
      });
    }

    if (restoreBtn) {
      restoreBtn.addEventListener('click', async () => {
        const pId = restoreBtn.dataset.projectId;
        if (!pId) return;

        restoreBtn.disabled = true;
        restoreBtn.textContent = 'Restoring...';
        try {
          await api.restoreProject(pId);
          renderProjectDetailView(container, store, pId);
        } catch (err) {
          console.error("Failed to restore project:", err);
          alert(`Failed to restore project: ${err.message || String(err)}`);
          restoreBtn.disabled = false;
          restoreBtn.textContent = 'Restore Project';
        }
      });
    }

  } catch (err) {
    if (!requestManager.isCurrent('projects', reqGen) || (err && err.isAborted && !err.isTimeout)) return;

    if (err.status === 404) {
      container.innerHTML = `
        <nav class="breadcrumb-nav" style="margin-bottom:var(--space-4);">
          <a href="#/projects" class="btn-ghost text-xs" style="display:inline-flex;align-items:center;gap:var(--space-1);color:var(--ink-secondary);text-decoration:none;">
            ← Back to Projects
          </a>
        </nav>
        ${renderErrorState(
          'Project Not Found',
          `Project "${escapeHtml(projectId)}" was not found in the indexed repository database.`
        )}
      `;
    } else if (err.isNetworkError) {
      store.setConnection('offline', err.message);
      container.innerHTML = renderOfflineState(() => renderProjectDetailView(container, store, projectId), err.message);
    } else {
      store.setConnection('degraded', err.message);
      container.innerHTML = renderErrorState(
        'Failed to Load Project Intelligence',
        err.message
      );
    }
  }
}
