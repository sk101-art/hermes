/**
 * Canonical HERMES API Client
 * Centralized, robust HTTP client with abort support, error normalization,
 * and strict preservation of epistemic nulls/unassessed values.
 */

export class ApiError extends Error {
  constructor(message, status = 0, data = null, isNetworkError = false) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.data = data;
    this.isNetworkError = isNetworkError;
    this.timestamp = new Date().toISOString();
  }
}

export function getApiBaseUrl() {
  if (typeof window !== 'undefined' && window.localStorage) {
    return window.localStorage.getItem('hermes_api_url') || 'http://127.0.0.1:8765';
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

  // Build URL with query params
  let url = `${baseUrl.replace(/\/+$/, '')}/${endpoint.replace(/^\/+/, '')}`;
  if (params && typeof params === 'object') {
    const searchParams = new URLSearchParams();
    for (const [key, value] of Object.entries(params)) {
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
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);
  
  // Link with optional user signal
  if (userSignal) {
    userSignal.addEventListener('abort', () => controller.abort());
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
      throw new ApiError(errorMsg, response.status, errorData, false);
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

    if (err.name === 'AbortError') {
      throw new ApiError('Request timed out or was aborted', 0, null, true);
    }

    // Network / offline failure
    throw new ApiError(
      err.message || 'Unable to connect to local HERMES API',
      0,
      null,
      true
    );
  }
}

export default {
  request,
  getApiBaseUrl,
  setApiBaseUrl,
  ApiError,
};
