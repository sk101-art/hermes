/**
 * HERMES Domain & Formatting Adapters
 * Pure presentation formatting utilities.
 * NEVER derives intelligence, falsifies nulls, or invents defaults.
 */

/**
 * Escapes unsafe characters for HTML rendering.
 * @param {string|any} str 
 * @returns {string} Safe HTML string
 */
export function escapeHtml(str) {
  if (str === null || str === undefined) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

/**
 * Format ISO timestamp to localized human-readable date.
 * Returns '—' if null/invalid.
 * @param {string|Date|null} value 
 * @returns {string}
 */
export function formatDate(value) {
  if (!value) return '—';
  try {
    const d = new Date(value);
    if (isNaN(d.getTime())) return '—';
    return d.toLocaleDateString(undefined, {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
    });
  } catch {
    return '—';
  }
}

/**
 * Format ISO timestamp to localized human-readable time.
 * Returns '—' if null/invalid.
 * @param {string|Date|null} value 
 * @returns {string}
 */
export function formatTime(value) {
  if (!value) return '—';
  try {
    const d = new Date(value);
    if (isNaN(d.getTime())) return '—';
    return d.toLocaleTimeString(undefined, {
      hour: '2-digit',
      minute: '2-digit',
    });
  } catch {
    return '—';
  }
}

/**
 * Format ISO timestamp to relative time (e.g. "3h ago", "2d ago").
 * @param {string|Date|null} value 
 * @returns {string}
 */
export function formatRelativeTime(value) {
  if (!value) return '—';
  try {
    const d = new Date(value);
    const timeMs = d.getTime();
    if (isNaN(timeMs)) return '—';
    
    const now = Date.now();
    const diffSec = Math.floor((now - timeMs) / 1000);
    
    if (diffSec < 60) return 'just now';
    if (diffSec < 3600) return `${Math.floor(diffSec / 60)}m ago`;
    if (diffSec < 86400) return `${Math.floor(diffSec / 3600)}h ago`;
    if (diffSec < 604800) return `${Math.floor(diffSec / 86400)}d ago`;
    return formatDate(value);
  } catch {
    return '—';
  }
}

/**
 * Checks if a value is a valid finite normalized score in [0.0, 1.0].
 * Rejects null, undefined, NaN, Infinity, strings, objects, numbers < 0, numbers > 1.
 * @param {any} val
 * @returns {boolean}
 */
export function isValidNormalizedScore(val) {
  return typeof val === 'number' && Number.isFinite(val) && val >= 0.0 && val <= 1.0;
}

/**
 * Checks if a value is a valid finite non-normalized score (e.g. search rank or cluster score).
 * Rejects null, undefined, NaN, Infinity, strings, objects.
 * @param {any} val
 * @returns {boolean}
 */
export function isValidFiniteScore(val) {
  return typeof val === 'number' && Number.isFinite(val);
}

/**
 * Formats a numeric fraction (0.0 - 1.0) as a percentage string (e.g. "85%").
 * Returns '—' if value is null/undefined/NaN or outside [0.0, 1.0].
 * NEVER converts null, negative, or > 1 values to percentages.
 * Preserves genuine 0 as '0%'.
 * @param {number|null} score 
 * @returns {string}
 */
export function formatScorePercentage(score) {
  if (!isValidNormalizedScore(score)) {
    return '—';
  }
  return `${Math.round(score * 100)}%`;
}

/**
 * Formats a numeric score to 2 decimal places.
 * Returns '—' if value is null/undefined/NaN or non-finite.
 * @param {number|null} score 
 * @returns {string}
 */
export function formatScoreDecimal(score) {
  if (!isValidFiniteScore(score)) {
    return '—';
  }
  return score.toFixed(2);
}

/**
 * Convert snake_case or hyphenated string to Title Case.
 * @param {string|null} text 
 * @returns {string}
 */
export function toTitleCase(text) {
  if (!text) return '';
  return String(text)
    .replace(/[_-]/g, ' ')
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

/**
 * Truncate long text cleanly at word boundaries.
 * @param {string|null} text 
 * @param {number} [maxLength=140] 
 * @returns {string}
 */
export function truncateText(text, maxLength = 140) {
  if (!text) return '';
  if (text.length <= maxLength) return text;
  const sub = text.substring(0, maxLength);
  const lastSpace = sub.lastIndexOf(' ');
  return (lastSpace > 0 ? sub.substring(0, lastSpace) : sub) + '…';
}

/**
 * Ensures input is always an Array.
 * @param {any} value 
 * @returns {Array}
 */
export function ensureArray(value) {
  if (!value) return [];
  return Array.isArray(value) ? value : [value];
}
