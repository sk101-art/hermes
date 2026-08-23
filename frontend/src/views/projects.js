/**
 * HERMES My Projects View
 * Local engineering context profiles and dependency match intelligence.
 * Supports Index View (#/projects) and Deep Detail View (#/projects/{project_id}).
 */

import { api } from '../api/endpoints.js';
import { renderLoadingState, renderEmptyState, renderErrorState, renderOfflineState } from '../components/ui-states.js';
import { escapeHtml, formatDate, ensureArray } from '../utils/adapters.js';
import {
  renderProjectRelevanceBadge,
  renderProjectImpactBadge,
} from '../components/badges.js';

let currentProjectRequestToken = 0;

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
 * Format reason code into human-readable chip text.
 */
function formatReasonCode(code) {
  if (!code) return '';
  const clean = String(code).trim().toLowerCase();
  const map = {
    direct_dependency_match: 'Direct Dependency',
    technology_overlap: 'Technology Overlap',
    framework_match: 'Framework Match',
    language_match: 'Language Match',
    database_match: 'Database Match',
    infrastructure_match: 'Infrastructure Match',
    model_match: 'Model Match',
    topic_match: 'Topic Match',
    keyword_match: 'Keyword Match',
    high_impact: 'High Impact',
    breaking_change: 'Breaking Change',
    security_vulnerability: 'Security Vulnerability',
    deprecation_warning: 'Deprecation',
  };
  if (map[clean]) return map[clean];
  return clean.split('_').map((w) => w.charAt(0).toUpperCase() + w.slice(1)).join(' ');
}

/**
 * Format heuristic recommendation token cautiously as advisory note.
 */
function formatAdvisory(rec) {
  if (!rec) return '';
  const clean = String(rec).trim().toLowerCase();
  const map = {
    potential_risk: 'Potential Risk — Investigate impact on current project implementation.',
    upgrade_candidate: 'Upgrade Candidate — New release or major improvements available.',
    optimization_candidate: 'Optimization Candidate — Potential performance or efficiency gains.',
    consider: 'Consider — Relevant tool or technique for evaluation.',
    evaluate: 'Evaluate — Assess compatibility with project architecture.',
    watch: 'Watch — Emerging technology in project ecosystem.',
    not_recommended_yet: 'Not Recommended Yet — Early stage or unverified stability.',
  };
  if (map[clean]) return map[clean];
  const humanized = clean.replace(/_/g, ' ');
  return `${humanized.charAt(0).toUpperCase() + humanized.slice(1)}`;
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
 * Renders the Projects Index View listing all active project profiles.
 */
async function renderProjectIndexView(container, store) {
  const thisToken = ++currentProjectRequestToken;
  container.innerHTML = renderLoadingState('Loading local engineering projects…');

  try {
    const response = await api.getProjects();
    if (thisToken !== currentProjectRequestToken) return;

    const projects = ensureArray(response.projects || response);
    store.setViewData('projects', projects);
    store.setConnection('healthy');

    let html = `
      <div class="page-header-container">
        <div>
          <span class="eyebrow">Context Intelligence</span>
          <h1>My Projects</h1>
          <p class="lead">HERMES processes local repository source code, configuration, manifests, and documentation to build technology profiles and relevant engineering context.</p>
        </div>
        <div class="page-header-meta">
          <strong>${projects.length}</strong>
          <span>indexed project${projects.length === 1 ? '' : 's'}</span>
        </div>
      </div>

      <div class="privacy-notice" role="note" aria-label="Privacy disclosure" style="margin-bottom:var(--space-5);padding:var(--space-3) var(--space-4);background:var(--bg-panel-subtle);border:1px solid var(--border-subtle);border-radius:var(--radius-md);">
        <p class="text-xs text-muted" style="margin:0;line-height:1.5;">
          <strong>Local Workspace Processing:</strong> HERMES processes supported local source files, configurations, manifests, and documentation, storing extracted text, relative paths, content hashes, derived technology profiles, and local embeddings in your local SQLite database. Sensitive filename patterns (such as <code>.env*</code> and keys) and detected binaries are skipped.
        </p>
      </div>
    `;

    if (!projects.length) {
      html += renderEmptyState(
        'No Projects Configured',
        'HERMES has not indexed any local repository profiles yet. Add project definitions in your workspace to enable automatic relevance matching.'
      );
    } else {
      html += `
        <h2 class="sr-only">Indexed Projects</h2>
        <div class="grid-3 project-cards-grid">
          ${projects.map((p) => {
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
                <div class="project-card-header" style="display:flex;justify-content:space-between;align-items:flex-start;gap:var(--space-2);">
                  <span class="mono text-xs text-muted">${escapeHtml(canonicalId)}</span>
                  <span class="badge ${p.is_active ? 'badge-neutral' : 'badge-subtle'}">${p.is_active ? 'Active' : 'Inactive'}</span>
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

                <div class="project-card-footer" style="margin-top:var(--space-4);padding-top:var(--space-3);border-top:1px solid var(--border-subtle);display:flex;justify-content:space-between;align-items:center;">
                  <span class="mono text-xs text-muted">${matchCount} matched item${matchCount === 1 ? '' : 's'}</span>
                  <span class="mono text-xs text-faint">${p.last_indexed_at ? `Indexed · ${formatDate(p.last_indexed_at)}` : 'Never indexed'}</span>
                </div>
              </article>
            `;
          }).join('')}
        </div>
      `;
    }

    container.innerHTML = html;

    // Make project cards keyboard and click operable
    container.querySelectorAll('.project-card-item').forEach((card) => {
      const pId = card.getAttribute('data-project-id');
      if (!pId) return;

      const navigateToProject = () => {
        window.location.hash = `#/projects/${encodeURIComponent(pId)}`;
      };

      card.addEventListener('click', (e) => {
        if (e.target.closest('a')) return;
        navigateToProject();
      });

      card.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          navigateToProject();
        }
      });
    });

  } catch (err) {
    if (thisToken !== currentProjectRequestToken) return;

    if (err.isNetworkError) {
      store.setConnection('offline', err.message);
      container.innerHTML = renderOfflineState(() => renderProjectIndexView(container, store), err.message);
    } else {
      store.setConnection('degraded', err.message);
      container.innerHTML = renderErrorState(
        'Failed to Load Projects',
        err.message,
        `<button class="btn btn-secondary" onclick="window.location.reload()">Retry</button>`
      );
    }
  }
}

/**
 * Renders the Deep Project Detail View with technology profile, story matches,
 * engineering concerns, recent changes, and cross-surface navigation.
 */
async function renderProjectDetailView(container, store, projectId) {
  const thisToken = ++currentProjectRequestToken;
  container.innerHTML = renderLoadingState(`Loading intelligence for ${projectId}…`);

  try {
    const intel = await api.getProjectIntelligence(projectId);
    if (thisToken !== currentProjectRequestToken) return;

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
            <div class="mono text-xs text-muted">${lastIndexed ? `Indexed · ${formatDate(lastIndexed)}` : 'Never indexed'}</div>
            <div class="mono text-xs text-faint" style="margin-top:var(--space-1);">${topMatches.length} matched intelligence items</div>
          </div>
        </div>

        <!-- Cross-Surface Quick Navigation Bar -->
        <div class="project-cross-nav" style="margin-top:var(--space-4);display:flex;flex-wrap:wrap;gap:var(--space-2);">
          <a href="#/today?project=${encodeURIComponent(canonicalId)}" class="btn btn-sm btn-secondary">
            Open in Today Inbox →
          </a>
          <a href="#/search?project=${encodeURIComponent(canonicalId)}" class="btn btn-sm btn-secondary">
            Search Project Context →
          </a>
          <a href="#/changes?project=${encodeURIComponent(canonicalId)}" class="btn btn-sm btn-secondary">
            View Project Changes →
          </a>
        </div>
      </header>

      <!-- Structured Technology Profile -->
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

      <!-- Potential Engineering Concerns -->
      <section class="project-section" style="margin-bottom:var(--space-6);">
        <div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:var(--space-2);">
          <h2 style="font-size:var(--text-lg);margin:0;">Potential Engineering Concerns</h2>
          <span class="mono text-xs text-muted">${risks.length} detected</span>
        </div>
        <p class="text-sm text-muted" style="margin-bottom:var(--space-4);">
          Deprecations, breaking changes, vulnerabilities, canonical assessed risks, and high-impact changes affecting this project.
        </p>

        ${
          risks.length === 0
            ? '<div class="empty-sub-section" style="padding:var(--space-4);background:var(--bg-panel-subtle);border:1px solid var(--border-subtle);border-radius:var(--radius-md);"><p class="text-sm text-muted" style="margin:0;">No high-risk concerns or breaking changes detected for this project profile.</p></div>'
            : `
              <div class="concerns-list" style="display:flex;flex-direction:column;gap:var(--space-3);">
                ${risks.map((r) => {
                  const concernType = r.concern_type || 'high_project_impact';
                  let badgeHtml = '<span class="badge badge-primary">High Project Impact</span>';
                  if (concernType === 'vulnerability') {
                    badgeHtml = '<span class="badge badge-danger">Vulnerability</span>';
                  } else if (concernType === 'breaking_change') {
                    badgeHtml = '<span class="badge badge-warning">Breaking Change</span>';
                  } else if (concernType === 'deprecation') {
                    badgeHtml = '<span class="badge badge-neutral">Deprecation</span>';
                  } else if (concernType === 'assessed_risk') {
                    badgeHtml = `<span class="badge badge-danger">Assessed Risk · ${escapeHtml(r.risk_level || 'high')}</span>`;
                  }

                  const titleHtml = r.story_available && r.cluster_id
                    ? `<a href="#/story/${encodeURIComponent(r.cluster_id)}" class="concern-title-link" data-testid="projects-concern-link-${escapeHtml(r.cluster_id)}" style="color:var(--ink-primary);font-weight:600;text-decoration:none;">${escapeHtml(r.title)}</a>`
                    : `<span style="font-weight:600;">${escapeHtml(r.title)}</span> <span class="badge badge-subtle">Story unavailable</span>`;

                  return `
                    <div class="concern-card" style="padding:var(--space-4);background:var(--bg-panel);border:1px solid var(--border-subtle);border-radius:var(--radius-md);">
                      <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:var(--space-2);margin-bottom:var(--space-2);">
                        <div>${badgeHtml}</div>
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

                      ${r.recommendation ? `
                        <div class="advisory-box" style="margin-top:var(--space-2);padding:var(--space-2) var(--space-3);background:var(--bg-panel-subtle);border-radius:var(--radius-sm);border-left:3px solid var(--accent-primary);">
                          <span class="advisory-label text-xs" style="font-weight:600;color:var(--ink-secondary);">Advisory Context:</span>
                          <span class="advisory-text text-xs text-muted">${escapeHtml(formatAdvisory(r.recommendation))}</span>
                        </div>
                      ` : ''}
                    </div>
                  `;
                }).join('')}
              </div>
            `
        }
      </section>

      <!-- Relevant Intelligence Story Matches -->
      <section class="project-section" style="margin-bottom:var(--space-6);">
        <div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:var(--space-2);">
          <h2 style="font-size:var(--text-lg);margin:0;">Relevant Intelligence Matches</h2>
          <span class="mono text-xs text-muted">${topMatches.length} matches</span>
        </div>
        <p class="text-sm text-muted" style="margin-bottom:var(--space-4);">
          Current intelligence stories matching this project's technology stack and engineering context.
        </p>

        ${
          topMatches.length === 0
            ? '<div class="empty-sub-section" style="padding:var(--space-4);background:var(--bg-panel-subtle);border:1px solid var(--border-subtle);border-radius:var(--radius-md);"><p class="text-sm text-muted" style="margin:0;">No intelligence matches currently recorded for this project profile.</p></div>'
            : `
              <div class="matches-list" style="display:flex;flex-direction:column;gap:var(--space-3);">
                ${topMatches.map((m) => {
                  const titleHtml = m.story_available && m.cluster_id
                    ? `<a href="#/story/${encodeURIComponent(m.cluster_id)}" class="match-title-link" data-testid="projects-match-link-${escapeHtml(m.cluster_id)}" style="color:var(--ink-primary);font-weight:600;text-decoration:none;">${escapeHtml(m.title)}</a>`
                    : `<span style="font-weight:600;">${escapeHtml(m.title)}</span> <span class="badge badge-subtle">Story unavailable</span>`;

                  const reasons = ensureArray(m.reason_codes);

                  return `
                    <div class="match-card" style="padding:var(--space-4);background:var(--bg-panel);border:1px solid var(--border-subtle);border-radius:var(--radius-md);">
                      <div style="display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:var(--space-2);margin-bottom:var(--space-2);">
                        <span class="chip match-type-chip" style="font-weight:500;">${escapeHtml(formatMatchType(m.match_type))}</span>
                        <div style="display:flex;gap:var(--space-2);align-items:center;">
                          ${renderProjectRelevanceBadge(m.relevance_score)}
                          ${renderProjectImpactBadge(m.impact_score)}
                        </div>
                      </div>

                      <h3 class="match-title" style="margin:0 0 var(--space-2) 0;font-size:var(--text-md);font-weight:inherit;">${titleHtml}</h3>

                      ${reasons.length > 0 ? `
                        <div class="chip-group" style="margin-top:var(--space-2);margin-bottom:var(--space-2);">
                          ${reasons.map((r) => `<span class="chip chip-reason text-xs" data-reason-code="${escapeHtml(r)}">${escapeHtml(formatReasonCode(r))}</span>`).join('')}
                        </div>
                      ` : ''}

                      ${m.recommendation ? `
                        <div class="advisory-box" style="margin-top:var(--space-2);padding:var(--space-2) var(--space-3);background:var(--bg-panel-subtle);border-radius:var(--radius-sm);border-left:3px solid var(--border-strong);">
                          <span class="advisory-label text-xs" style="font-weight:600;color:var(--ink-secondary);">Advisory Context:</span>
                          <span class="advisory-text text-xs text-muted">${escapeHtml(formatAdvisory(m.recommendation))}</span>
                        </div>
                      ` : ''}
                    </div>
                  `;
                }).join('')}
              </div>
            `
        }
      </section>

      <!-- Recent Project Changes -->
      <section class="project-section" style="margin-bottom:var(--space-6);">
        <div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:var(--space-2);">
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

  } catch (err) {
    if (thisToken !== currentProjectRequestToken) return;

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
