/**
 * HERMES Reusable UI States
 * Standardized presentation for loading, empty, offline, degraded, and error states.
 * 
 * Rules:
 * - Empty states must NOT imply error or failure.
 * - Offline states must distinguish browser/network failure from HERMES backend degradation.
 * - Degraded states surface actionable diagnostic information.
 */

import { getIcon } from '../icons/index.js';
import { escapeHtml } from '../utils/adapters.js';

/**
 * Render a Loading State Container.
 * @param {string} [message='Connecting to local intelligence engine…']
 * @returns {string} HTML string
 */
export function renderLoadingState(message = 'Connecting to local intelligence engine…') {
  return `<div class="state-container state-loading" role="status" aria-live="polite">
    <div class="state-icon-wrapper">
      <div class="spinner" aria-hidden="true"></div>
    </div>
    <div class="state-title">Loading Intelligence</div>
    <p class="state-description">${escapeHtml(message)}</p>
  </div>`;
}

/**
 * Render an Empty State Container.
 * Never implies system error.
 * @param {string} title 
 * @param {string} description 
 * @param {string} [actionHtml='']
 * @returns {string} HTML string
 */
export function renderEmptyState(title, description, actionHtml = '') {
  return `<div class="state-container state-empty" role="region" aria-label="${escapeHtml(title)}">
    <div class="state-icon-wrapper">
      ${getIcon('inbox')}
    </div>
    <div class="state-title">${escapeHtml(title)}</div>
    <p class="state-description">${escapeHtml(description)}</p>
    ${actionHtml ? `<div class="state-actions">${actionHtml}</div>` : ''}
  </div>`;
}

/**
 * Render an Offline State Container.
 * Clearly explains that the local API / backend is unreachable.
 * @param {string} [apiUrl='http://127.0.0.1:8765']
 * @param {string} [errorDetail='']
 * @returns {string} HTML string
 */
export function renderOfflineState(apiUrl = 'http://127.0.0.1:8765', errorDetail = '') {
  return `<div class="state-container state-offline" role="alert" aria-live="assertive">
    <div class="state-icon-wrapper">
      ${getIcon('wifiOff')}
    </div>
    <div class="state-title">Unable to Connect to HERMES API</div>
    <p class="state-description">
      HERMES could not establish a connection to <code>${escapeHtml(apiUrl)}</code>. 
      Start the FastAPI backend server to load live intelligence.
    </p>
    ${errorDetail ? `<p class="state-description" style="font-size:12px;color:#dc2626;background:#fee2e2;padding:6px 12px;border-radius:6px;">${escapeHtml(errorDetail)}</p>` : ''}
    <div class="state-actions">
      <button class="btn btn-secondary btn-sm" id="retry-btn">
        ${getIcon('refresh')} Retry Connection
      </button>
      <a href="${escapeHtml(apiUrl)}/docs" target="_blank" rel="noopener noreferrer" class="btn btn-secondary btn-sm">
        ${getIcon('external')} Open API Docs
      </a>
    </div>
  </div>`;
}

/**
 * Render an API Error State Container.
 * @param {string} title 
 * @param {string} errorMessage 
 * @returns {string} HTML string
 */
export function renderErrorState(title, errorMessage) {
  return `<div class="state-container state-error" role="alert" aria-live="assertive">
    <div class="state-icon-wrapper">
      ${getIcon('alertTriangle')}
    </div>
    <div class="state-title">${escapeHtml(title)}</div>
    <p class="state-description">${escapeHtml(errorMessage)}</p>
    <div class="state-actions">
      <button class="btn btn-secondary btn-sm" id="retry-btn">
        ${getIcon('refresh')} Try Again
      </button>
    </div>
  </div>`;
}

/**
 * Render a Degraded Backend State Container.
 * @param {string} title 
 * @param {string} details 
 * @returns {string} HTML string
 */
export function renderDegradedState(title, details) {
  return `<div class="state-container state-degraded" role="region" aria-label="${escapeHtml(title)}">
    <div class="state-icon-wrapper">
      ${getIcon('alertCircle')}
    </div>
    <div class="state-title">${escapeHtml(title)}</div>
    <p class="state-description">${escapeHtml(details)}</p>
    <div class="state-actions">
      <button class="btn btn-secondary btn-sm" id="retry-btn">
        ${getIcon('refresh')} Refresh Status
      </button>
    </div>
  </div>`;
}
