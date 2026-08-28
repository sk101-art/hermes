/**
 * Canonical HERMES API Client
 * Centralized, robust HTTP client with abort support, error normalization,
 * and strict preservation of epistemic nulls/unassessed values.
 */

export class ApiError extends Error {
  constructor(message, status = 0, data = null, isNetworkError = false, isTimeout = false, isAborted = false) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.data = data;
    this.isNetworkError = isNetworkError;
    this.isTimeout = isTimeout;
    this.isAborted = isAborted;
    this.timestamp = new Date().toISOString();
  }
}

export const DEFAULT_API_BASE_URL = 'http://127.0.0.1:8765';

/**
 * Custom client header required by the sensitive /local/* endpoints. A
 * cross-origin page cannot set arbitrary headers without passing a CORS
 * preflight, which the locked-down CORS policy denies — so this header is a
 * real barrier against drive-by webpages hitting the folder-picker API.
 */
export const HERMES_CLIENT_HEADER = 'X-Hermes-Client';
export const HERMES_CLIENT_HEADER_VALUE = 'hermes-ui';
export const HERMES_SESSION_HEADER = 'X-Hermes-Session';

/**
 * Local session token cache. Issued by POST /local/session and attached to
 * every request so picker selection tokens stay tied to this UI session.
 */
let _sessionToken = null;
let _sessionPromise = null;

export function setSessionToken(token) {
  _sessionToken = token || null;
}

export function getSessionToken() {
  return _sessionToken;
}

/**
 * Lazily obtains (and caches) a local session token from the backend.
 * Failures are non-fatal: endpoints that require it will surface 401.
 */
export async function ensureSessionToken() {
  if (_sessionToken) return _sessionToken;
  if (_sessionPromise) return _sessionPromise;
  _sessionPromise = (async () => {
    try {
      const baseUrl = getApiBaseUrl();
      const resp = await fetch(`${baseUrl.replace(/\/+$/, '')}/local/session`, {
        method: 'POST',
        headers: { [HERMES_CLIENT_HEADER]: HERMES_CLIENT_HEADER_VALUE },
      });
      if (resp.ok) {
        const data = await resp.json();
        if (data && data.session_token) _sessionToken = data.session_token;
      }
    } catch {
      // Non-fatal; sensitive endpoints will report 401 if needed.
    } finally {
      _sessionPromise = null;
    }
    return _sessionToken;
  })();
  return _sessionPromise;
}

/**
 * Validate a stored API base URL. A stale/corrupt hermes_api_url value
 * (e.g. "undefined", "null", a bare path, or a non-http scheme) would
 * otherwise silently break every request with a confusing error.
 * Must be http(s)://host[:port][/path] with a non-empty host.
 */
export function isValidApiBaseUrl(url) {
  if (typeof url !== 'string') return false;
  const trimmed = url.trim();
  if (!/^https?:\/\/[^\s/]+(:\d{1,5})?(\/[^\s]*)?$/i.test(trimmed)) return false;
  try {
    const parsed = new URL(trimmed);
    return Boolean(parsed.hostname);
  } catch {
    return false;
  }
}

export function getApiBaseUrl() {
  if (typeof window !== 'undefined') {
    try {
      const urlParams = new URLSearchParams(window.location.search);
      const paramUrl = urlParams.get('api_url');
      if (paramUrl && isValidApiBaseUrl(paramUrl)) return paramUrl.trim();
      const paramPort = urlParams.get('api_port');
      if (paramPort && /^\d{1,5}$/.test(paramPort)) return `http://127.0.0.1:${paramPort}`;
    } catch {}
    if (window.localStorage) {
      try {
        const stored = window.localStorage.getItem('hermes_api_url');
        if (stored) {
          if (isValidApiBaseUrl(stored)) {
            return stored.trim();
          }
          // Stale/corrupt stored URL: discard it and fall back to the
          // canonical default instead of failing every request.
          window.localStorage.removeItem('hermes_api_url');
        }
      } catch {}
    }
  }
  return DEFAULT_API_BASE_URL;
}

export function setApiBaseUrl(url) {
  if (typeof window !== 'undefined' && window.localStorage) {
    if (url && isValidApiBaseUrl(url)) {
      window.localStorage.setItem('hermes_api_url', url.trim());
    } else {
      window.localStorage.removeItem('hermes_api_url');
    }
  }
}

/**
 * Perform an HTTP request to the HERMES backend.
 * @param {string} endpoint - API path (e.g. "/stories/cluster:123")
 * @param {Object} [options] - Fetch options + query params + timeout
 * @returns {Promise<any>}
 */
export async function request(endpoint, options = {}) {
  const {
    params,
    timeoutMs = 8000,
    signal: userSignal,
    baseUrl = getApiBaseUrl(),
    ...fetchOptions
  } = options;

  // Build URL with canonically sorted query params
  let url = `${baseUrl.replace(/\/+$/, '')}/${endpoint.replace(/^\/+/, '')}`;
  if (params && typeof params === 'object') {
    const sortedKeys = Object.keys(params).sort();
    const searchParams = new URLSearchParams();
    for (const key of sortedKeys) {
      const value = params[key];
      if (value !== undefined && value !== null) {
        searchParams.append(key, String(value));
      }
    }
    const queryString = searchParams.toString();
    if (queryString) {
      url += (url.includes('?') ? '&' : '?') + queryString;
    }
  }

  // Setup timeout & cancellation
  const controller = new AbortController();
  let timedOut = false;
  let userAborted = false;

  const timeoutId = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, timeoutMs);

  const onUserAbort = () => {
    userAborted = true;
    controller.abort();
  };

  if (userSignal) {
    if (userSignal.aborted) {
      userAborted = true;
      controller.abort();
    } else {
      userSignal.addEventListener('abort', onUserAbort);
    }
  }

  try {
    const isJsonBody = fetchOptions.body && typeof fetchOptions.body === 'object' && (typeof FormData === 'undefined' || !(fetchOptions.body instanceof FormData));
    const serializedBody = isJsonBody ? JSON.stringify(fetchOptions.body) : fetchOptions.body;

    // Attach the client identity header (required by /local/* endpoints) and
    // the local session token when one has been issued.
    const securityHeaders = { [HERMES_CLIENT_HEADER]: HERMES_CLIENT_HEADER_VALUE };
    if (_sessionToken) securityHeaders[HERMES_SESSION_HEADER] = _sessionToken;

    const response = await fetch(url, {
      ...fetchOptions,
      body: serializedBody,
      headers: {
        'Accept': 'application/json',
        ...(isJsonBody ? { 'Content-Type': 'application/json' } : {}),
        ...securityHeaders,
        ...fetchOptions.headers,
      },
      signal: controller.signal,
    });

    clearTimeout(timeoutId);

    // Handle non-2xx HTTP responses
    if (!response.ok) {
      // A 401 means our session token expired — drop it so the next call
      // re-issues a fresh one.
      if (response.status === 401) setSessionToken(null);
      let errorData = null;
      let errorMsg = `HTTP ${response.status}: ${response.statusText}`;
      try {
        errorData = await response.json();
        if (errorData && (errorData.detail || errorData.message)) {
          errorMsg = errorData.detail || errorData.message;
        }
      } catch {
        // Body was not JSON
      }
      throw new ApiError(errorMsg, response.status, errorData, false, false, false);
    }

    // Parse JSON while strictly preserving null/empty fields
    if (response.status === 204) {
      return null;
    }

    return await response.json();
  } catch (err) {
    clearTimeout(timeoutId);

    if (err instanceof ApiError) {
      throw err;
    }

    if (timedOut) {
      throw new ApiError('Request timed out', 0, null, true, true, false);
    }

    if (userAborted || err.name === 'AbortError') {
      throw new ApiError('Request was aborted', 0, null, false, false, true);
    }

    // Network / offline failure
    throw new ApiError(
      err.message || 'Unable to connect to local HERMES API',
      0,
      null,
      true,
      false,
      false
    );
  } finally {
    clearTimeout(timeoutId);
    if (userSignal) {
      userSignal.removeEventListener('abort', onUserAbort);
    }
  }
}

export default {
  request,
  getApiBaseUrl,
  setApiBaseUrl,
  isValidApiBaseUrl,
  ensureSessionToken,
  getSessionToken,
  setSessionToken,
  HERMES_CLIENT_HEADER,
  HERMES_CLIENT_HEADER_VALUE,
  HERMES_SESSION_HEADER,
  DEFAULT_API_BASE_URL,
  ApiError,
};
