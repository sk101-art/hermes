/**
 * HERMES Canonical Semantic Display Components
 * Reusable presentation components for canonical domain models.
 * 
 * Strict Truthfulness Guarantee:
 * - null is NEVER converted to zero or positive states.
 * - Missing verification renders "Not assessed", not "Unverified" or "Supported".
 * - Missing maturity renders "Not assessed", not "Experimental" or "Concept".
 * - Risk with status "not_assessed" NEVER renders "Low Risk".
 * - Risk with status "insufficient_data" NEVER renders "Medium Risk".
 * - Contextual evidence NEVER renders as "Supports".
 * - Ranking scores are NEVER labeled "Confidence" or "Verification".
 */

import { getIcon } from '../icons/index.js';
import {
  getVerificationMeta,
  getMaturityMeta,
  getRiskMeta,
  getEvidenceStanceMeta,
} from '../utils/semantic.js';
import {
  escapeHtml,
  formatScorePercentage,
  isValidNormalizedScore,
  isValidFiniteScore,
} from '../utils/adapters.js';

/**
 * Render a Verification Status Badge.
 * @param {string|null} status 
 * @param {number|null} [score=null]
 * @returns {string} HTML string
 */
export function renderVerificationBadge(status, score = null) {
  const meta = getVerificationMeta(status);
  const iconSvg = meta.icon ? getIcon(meta.icon) : '';
  const scoreStr = isValidNormalizedScore(score)
    ? ` (${formatScorePercentage(score)})`
    : '';

  return `<span class="semantic-badge ${meta.cssClass}" title="${escapeHtml(meta.description)}" aria-label="Verification: ${escapeHtml(meta.label)}${scoreStr}">
    <span class="semantic-badge-icon">${iconSvg}</span>
    <span>${escapeHtml(meta.label)}${scoreStr}</span>
  </span>`;
}

/**
 * Render a Technology Maturity Stage Badge.
 * @param {string|null} stage - 'concept' | 'research' | 'prototype' | 'experimental' | 'early_adoption' | 'production_candidate' | 'established'
 * @returns {string} HTML string
 */
export function renderMaturityBadge(stage) {
  const meta = getMaturityMeta(stage);
  return `<span class="semantic-badge ${meta.cssClass}" title="${escapeHtml(meta.description)}" aria-label="Maturity stage: ${escapeHtml(meta.label)}">
    <span>${escapeHtml(meta.label)}</span>
  </span>`;
}

/**
 * Render a Risk Level / Status Badge.
 * @param {string|null} status - 'assessed' | 'not_assessed' | 'insufficient_data'
 * @param {string|null} level - 'critical' | 'high' | 'medium' | 'low'
 * @param {number|null} [score=null]
 * @returns {string} HTML string
 */
export function renderRiskBadge(status, level, score = null) {
  const meta = getRiskMeta(status, level, score);
  const iconSvg = meta.icon ? getIcon(meta.icon) : '';

  return `<span class="semantic-badge ${meta.cssClass}" title="${escapeHtml(meta.description)}" aria-label="${escapeHtml(meta.label)}">
    <span class="semantic-badge-icon">${iconSvg}</span>
    <span>${escapeHtml(meta.label)}</span>
  </span>`;
}

/**
 * Render an Evidence Stance Badge.
 * @param {string|null} stance - 'supports' | 'contradicts' | 'context'
 * @returns {string} HTML string
 */
export function renderEvidenceStanceBadge(stance) {
  const meta = getEvidenceStanceMeta(stance);
  return `<span class="semantic-badge ${meta.cssClass}" title="${escapeHtml(meta.description)}" aria-label="Evidence stance: ${escapeHtml(meta.label)}">
    <span>${escapeHtml(meta.label)}</span>
  </span>`;
}

/**
 * Closed Score Domain Identifiers
 */
export const SCORE_DOMAINS = Object.freeze({
  SEARCH_RANK: 'search_rank',
  RELEVANCE: 'relevance',
  CLUSTER_SCORE: 'cluster_score',
  INBOX_PRIORITY: 'inbox_priority',
  INBOX_RANK: 'inbox_rank',
  PROJECT_RELEVANCE: 'project_relevance',
  PROJECT_IMPACT: 'project_impact',
});

/**
 * Render Search Score Badge (Neutral decimal representation, never probability percentage).
 * @param {number|null} score 
 * @returns {string}
 */
export function renderSearchScoreBadge(score) {
  if (!isValidFiniteScore(score)) {
    return '';
  }
  const formatted = score.toFixed(2);
  return `<span class="semantic-badge badge-rank" title="Search retrieval and ranking score" aria-label="Search rank score: ${formatted}">
    <span>Score: ${formatted}</span>
  </span>`;
}

/**
 * Render Relevance Score Badge (Normalized fraction 0.0 - 1.0).
 * @param {number|null} score 
 * @returns {string}
 */
export function renderRelevanceBadge(score) {
  if (!isValidNormalizedScore(score)) {
    return '';
  }
  const formatted = formatScorePercentage(score);
  return `<span class="semantic-badge badge-rank" title="Corpus query relevance score" aria-label="Relevance: ${formatted}">
    <span>Relevance: ${formatted}</span>
  </span>`;
}

/**
 * Render Cluster Discovery Score Badge (Non-normalized aggregate score, never percentage).
 * @param {number|null} score 
 * @returns {string}
 */
export function renderClusterScoreBadge(score) {
  if (!isValidFiniteScore(score)) {
    return '';
  }
  const formatted = score.toFixed(2);
  return `<span class="semantic-badge badge-rank" title="Aggregated cluster discovery score" aria-label="Cluster score: ${formatted}">
    <span>Cluster score: ${formatted}</span>
  </span>`;
}

/**
 * Render Daily Inbox Priority Score Badge (Normalized fraction 0.0 - 1.0).
 * @param {number|null} score 
 * @returns {string}
 */
export function renderInboxPriorityBadge(score) {
  if (!isValidNormalizedScore(score)) {
    return '';
  }
  const formatted = formatScorePercentage(score);
  return `<span class="semantic-badge badge-rank" title="Daily inbox priority score" aria-label="Priority: ${formatted}">
    <span>Priority: ${formatted}</span>
  </span>`;
}

/**
 * Render Daily Inbox Rank Score Badge (Normalized fraction 0.0 - 1.0).
 * @param {number|null} score 
 * @returns {string}
 */
export function renderInboxRankBadge(score) {
  if (!isValidNormalizedScore(score)) {
    return '';
  }
  const formatted = formatScorePercentage(score);
  return `<span class="semantic-badge badge-rank" title="Daily inbox rank score" aria-label="Rank: ${formatted}">
    <span>Rank: ${formatted}</span>
  </span>`;
}

/**
 * Render Project Relevance Badge (Normalized fraction 0.0 - 1.0).
 * @param {number|null} score 
 * @returns {string}
 */
export function renderProjectRelevanceBadge(score) {
  if (!isValidNormalizedScore(score)) {
    return '';
  }
  const formatted = formatScorePercentage(score);
  return `<span class="semantic-badge badge-rank" title="Local project relevance score" aria-label="Project relevance: ${formatted}">
    <span>Project relevance: ${formatted}</span>
  </span>`;
}

/**
 * Render Project Impact Badge (Normalized fraction 0.0 - 1.0).
 * @param {number|null} score 
 * @returns {string}
 */
export function renderProjectImpactBadge(score) {
  if (!isValidNormalizedScore(score)) {
    return '';
  }
  const formatted = formatScorePercentage(score);
  return `<span class="semantic-badge badge-rank" title="Local project impact score" aria-label="Project impact: ${formatted}">
    <span>Project impact: ${formatted}</span>
  </span>`;
}

/**
 * Closed domain-aware ranking badge renderer.
 * Strictly uses closed score domains without guessing from numeric magnitude.
 * Does NOT default to relevance or any other domain.
 * @param {number|null} score 
 * @param {string} domain - Must be an explicit member of SCORE_DOMAINS
 * @returns {string} HTML string
 */
export function renderScoreBadge(score, domain) {
  if (score === null || score === undefined || typeof score !== 'number' || !Number.isFinite(score)) {
    return '';
  }
  switch (domain) {
    case SCORE_DOMAINS.SEARCH_RANK:
      return renderSearchScoreBadge(score);
    case SCORE_DOMAINS.CLUSTER_SCORE:
      return renderClusterScoreBadge(score);
    case SCORE_DOMAINS.INBOX_PRIORITY:
      return renderInboxPriorityBadge(score);
    case SCORE_DOMAINS.INBOX_RANK:
      return renderInboxRankBadge(score);
    case SCORE_DOMAINS.PROJECT_RELEVANCE:
      return renderProjectRelevanceBadge(score);
    case SCORE_DOMAINS.PROJECT_IMPACT:
      return renderProjectImpactBadge(score);
    case SCORE_DOMAINS.RELEVANCE:
      return renderRelevanceBadge(score);
    default:
      // Unknown or missing domain: omit the badge, never guess relevance or convert to percentage
      return '';
  }
}

/**
 * Direct alias for renderScoreBadge.
 * Requires an explicit domain argument.
 */
export function renderRankingBadge(score, domain) {
  return renderScoreBadge(score, domain);
}

export const CANONICAL_SOURCES = {
  github: 'GitHub',
  github_releases: 'GitHub Releases',
  arxiv: 'arXiv',
  hackernews: 'Hacker News',
  huggingface: 'Hugging Face',
  openalex: 'OpenAlex',
  crossref: 'Crossref',
  stackexchange: 'Stack Exchange',
  rss: 'RSS Feed',
};

export function renderSourcePill(source) {
  if (!source) return '';
  const key = String(source).toLowerCase().trim();
  const label = CANONICAL_SOURCES[key] || source;
  return `<span class="source-pill" aria-label="Source: ${escapeHtml(label)}">
    <span>${escapeHtml(label)}</span>
  </span>`;
}

/**
 * Render a Project Context Match Pill (Strictly match type only; does NOT combine impact score).
 * @param {string|null} matchType 
 * @returns {string} HTML string
 */
export function renderProjectMatchPill(matchType) {
  if (!matchType) return '';
  const label = matchType.replace(/[_-]/g, ' ');
  return `<span class="project-match-pill" title="Matched to local engineering project profile" aria-label="Project match: ${escapeHtml(label)}">
    <span>${escapeHtml(label)}</span>
  </span>`;
}
