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

export function getApiBaseUrl() {
  if (typeof window !== 'undefined') {
    try {
      const urlParams = new URLSearchParams(window.location.search);
      if (urlParams.get('api_url')) return urlParams.get('api_url');
      if (urlParams.get('api_port')) return `http://127.0.0.1:${urlParams.get('api_port')}`;
    } catch {}
    if (window.localStorage) {
      try {
        const stored = window.localStorage.getItem('hermes_api_url');
        if (stored) return stored;
      } catch {}
    }
  }
  return 'http://127.0.0.1:8765';
}

export function setApiBaseUrl(url) {
  if (typeof window !== 'undefined' && window.localStorage) {
    if (url) {
      window.localStorage.setItem('hermes_api_url', url);
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

    const response = await fetch(url, {
      ...fetchOptions,
      body: serializedBody,
      headers: {
        'Accept': 'application/json',
        ...(isJsonBody ? { 'Content-Type': 'application/json' } : {}),
        ...fetchOptions.headers,
      },
      signal: controller.signal,
    });

    clearTimeout(timeoutId);

    // Handle non-2xx HTTP responses
    if (!response.ok) {
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
  ApiError,
};
