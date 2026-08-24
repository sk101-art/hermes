/**
 * Accessible Error Boundary Component for HERMES SPA Views.
 * Wraps view loading and rendering failures with accessible alert semantics,
 * clear diagnostic messaging, and keyboard-accessible retry actions.
 */

import { escapeHtml } from '../utils/adapters.js';
import { focusPageHeading } from '../utils/a11y.js';

export function getErrorDiagnostics(err) {
  let title = 'Something Went Wrong';
  let message = 'An unexpected error occurred while rendering this view.';
  let type = 'unknown';

  if (!err) {
    return { title, message, type };
  }

  if (err.isTimeout) {
    title = 'Request Timed Out';
    message = 'The server took too long to respond. Please check your local backend connection and try again.';
    type = 'timeout';
  } else if (err.isNetworkError || err.status === 0) {
    title = 'Backend Unavailable';
    message = 'Unable to connect to the HERMES local API. Ensure the backend server is running on http://127.0.0.1:8765.';
    type = 'offline';
  } else if (err.status === 404) {
    title = 'Record Not Found';
    message = err.message || 'The requested intelligence record or entity could not be found in the database.';
    type = 'not_found';
  } else if (err.status >= 500) {
    title = 'Backend Server Error';
    message = err.message || 'The backend encountered an internal error while processing this request.';
    type = 'server_error';
  } else if (err.message) {
    message = err.message;
    if (err.message.includes('Malformed') || err.message.includes('JSON')) {
      title = 'Malformed Data Payload';
      type = 'malformed';
    }
  }

  return { title, message, type };
}

export function renderErrorBoundaryHtml(error, options = {}) {
  const { title: customTitle, viewKey = 'view' } = options;
  const diag = getErrorDiagnostics(error);
  const title = customTitle || diag.title;
  const message = diag.message;

  return `
    <div 
      class="error-boundary-card container" 
      role="alert" 
      aria-live="assertive"
      data-testid="error-boundary"
      tabindex="-1"
      style="padding: 2.5rem 1.5rem; text-align: center; max-width: 640px; margin: 3rem auto;"
    >
      <div class="error-boundary-icon" style="font-size: 2.5rem; margin-bottom: 1rem;" aria-hidden="true">⚠️</div>
      <h1 class="error-boundary-heading text-xl font-bold" id="error-boundary-title" tabindex="-1" style="margin-bottom: 0.75rem;">
        ${escapeHtml(title)}
      </h1>
      <p class="error-boundary-message text-muted" style="margin-bottom: 1.5rem; line-height: 1.5;">
        ${escapeHtml(message)}
      </p>
      <div class="error-boundary-actions" style="display: flex; gap: 0.75rem; justify-content: center; flex-wrap: wrap;">
        <button 
          type="button" 
          class="btn btn-primary btn-retry-view" 
          data-testid="btn-retry-view"
        >
          Try Again
        </button>
        <a 
          href="#/today" 
          class="btn btn-secondary btn-home-view" 
          data-testid="btn-home-view"
        >
          Back to Today
        </a>
      </div>
    </div>
  `;
}

/**
 * Mounts an accessible error boundary into a DOM container and binds retry logic.
 * @param {HTMLElement} container - DOM mount container
 * @param {Object} params
 * @param {Error} params.error - The caught exception
 * @param {string} params.viewKey - The current view key
 * @param {Function} [params.retryFn] - Asynchronous retry callback
 * @param {string} [params.title] - Optional custom error title
 */
export function mountErrorBoundary(container, { error, viewKey, retryFn, title }) {
  if (!container) return;

  container.innerHTML = renderErrorBoundaryHtml(error, { viewKey, title });

  const heading = container.querySelector('#error-boundary-title');
  if (heading && typeof heading.focus === 'function') {
    heading.focus();
  }

  const retryBtn = container.querySelector('.btn-retry-view');
  if (retryBtn && typeof retryFn === 'function') {
    retryBtn.addEventListener('click', async () => {
      retryBtn.disabled = true;
      retryBtn.textContent = 'Retrying…';
      try {
        await retryFn();
        focusPageHeading(container);
      } catch (retryErr) {
        mountErrorBoundary(container, { error: retryErr, viewKey, retryFn, title });
      }
    });
  }
}
