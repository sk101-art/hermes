/**
 * HERMES Story Detail (Baseline Dossier View)
 * Displays structured intelligence for a selected story cluster:
 * synthesis statements, verification detail, maturity stage, risk profile, claims, and evidence trail.
 */

import { api } from '../api/endpoints.js';
import { getIcon } from '../icons/index.js';
import {
  renderVerificationBadge,
  renderMaturityBadge,
  renderRiskBadge,
  renderEvidenceStanceBadge,
  renderSourcePill,
} from '../components/badges.js';
import { renderLoadingState, renderEmptyState, renderErrorState, renderOfflineState } from '../components/ui-states.js';
import { escapeHtml, formatDate, ensureArray, formatScorePercentage } from '../utils/adapters.js';

export async function renderStoryDetailView(container, store, routeParams = {}) {
  const storyId = routeParams.storyId || store.getState().selectedStoryId;

  if (!storyId) {
    container.innerHTML = renderEmptyState(
      'No Story Selected',
      'Select a development from Today, Search, or Saved Library to inspect its verified claims and evidence trail.',
      `<a href="#/today" class="btn btn-primary btn-sm">${getIcon('arrowLeft')} Back to Today</a>`
    );
    return;
  }

  container.innerHTML = renderLoadingState(`Loading dossier for ${storyId}…`);

  try {
    const story = await api.getStory(storyId);
    store.setState({ selectedStoryId: storyId });
    store.setConnection('healthy');

    const title = story.canonical_title || story.title || 'Story Dossier';
    const sources = ensureArray(story.sources || (story.source ? [story.source] : []));
    const synthesis = story.synthesis || null;
    const verif = story.verification || null;
    const maturity = story.maturity_stage || null;
    const risk = story.risk || null;
    const claims = ensureArray(story.claims || []);
    const events = ensureArray(story.events || []);

    let html = `
      <div style="margin-bottom:var(--space-4);">
        <a href="#/today" class="btn btn-secondary btn-sm" id="btn-back-nav" aria-label="Back to feed">
          ${getIcon('arrowLeft')} Back to Feed
        </a>
      </div>

      <div class="page-header-container">
        <div>
          <div style="display:flex;gap:6px;align-items:center;margin-bottom:var(--space-2);flex-wrap:wrap;">
            ${sources.map(renderSourcePill).join('')}
            ${!sources.length ? '<span class="source-pill">HERMES cluster</span>' : ''}
          </div>
          <h1>${escapeHtml(title)}</h1>
          <p class="mono text-xs text-muted" style="margin-top:2px;">ID: ${escapeHtml(storyId)}</p>
        </div>
      </div>

      <div class="panel" style="padding:var(--space-5);margin-bottom:var(--space-6);">
        <div style="display:flex;flex-wrap:wrap;gap:var(--space-3);align-items:center;">
          ${verif ? renderVerificationBadge(verif.claim_status, verif.verification_score) : renderVerificationBadge(null)}
          ${maturity ? renderMaturityBadge(maturity) : renderMaturityBadge(null)}
          ${risk ? renderRiskBadge(risk.status, risk.level, risk.score) : renderRiskBadge('not_assessed', null)}
          <span class="mono text-xs text-muted" style="margin-left:auto;">
            ${events.length} event${events.length === 1 ? '' : 's'} · ${claims.length} claim${claims.length === 1 ? '' : 's'}
          </span>
        </div>
      </div>
    `;

    // Grounded Synthesis Section (Phase 3 contract)
    if (synthesis) {
      html += `
        <div class="panel" style="padding:var(--space-6);margin-bottom:var(--space-6);">
          <span class="eyebrow">Grounded Synthesis</span>
          ${synthesis.what_happened ? `
            <div style="margin-bottom:var(--space-4);">
              <h3 style="font-size:var(--text-sm);text-transform:uppercase;color:var(--ink-muted);letter-spacing:var(--tracking-wide);">What Happened</h3>
              <p style="margin-top:4px;">${escapeHtml(synthesis.what_happened.statement)}</p>
            </div>
          ` : ''}
          ${synthesis.why_it_matters ? `
            <div style="margin-bottom:var(--space-4);">
              <h3 style="font-size:var(--text-sm);text-transform:uppercase;color:var(--ink-muted);letter-spacing:var(--tracking-wide);">Why It Matters</h3>
              <p style="margin-top:4px;">${escapeHtml(synthesis.why_it_matters.statement)}</p>
            </div>
          ` : ''}
          ${synthesis.evidence_position ? `
            <div>
              <h3 style="font-size:var(--text-sm);text-transform:uppercase;color:var(--ink-muted);letter-spacing:var(--tracking-wide);">Evidence Position</h3>
              <p style="margin-top:4px;">${escapeHtml(synthesis.evidence_position.statement)}</p>
            </div>
          ` : ''}
        </div>
      `;
    }

    // Claims and Evidence Section
    html += `
      <div class="section-header">
        <div>
          <h2>Extracted Claims & Evidence Provenance</h2>
          <p class="text-muted text-sm" style="margin:0;">Atomic claims extracted from primary artifacts with individual verification statuses.</p>
        </div>
      </div>
    `;

    if (!claims.length) {
      html += renderEmptyState('No Extracted Claims', 'No atomic claims have been linked to this development yet.');
    } else {
      html += `
        <div class="grid-1" style="gap:var(--space-3);">
          ${claims.map((c) => {
            const claimText = c.claim_text || c.text || 'Claim';
            const status = c.status || 'unverified';
            const score = typeof c.verification_score === 'number' ? c.verification_score : null;
            const isSelf = Boolean(c.is_self_reported || c.self_reported);

            return `<article class="panel" style="padding:var(--space-4);">
              <div style="display:flex;align-items:flex-start;justify-content:space-between;gap:var(--space-3);">
                <div>
                  <div class="text-semibold text-sm">${escapeHtml(claimText)}</div>
                  <div class="mono text-xs text-faint" style="margin-top:4px;">
                    ${isSelf ? 'Self-reported' : 'Third-party / Reported'} · ID: ${escapeHtml(c.claim_id || c.id || '')}
                  </div>
                </div>
                <div>
                  ${renderVerificationBadge(status, score)}
                </div>
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
      container.innerHTML = renderErrorState(`Failed to Load Story ${storyId}`, err.message);
    }
  }
}
