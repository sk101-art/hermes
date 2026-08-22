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
import { escapeHtml, formatScorePercentage } from '../utils/adapters.js';

/**
 * Render a Verification Status Badge.
 * @param {string|null} status 
 * @param {number|null} [score=null]
 * @returns {string} HTML string
 */
export function renderVerificationBadge(status, score = null) {
  const meta = getVerificationMeta(status);
  const iconSvg = meta.icon ? getIcon(meta.icon) : '';
  const scoreStr = (score !== null && score !== undefined && typeof score === 'number' && !isNaN(score))
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
 * Render a Ranking / Relevance Score Badge.
 * Strictly labeled Relevance or Rank, NEVER Confidence or Verification.
 * @param {number|null} score 
 * @param {string} [label='Relevance'] 
 * @returns {string} HTML string
 */
export function renderRankingBadge(score, label = 'Relevance') {
  if (score === null || score === undefined || isNaN(score)) {
    return '';
  }
  const scoreText = (score >= 0 && score <= 1) ? `${Math.round(score * 100)}%` : String(score);
  return `<span class="semantic-badge badge-rank" title="Search / Ingestion ranking score" aria-label="${escapeHtml(label)} score: ${scoreText}">
    <span>${escapeHtml(label)}: ${scoreText}</span>
  </span>`;
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
 * Render a Project Context Match Pill.
 * @param {string|null} matchType 
 * @param {number|null} [impactScore=null]
 * @returns {string} HTML string
 */
export function renderProjectMatchPill(matchType, impactScore = null) {
  const label = matchType ? matchType.replace(/[_-]/g, ' ') : 'Project Match';
  const impact = impactScore !== null && impactScore !== undefined ? ` (${Math.round(impactScore * 100)}%)` : '';
  return `<span class="project-match-pill" title="Matched to local engineering project profile" aria-label="Project relevance: ${escapeHtml(label)}${impact}">
    <span>${escapeHtml(label)}${impact}</span>
  </span>`;
}
