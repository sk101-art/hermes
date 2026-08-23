/**
 * HERMES Story Dossier & Evidence Investigation Experience
 * Primary investigation surface providing deep grounded intelligence:
 * What Happened, Why It Matters, Evidence Position, Atomic Claims,
 * Progressive Evidence Provenance, Technology Maturity, and Project Relevance.
 * 
 * Strict Truthfulness Guarantee:
 * - cluster_score is labeled Discovery / Relevance, NEVER Confidence or Verification.
 * - Missing synthesis fields produce no fabricated filler.
 * - Progressive loading fetches GET /claims/{id} on-demand and caches per session.
 * - Self-reported origin and evidence independence remain separate dimensions.
 * - Real external URLs only; no guessed links.
 */

import { api } from '../api/endpoints.js';
import { getIcon } from '../icons/index.js';
import {
  renderVerificationBadge,
  renderMaturityBadge,
  renderRiskBadge,
  renderEvidenceStanceBadge,
  renderClusterScoreBadge,
  renderSourcePill,
  renderProjectRelevanceBadge,
  renderProjectImpactBadge,
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
  formatScorePercentage,
} from '../utils/adapters.js';

// In-memory session cache for progressive ClaimDetail objects
const dossierClaimCache = new Map();

/**
 * Render interactive grounding reference pills.
 * @param {Array<{entity_type: string, entity_id: string}>} refs 
 * @returns {string} HTML string
 */
export function renderGroundingReferences(refs) {
  const safeRefs = ensureArray(refs);
  if (!safeRefs.length) return '';

  return `<div class="grounding-refs-list" role="group" aria-label="Grounded provenance references">
    <span class="mono text-xs text-muted" style="margin-right:2px;">Grounding:</span>
    ${safeRefs.map((ref) => {
      const type = ref.entity_type || 'entity';
      const id = ref.entity_id || '';
      let pillClass = 'provenance-pill';
      let icon = 'link';
      let typeLabel = type.replace(/[_-]/g, ' ');

      if (type === 'event') {
        pillClass += ' provenance-pill-event';
        icon = 'fileText';
        typeLabel = 'Event';
      } else if (type === 'claim') {
        pillClass += ' provenance-pill-claim';
        icon = 'checkCircle';
        typeLabel = 'Claim';
      } else if (type === 'evidence') {
        pillClass += ' provenance-pill-evidence';
        icon = 'link';
        typeLabel = 'Evidence';
      } else if (type === 'assessment') {
        pillClass += ' provenance-pill-assessment';
        icon = 'layers';
        typeLabel = 'Assessment';
      } else if (type === 'project_match') {
        pillClass += ' provenance-pill-project';
        icon = 'folder';
        typeLabel = 'Project';
      } else if (type === 'change') {
        pillClass += ' provenance-pill-change';
        icon = 'clock';
        typeLabel = 'Change';
      }

      return `<button type="button" class="${pillClass}" 
                data-action="focus-grounding" 
                data-entity-type="${escapeHtml(type)}" 
                data-entity-id="${escapeHtml(id)}"
                aria-label="Focus grounded ${escapeHtml(typeLabel)}: ${escapeHtml(id)}"
                title="Inspect grounding ${escapeHtml(typeLabel)} (${escapeHtml(id)})">
        <span class="icon-inline">${getIcon(icon)}</span>
        <span>${escapeHtml(typeLabel)}: ${escapeHtml(id)}</span>
      </button>`;
    }).join('')}
  </div>`;
}

/**
 * Render single evidence card within expanded claim.
 * @param {object} ev 
 * @returns {string} HTML string
 */
export function renderEvidenceItem(ev) {
  const source = ev.source || 'Unknown source';
  const stance = ev.stance || 'context';
  const isReproduction = ev.evidence_type === 'independent_reproduction';
  const isIndependent = Boolean(ev.is_independent);
  const excerpt = ev.excerpt || ev.text || null;
  const url = ev.url && typeof ev.url === 'string' && ev.url.trim().startsWith('http') ? ev.url.trim() : null;
  const observedDate = formatDate(ev.observed_at || ev.created_at);

  let indPill = '';
  if (isReproduction) {
    indPill = `<span class="pill-reproduction" title="Independent empirical replication or benchmark reproducing claimed results">
      ${getIcon('checkCircle')} Independent Reproduction
    </span>`;
  } else if (isIndependent) {
    indPill = `<span class="pill-independent" title="Qualifies as independent under HERMES source-separation policy">
      ${getIcon('shield')} Independent Evidence
    </span>`;
  } else {
    indPill = `<span class="pill-dependent" title="Shared author/organization affiliation with primary claim or non-independent venue">
      Non-independent Evidence
    </span>`;
  }

  return `<div class="evidence-card" data-evidence-id="${escapeHtml(ev.evidence_id || ev.id || '')}">
    <div class="evidence-header">
      <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap;">
        ${renderSourcePill(source)}
        ${renderEvidenceStanceBadge(stance)}
        ${indPill}
      </div>
      <span class="mono text-xs text-muted">ID: ${escapeHtml(ev.evidence_id || ev.id || '—')}</span>
    </div>

    <div class="evidence-metrics-grid">
      <div class="evidence-metric-item" title="Evaluated artifact source quality and publication venue trustworthiness">
        Quality: <strong>${formatScorePercentage(ev.quality_score)}</strong>
      </div>
      <div class="evidence-metric-item" title="Calculated source and author organizational separation score">
        Independence: <strong>${formatScorePercentage(ev.independence_score)}</strong>
      </div>
      <div class="evidence-metric-item" title="Evaluated availability of reproducible scripts, public code, or benchmark datasets">
        Reproducibility: <strong>${formatScorePercentage(ev.reproducibility_score)}</strong>
      </div>
    </div>

    ${excerpt ? `<blockquote class="evidence-excerpt">${escapeHtml(excerpt)}</blockquote>` : ''}

    <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:var(--space-2);margin-top:var(--space-2);">
      ${url ? `
        <a href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer" class="evidence-url-link" aria-label="Visit external source link: ${escapeHtml(url)}">
          ${getIcon('externalLink')} <span>${escapeHtml(url)}</span>
        </a>
      ` : '<span class="text-xs text-faint">No external URL provided</span>'}
      <span class="text-xs text-muted">Observed: ${observedDate}</span>
    </div>
  </div>`;
}

/**
 * Render claim revision history section.
 * @param {Array<object>} revisions 
 * @returns {string} HTML string
 */
export function renderClaimRevisions(revisions) {
  const safeRevs = ensureArray(revisions);
  if (!safeRevs.length) return '';

  return `<div class="claim-revisions-section">
    <div class="synthesis-title" style="margin-bottom:var(--space-3);">${getIcon('clock')} Verification & State History (${safeRevs.length})</div>
    <div>
      ${safeRevs.map((r) => {
        const prevStatus = r.previous_status || r.old_status || null;
        const newStatus = r.new_status || 'unverified';
        const prevScore = typeof r.previous_verification_score === 'number' ? r.previous_verification_score : null;
        const newScore = typeof r.new_verification_score === 'number' ? r.new_verification_score : null;
        const reason = r.reason || 'Verification state update';
        const revisedAt = formatDate(r.created_at || r.revised_at);

        const prevLabel = prevStatus ? `${prevStatus} (${prevScore !== null ? formatScorePercentage(prevScore) : 'unassessed'})` : 'Initial Ingestion';
        const newLabel = `${newStatus} (${newScore !== null ? formatScorePercentage(newScore) : 'unassessed'})`;

        return `<div class="revision-item">
          <div class="revision-transition">
            <span class="text-muted">${escapeHtml(prevLabel)}</span>
            <span>&rarr;</span>
            <span class="text-semibold">${escapeHtml(newLabel)}</span>
          </div>
          <p class="text-xs text-secondary" style="margin:2px 0 0 0;">${escapeHtml(reason)}</p>
          <div class="mono text-xs text-faint" style="margin-top:2px;">${revisedAt} · Rev ID: ${escapeHtml(r.revision_id || r.id || '')}</div>
        </div>`;
      }).join('')}
    </div>
  </div>`;
}

/**
 * Render atomic claim card with progressive disclosure.
 * @param {object} claim 
 * @param {boolean} isExpanded 
 * @param {object|null} claimDetail 
 * @param {boolean} isLoading 
 * @param {string|null} error 
 * @returns {string} HTML string
 */
export function renderClaimCard(claim, isExpanded = false, claimDetail = null, isLoading = false, error = null) {
  const claimId = claim.claim_id || claim.id || '';
  const text = claim.claim_text || claim.text || 'Unspecified Claim';
  const status = claim.status || 'unverified';
  const verifScore = typeof claim.verification_score === 'number' ? claim.verification_score : null;
  const isSelfReported = Boolean(claim.is_self_reported || claim.self_reported);
  const assertionLevel = claim.assertion_level || null;
  const claimType = claim.claim_type || claim.type || null;
  const evidenceCount = claim.evidence_count !== undefined ? claim.evidence_count : (claimDetail ? (claimDetail.evidence || []).length : 0);

  const originLabel = isSelfReported ? 'Claim origin: Self-reported' : 'Claim origin: Not self-reported';
  const originClass = isSelfReported ? 'pill-self-reported' : 'pill-not-self-reported';
  const originTitle = isSelfReported 
    ? 'Claim originated from author repository or primary announcement' 
    : 'Claim not flagged as originating from primary self-reported announcement';

  return `<article class="claim-card ${isExpanded ? 'claim-card-expanded' : ''}" 
            id="claim-card-${escapeHtml(claimId)}" 
            data-claim-card-id="${escapeHtml(claimId)}">
    <div class="claim-header-row">
      <div class="claim-meta-tags">
        ${renderVerificationBadge(status, verifScore)}
        <span class="${originClass}" title="${originTitle}">${originLabel}</span>
        ${assertionLevel ? `<span class="chip mono">${escapeHtml(assertionLevel.replace(/_/g, ' '))}</span>` : ''}
        ${claimType ? `<span class="chip">${escapeHtml(claimType)}</span>` : ''}
      </div>

      <button type="button" 
              class="btn btn-secondary btn-sm btn-claim-toggle" 
              data-action="toggle-claim" 
              data-claim-id="${escapeHtml(claimId)}" 
              aria-expanded="${isExpanded ? 'true' : 'false'}" 
              aria-controls="claim-evidence-${escapeHtml(claimId)}"
              aria-label="${isExpanded ? 'Collapse evidence for claim' : 'Inspect evidence for claim'} ${escapeHtml(claimId)}">
        ${isExpanded ? `${getIcon('chevronDown')} Hide Evidence` : `${getIcon('chevronRight')} Inspect Evidence (${evidenceCount})`}
      </button>
    </div>

    <h3 class="claim-text-content" style="font-size:var(--text-base);font-weight:600;margin:var(--space-2) 0;">${escapeHtml(text)}</h3>
    <div class="mono text-xs text-muted">ID: ${escapeHtml(claimId)}</div>

    <div id="claim-evidence-${escapeHtml(claimId)}" class="claim-evidence-panel" style="display:${isExpanded ? 'block' : 'none'};">
      ${isLoading ? `
        <div style="padding:var(--space-4);text-align:center;">
          <span class="spinner" style="display:inline-block;margin-right:6px;"></span>
          <span class="text-sm text-muted">Retrieving progressive evidence provenance for ${escapeHtml(claimId)}…</span>
        </div>
      ` : error ? `
        <div class="alert alert-error" style="padding:var(--space-3);margin-bottom:var(--space-2);">
          <div style="display:flex;justify-content:space-between;align-items:center;">
            <span>Failed to load evidence: ${escapeHtml(error)}</span>
            <button type="button" class="btn btn-secondary btn-sm" data-action="toggle-claim" data-claim-id="${escapeHtml(claimId)}">Retry</button>
          </div>
        </div>
      ` : claimDetail ? `
        <div>
          <div class="synthesis-title" style="margin-bottom:var(--space-3);">
            Evidence Records (${(claimDetail.evidence || []).length})
          </div>
          ${(claimDetail.evidence && claimDetail.evidence.length) ? `
            <div style="display:flex;flex-direction:column;gap:var(--space-3);">
              ${claimDetail.evidence.map(renderEvidenceItem).join('')}
            </div>
          ` : `
            <p class="text-xs text-muted" style="margin:0;">No individual evidence records are attached to this claim yet.</p>
          `}
          ${renderClaimRevisions(claimDetail.revisions)}
        </div>
      ` : ''}
    </div>
  </article>`;
}

/**
 * Main Story Dossier View Renderer
 */
export async function renderStoryDetailView(container, store, routeParams = {}) {
  const storyId = routeParams.storyId || store.getState().selectedStoryId;

  if (!storyId) {
    container.innerHTML = renderEmptyState(
      'No Story Selected',
      'Select a development from Today, Search, or Saved Library to inspect its verified claims and evidence trail.',
      `<a href="#/today" class="btn btn-primary btn-sm">${getIcon('arrowLeft')} Back to Today</a>`,
      'h1'
    );
    return;
  }

  container.innerHTML = renderLoadingState(`Retrieving Story Dossier for ${storyId}…`);

  try {
    const story = await api.getStory(storyId);
    store.setState({ selectedStoryId: storyId });
    store.setConnection('healthy');

    const title = story.canonical_title || story.title || 'Story Dossier';
    const clusterScore = typeof story.cluster_score === 'number' ? story.cluster_score : (typeof story.score === 'number' ? story.score : null);
    const sources = ensureArray(story.sources || (story.source ? [story.source] : []));
    const synthesis = story.synthesis || null;
    const verif = story.verification || null;
    const maturity = story.maturity_stage || (verif ? verif.maturity_stage : null);
    const risk = story.risk || null;
    const claims = ensureArray(story.claims || []);
    const events = ensureArray(story.events || []);
    const projectMatches = ensureArray(story.project_matches || []);
    const relationships = ensureArray(story.relationships || []);

    // Set of expanded claim IDs for this session view
    const expandedClaims = new Set();
    const loadingClaims = new Set();
    const claimErrors = new Map();

    function renderDossierHtml() {
      return `
        <nav style="margin-bottom:var(--space-4);" aria-label="Breadcrumb navigation">
          <a href="#/today" class="btn btn-secondary btn-sm" id="btn-back-nav" aria-label="Back to feed">
            ${getIcon('arrowLeft')} Back to Today Feed
          </a>
        </nav>

        <header class="dossier-header-panel">
          <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:var(--space-4);flex-wrap:wrap;">
            <div style="flex:1;min-width:280px;">
              <div style="display:flex;gap:6px;align-items:center;margin-bottom:var(--space-2);flex-wrap:wrap;">
                ${sources.map(renderSourcePill).join('')}
                ${clusterScore !== null ? renderClusterScoreBadge(clusterScore) : ''}
              </div>
              <h1 style="margin:0 0 var(--space-2) 0;">${escapeHtml(title)}</h1>
              <div class="mono text-xs text-muted">
                Story Cluster ID: <strong>${escapeHtml(storyId)}</strong> · ${events.length} Source Event${events.length === 1 ? '' : 's'} · ${claims.length} Extracted Claim${claims.length === 1 ? '' : 's'}
              </div>
            </div>

            <div style="display:flex;gap:var(--space-2);align-items:center;">
              <button type="button" class="btn btn-secondary btn-sm" id="btn-save-dossier" aria-label="Save this story to research library">
                ${getIcon('star')} Save to Library
              </button>
            </div>
          </div>

          <div class="dossier-meta-row">
            <div>
              <span class="stat-label">Claim Verification</span>
              <div style="margin-top:4px;">
                ${verif ? renderVerificationBadge(verif.claim_status, verif.verification_score) : renderVerificationBadge(null)}
              </div>
            </div>

            <div>
              <span class="stat-label">Technology Maturity</span>
              <div style="margin-top:4px;">
                ${renderMaturityBadge(maturity)}
              </div>
            </div>

            <div>
              <span class="stat-label">Evaluated Risk</span>
              <div style="margin-top:4px;">
                ${risk ? renderRiskBadge(risk.status, risk.level, risk.score) : renderRiskBadge('not_assessed', null)}
              </div>
            </div>

            ${risk && risk.rationale ? `
              <div style="flex:1;min-width:240px;">
                <span class="stat-label">Risk Rationale</span>
                <p class="text-xs text-secondary" style="margin:4px 0 0 0;">${escapeHtml(risk.rationale)}</p>
              </div>
            ` : ''}
          </div>
        </header>

        <!-- Grounded Synthesis Section (Phase 3 Synthesis Contract) -->
        ${synthesis ? `
          <section class="panel" style="padding:var(--space-6);margin-bottom:var(--space-6);" aria-labelledby="section-synthesis-heading">
            <div class="section-header" style="margin-bottom:var(--space-4);">
              <div>
                <h2 id="section-synthesis-heading" style="font-size:var(--text-lg);margin:0;">Grounded Intelligence Synthesis</h2>
                <p class="text-muted text-xs" style="margin:2px 0 0 0;">Synthesized intelligence grounded in stored primary artifacts and verification models.</p>
              </div>
            </div>

            ${synthesis.what_happened ? `
              <div class="synthesis-card" id="synthesis-what-happened">
                <div class="synthesis-title">${getIcon('fileText')} What Happened</div>
                <div class="synthesis-statement">${escapeHtml(synthesis.what_happened.statement)}</div>
                ${renderGroundingReferences(synthesis.what_happened.grounding_references)}
              </div>
            ` : ''}

            ${synthesis.why_it_matters ? `
              <div class="synthesis-card" id="synthesis-why-it-matters">
                <div class="synthesis-title">${getIcon('alertCircle')} Why It Matters</div>
                <div class="synthesis-statement">${escapeHtml(synthesis.why_it_matters.statement)}</div>
                ${renderGroundingReferences(synthesis.why_it_matters.grounding_references)}
              </div>
            ` : ''}

            ${synthesis.evidence_position ? `
              <div class="synthesis-card" id="synthesis-evidence-position">
                <div class="synthesis-title">${getIcon('shield')} Evidence Position</div>
                <div class="synthesis-statement">${escapeHtml(synthesis.evidence_position.statement)}</div>
                ${renderGroundingReferences(synthesis.evidence_position.grounding_references)}
              </div>
            ` : ''}

            ${synthesis.project_implications ? `
              <div class="synthesis-card" id="synthesis-project-implications">
                <div class="synthesis-title">${getIcon('folder')} Project Implications</div>
                <div class="synthesis-statement">${escapeHtml(synthesis.project_implications.statement)}</div>
                ${renderGroundingReferences(synthesis.project_implications.grounding_references)}
              </div>
            ` : ''}

            ${synthesis.change_summary ? `
              <div class="synthesis-card" id="synthesis-change-summary">
                <div class="synthesis-title">${getIcon('clock')} Longitudinal Change Summary</div>
                <div class="synthesis-statement">${escapeHtml(synthesis.change_summary.statement)}</div>
                ${renderGroundingReferences(synthesis.change_summary.grounding_references)}
              </div>
            ` : ''}
          </section>
        ` : ''}

        <!-- Project Relevance & Matches (Phase 4 Contract) -->
        ${projectMatches.length ? `
          <section class="panel" style="padding:var(--space-6);margin-bottom:var(--space-6);" id="section-project-matches" aria-labelledby="section-projects-heading">
            <div class="section-header" style="margin-bottom:var(--space-4);">
              <div>
                <h2 id="section-projects-heading" style="font-size:var(--text-lg);margin:0;">Local Engineering Project Implications</h2>
                <p class="text-muted text-xs" style="margin:2px 0 0 0;">Computed alignment with scanned local codebase technology profiles.</p>
              </div>
            </div>
            <div class="grid-2" style="gap:var(--space-3);">
              ${projectMatches.map((pm) => {
                const projName = pm.project_name || pm.project_id || 'Project';
                const relScore = typeof pm.relevance_score === 'number' ? pm.relevance_score : null;
                const matchType = pm.match_type ? pm.match_type.replace(/_/g, ' ') : 'Relevance match';
                const rec = pm.recommendation || null;

                return `<div class="project-card-item" data-project-id="${escapeHtml(pm.project_id || '')}">
                  <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:var(--space-2);">
                    <div>
                      <div class="text-semibold">${escapeHtml(projName)}</div>
                      <div class="mono text-xs text-muted" style="margin-top:2px;">Type: ${escapeHtml(matchType)}</div>
                    </div>
                    <div style="display:flex;gap:var(--space-2);align-items:center;">
                      ${renderProjectRelevanceBadge(relScore)}
                      ${typeof pm.impact_score === 'number' ? renderProjectImpactBadge(pm.impact_score) : ''}
                    </div>
                  </div>
                  ${rec ? `<p class="text-xs text-secondary" style="margin:var(--space-2) 0 0 0;">${escapeHtml(rec)}</p>` : ''}
                </div>`;
              }).join('')}
            </div>
          </section>
        ` : ''}

        <!-- Extracted Claims & Progressive Evidence Investigation Section -->
        <section class="panel" style="padding:var(--space-6);margin-bottom:var(--space-6);" id="section-claims" aria-labelledby="section-claims-heading">
          <div class="section-header" style="margin-bottom:var(--space-4);">
            <div>
              <h2 id="section-claims-heading" style="font-size:var(--text-lg);margin:0;">Atomic Claims & Evidence Provenance</h2>
              <p class="text-muted text-xs" style="margin:2px 0 0 0;">Inspect individual empirical assertions, independent corroboration, and verification trails.</p>
            </div>
          </div>

          ${!claims.length ? `
            ${renderEmptyState('No Extracted Claims', 'No atomic assertions have been parsed for this story cluster.')}
          ` : `
            <div id="claims-container">
              ${claims.map((c) => {
                const cid = c.claim_id || c.id || '';
                const isExp = expandedClaims.has(cid);
                const isLd = loadingClaims.has(cid);
                const err = claimErrors.get(cid) || null;
                const detail = dossierClaimCache.get(cid) || null;
                return renderClaimCard(c, isExp, detail, isLd, err);
              }).join('')}
            </div>
          `}
        </section>

        <!-- Source Events Preview Section -->
        <section class="panel" style="padding:var(--space-6);margin-bottom:var(--space-6);" id="section-events" aria-labelledby="section-events-heading">
          <div class="section-header" style="margin-bottom:var(--space-4);">
            <div>
              <h2 id="section-events-heading" style="font-size:var(--text-lg);margin:0;">Source Events (${events.length})</h2>
              <p class="text-muted text-xs" style="margin:2px 0 0 0;">Preview of ingested primary artifacts grouped under this intelligence cluster.</p>
            </div>
          </div>

          ${!events.length ? `
            ${renderEmptyState('No Source Events', 'No primary source events found in preview.')}
          ` : `
            <div class="grid-1" style="gap:var(--space-3);">
              ${events.map((ev) => {
                const evId = ev.event_id || ev.id || '';
                const evTitle = ev.title || 'Untitled Event';
                const evSource = ev.source || 'source';
                const evUrl = ev.url && typeof ev.url === 'string' && ev.url.trim().startsWith('http') ? ev.url.trim() : null;
                const pubDate = formatDate(ev.published_at);
                const discDate = formatDate(ev.discovered_at);

                return `<article class="event-preview-card" id="event-card-${escapeHtml(evId)}" data-event-id="${escapeHtml(evId)}">
                  <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:var(--space-3);flex-wrap:wrap;">
                    <div>
                      <div style="display:flex;align-items:center;gap:6px;margin-bottom:4px;">
                        ${renderSourcePill(evSource)}
                        <span class="mono text-xs text-muted">ID: ${escapeHtml(evId)}</span>
                      </div>
                      <div class="text-semibold text-sm">${escapeHtml(evTitle)}</div>
                    </div>
                    <div class="text-xs text-muted" style="text-align:right;">
                      <div>Published: ${pubDate}</div>
                      <div>Discovered: ${discDate}</div>
                    </div>
                  </div>
                  ${evUrl ? `
                    <div style="margin-top:var(--space-2);">
                      <a href="${escapeHtml(evUrl)}" target="_blank" rel="noopener noreferrer" class="evidence-url-link" aria-label="Open source event url: ${escapeHtml(evUrl)}">
                        ${getIcon('externalLink')} <span>${escapeHtml(evUrl)}</span>
                      </a>
                    </div>
                  ` : ''}
                </article>`;
              }).join('')}
            </div>
          `}
        </section>

        <!-- Relationships Section (if present) -->
        ${relationships.length ? `
          <section class="panel" style="padding:var(--space-6);" id="section-relationships" aria-labelledby="section-relationships-heading">
            <h2 id="section-relationships-heading" style="font-size:var(--text-lg);margin:0 0 var(--space-3) 0;">Cross-Story Relationships (${relationships.length})</h2>
            <div class="grid-1" style="gap:var(--space-2);">
              ${relationships.map((rel) => {
                const relType = rel.relationship_type ? rel.relationship_type.replace(/_/g, ' ') : 'Related';
                const targetId = rel.target_cluster_id || rel.target_id || '';
                return `<div class="panel-subtle" style="padding:var(--space-3);display:flex;justify-content:space-between;align-items:center;">
                  <span class="mono text-xs">${escapeHtml(relType)} &rarr; <strong>${escapeHtml(targetId)}</strong></span>
                  <a href="#/stories/${encodeURIComponent(targetId)}" class="btn btn-secondary btn-sm">Inspect Target</a>
                </div>`;
              }).join('')}
            </div>
          </section>
        ` : ''}
      `;
    }

    container.innerHTML = renderDossierHtml();

    // Attach interactive event listeners
    attachDossierListeners();

    function attachDossierListeners() {
      // 1. Progressive Claim Disclosure Toggles
      container.querySelectorAll('[data-action="toggle-claim"]').forEach((btn) => {
        btn.addEventListener('click', async (e) => {
          const claimId = btn.getAttribute('data-claim-id');
          if (!claimId) return;

          if (expandedClaims.has(claimId)) {
            // Collapse
            expandedClaims.delete(claimId);
            updateClaimCardView(claimId);
          } else {
            // Expand
            expandedClaims.add(claimId);
            if (dossierClaimCache.has(claimId)) {
              // Instant load from session cache
              updateClaimCardView(claimId);
            } else {
              // Fetch claim detail on-demand
              loadingClaims.add(claimId);
              claimErrors.delete(claimId);
              updateClaimCardView(claimId);

              try {
                const claimDetail = await api.getClaim(claimId);
                dossierClaimCache.set(claimId, claimDetail);
                loadingClaims.delete(claimId);
                updateClaimCardView(claimId);
              } catch (err) {
                loadingClaims.delete(claimId);
                claimErrors.set(claimId, err.message || 'Failed to load evidence records');
                updateClaimCardView(claimId);
              }
            }
          }
        });
      });

      // 2. Interactive Grounding Reference Navigation
      container.querySelectorAll('[data-action="focus-grounding"]').forEach((pill) => {
        pill.addEventListener('click', async () => {
          const entityType = pill.getAttribute('data-entity-type');
          const entityId = pill.getAttribute('data-entity-id');
          if (!entityId) return;

          let targetFound = false;

          if (entityType === 'claim') {
            const claimCard = document.getElementById(`claim-card-${entityId}`);
            if (claimCard) {
              claimCard.scrollIntoView({ behavior: 'smooth', block: 'center' });
              claimCard.classList.remove('target-pulse-highlight');
              void claimCard.offsetWidth;
              claimCard.classList.add('target-pulse-highlight');
              targetFound = true;

              // Automatically expand evidence if not already open
              if (!expandedClaims.has(entityId)) {
                const toggleBtn = claimCard.querySelector('[data-action="toggle-claim"]');
                if (toggleBtn) toggleBtn.click();
              }
            }
          } else if (entityType === 'event') {
            const eventCard = document.getElementById(`event-card-${entityId}`);
            if (eventCard) {
              eventCard.scrollIntoView({ behavior: 'smooth', block: 'center' });
              eventCard.classList.remove('target-pulse-highlight');
              void eventCard.offsetWidth;
              eventCard.classList.add('target-pulse-highlight');
              targetFound = true;
            }
          } else if (entityType === 'evidence') {
            // Check if evidence is rendered in any loaded claim
            const evidenceCard = container.querySelector(`[data-evidence-id="${entityId}"]`);
            if (evidenceCard) {
              evidenceCard.scrollIntoView({ behavior: 'smooth', block: 'center' });
              evidenceCard.classList.remove('target-pulse-highlight');
              void evidenceCard.offsetWidth;
              evidenceCard.classList.add('target-pulse-highlight');
              targetFound = true;
            }
          } else if (entityType === 'assessment') {
            const metaRow = container.querySelector('.dossier-meta-row');
            if (metaRow) {
              metaRow.scrollIntoView({ behavior: 'smooth', block: 'center' });
              metaRow.classList.remove('target-pulse-highlight');
              void metaRow.offsetWidth;
              metaRow.classList.add('target-pulse-highlight');
              targetFound = true;
            }
          } else if (entityType === 'project_match') {
            const projectSection = document.getElementById('section-project-matches');
            const projectCard = container.querySelector(`[data-project-id="${entityId}"]`);
            const target = projectCard || projectSection;
            if (target) {
              target.scrollIntoView({ behavior: 'smooth', block: 'start' });
              target.classList.remove('target-pulse-highlight');
              void target.offsetWidth;
              target.classList.add('target-pulse-highlight');
              targetFound = true;
            }
          } else if (entityType === 'change') {
            const changeCard = document.getElementById('synthesis-change-summary');
            if (changeCard) {
              changeCard.scrollIntoView({ behavior: 'smooth', block: 'center' });
              changeCard.classList.remove('target-pulse-highlight');
              void changeCard.offsetWidth;
              changeCard.classList.add('target-pulse-highlight');
              targetFound = true;
            }
          }

          if (!targetFound) {
            // Truthful non-broken state for off-DOM entities (e.g. event outside top-10 preview)
            showGroundingToast(entityType, entityId);
          }
        });
      });

      function showGroundingToast(entityType, entityId) {
        let toast = container.querySelector('#grounding-feedback-toast');
        if (!toast) {
          toast = document.createElement('div');
          toast.id = 'grounding-feedback-toast';
          toast.className = 'panel';
          toast.style.cssText = 'position:fixed;bottom:24px;right:24px;max-width:380px;padding:var(--space-4);background:var(--bg-panel);border:1px solid var(--border-default);box-shadow:var(--shadow-lg);z-index:100;border-radius:var(--radius-md);';
          toast.setAttribute('role', 'status');
          toast.setAttribute('aria-live', 'polite');
          container.appendChild(toast);
        }

        const typeLabel = entityType.replace(/[_-]/g, ' ');
        toast.innerHTML = `
          <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:var(--space-3);">
            <div>
              <div class="text-semibold text-xs" style="text-transform:uppercase;color:var(--ink-muted);margin-bottom:2px;">
                Grounded Provenance Record
              </div>
              <div class="text-sm">
                <strong>${escapeHtml(typeLabel)}</strong>: <code class="mono text-xs">${escapeHtml(entityId)}</code>
              </div>
              <p class="text-xs text-secondary" style="margin:4px 0 0 0;">
                ${entityType === 'event' ? 'This source event is part of the cluster ingestion history outside the top preview.' : 'This provenance record is stored in the HERMES intelligence graph.'}
              </p>
            </div>
            <button type="button" class="btn btn-secondary btn-sm" id="btn-close-toast" aria-label="Close provenance notification" style="padding:2px 6px;">&times;</button>
          </div>
        `;
        toast.style.display = 'block';

        const closeBtn = toast.querySelector('#btn-close-toast');
        if (closeBtn) {
          closeBtn.addEventListener('click', () => {
            toast.style.display = 'none';
          });
        }
      }

      // 3. Save Story Button
      const saveBtn = container.querySelector('#btn-save-dossier');
      if (saveBtn) {
        saveBtn.addEventListener('click', async () => {
          try {
            saveBtn.disabled = true;
            saveBtn.innerHTML = `${getIcon('checkCircle')} Saved to Library`;
            await api.saveItem({ story_cluster_id: storyId });
          } catch {
            saveBtn.disabled = false;
          }
        });
      }
    }

    function updateClaimCardView(claimId) {
      const claim = claims.find((c) => (c.claim_id || c.id) === claimId);
      if (!claim) return;

      const cardElem = document.getElementById(`claim-card-${claimId}`);
      if (!cardElem) return;

      const isExp = expandedClaims.has(claimId);
      const isLd = loadingClaims.has(claimId);
      const err = claimErrors.get(claimId) || null;
      const detail = dossierClaimCache.get(claimId) || null;

      const newHtml = renderClaimCard(claim, isExp, detail, isLd, err);
      const tempDiv = document.createElement('div');
      tempDiv.innerHTML = newHtml;
      const newCardElem = tempDiv.firstElementChild;

      cardElem.replaceWith(newCardElem);
      attachDossierListeners();
    }

  } catch (err) {
    if (err.isNetworkError) {
      store.setConnection('offline', err.message);
      container.innerHTML = renderOfflineState(undefined, err.message);
    } else {
      store.setConnection('degraded', err.message);
      container.innerHTML = renderErrorState(`Story Not Found (${escapeHtml(storyId)})`, err.message);
    }
  }
}

export default renderStoryDetailView;

