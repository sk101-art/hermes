/**
 * HERMES Story Card Component
 * Reusable card preview for story clusters across Today feed, Search, and Saved library.
 * 
 * Truthfulness Invariant:
 * Only renders semantic badges when backend intelligence actually exists.
 * Does not invent defaults for verification, maturity, or risk.
 */

import { escapeHtml, formatDate, truncateText, ensureArray } from '../utils/adapters.js';
import {
  renderVerificationBadge,
  renderMaturityBadge,
  renderRiskBadge,
  renderSourcePill,
  renderProjectMatchPill,
  renderRankingBadge,
} from './badges.js';

/**
 * Render a Story Cluster Preview Card.
 * @param {Object} story - Story object from /inbox, /search, or /saved
 * @returns {string} HTML string
 */
export function renderStoryCard(story) {
  if (!story) return '';

  const id = story.story_cluster_id || story.cluster_id || story.id || '';
  const title = story.title || story.canonical_title || 'Untitled Development';
  const summary = story.summary || story.why_it_matters || story.reason || story.text || '';
  const dateStr = story.published_at || story.created_at || story.updated_at || null;
  const sources = ensureArray(story.sources || story.source_names || (story.source ? [story.source] : []));

  // Epistemic properties (preserve null if unassessed)
  const verifStatus = story.verification_status || (story.verification ? story.verification.claim_status : null);
  const verifScore = typeof story.verification_score === 'number'
    ? story.verification_score
    : (story.verification && typeof story.verification.verification_score === 'number' ? story.verification.verification_score : null);

  const maturityStage = story.maturity_stage || story.maturity || null;

  // Risk state (status + level + score)
  const riskStatus = story.risk_status || (story.risk && story.risk.status ? story.risk.status : null);
  const riskLevel = story.risk_level || story.risk_score_category || (story.risk && story.risk.level ? story.risk.level : null);
  const riskScore = typeof story.risk_score === 'number'
    ? story.risk_score
    : (story.risk && typeof story.risk.score === 'number' ? story.risk.score : null);

  // Relevance / Ranking (Cluster or Search Score)
  const rankingScore = typeof story.cluster_score === 'number'
    ? story.cluster_score
    : (typeof story.score === 'number' ? story.score : (typeof story.relevance_score === 'number' ? story.relevance_score : null));

  // Project Match / Context
  const isProjectMatched = Boolean(story.project_match || story.project_impact_score > 0 || (story.matched_project_ids && story.matched_project_ids.length));
  const matchType = story.match_type || (isProjectMatched ? 'Project context' : null);

  return `<article class="story-card" data-story-id="${escapeHtml(id)}" role="button" tabindex="0" aria-label="Story: ${escapeHtml(title)}">
    <div class="story-card-top">
      <div style="display:flex;gap:6px;align-items:center;flex-wrap:wrap;">
        ${sources.slice(0, 3).map(renderSourcePill).join('')}
        ${!sources.length ? '<span class="source-pill">HERMES cluster</span>' : ''}
      </div>
      <time datetime="${escapeHtml(dateStr || '')}">${formatDate(dateStr)}</time>
    </div>

    <h3 class="story-title">${escapeHtml(title)}</h3>
    
    ${summary ? `<p class="story-why">${escapeHtml(truncateText(summary, 160))}</p>` : ''}

    <div class="story-card-bottom">
      ${verifStatus ? renderVerificationBadge(verifStatus, verifScore) : ''}
      ${maturityStage ? renderMaturityBadge(maturityStage) : ''}
      ${riskStatus && riskStatus !== 'not_assessed' ? renderRiskBadge(riskStatus, riskLevel, riskScore) : ''}
      ${matchType ? renderProjectMatchPill(matchType, story.project_impact_score) : ''}
      ${rankingScore !== null ? renderRankingBadge(rankingScore, 'Relevance') : ''}
    </div>
  </article>`;
}
