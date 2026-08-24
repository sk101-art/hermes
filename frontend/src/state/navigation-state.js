/**
 * Canonical HERMES Navigation & Filter State Manager
 * Synchronizes view query parameters with URL hash history for back/forward restoration.
 */

export function buildRouteUrl(viewKey, params = {}) {
  const cleanView = String(viewKey || 'today').replace(/^#\/?/, '');
  if (!params || typeof params !== 'object') {
    return `#/${cleanView}`;
  }

  const sortedKeys = Object.keys(params).sort();
  const searchParams = new URLSearchParams();
  for (const k of sortedKeys) {
    const v = params[k];
    if (v !== undefined && v !== null && v !== '' && v !== false) {
      searchParams.append(k, String(v));
    }
  }
  const qs = searchParams.toString();
  return qs ? `#/${cleanView}?${qs}` : `#/${cleanView}`;
}

export function updateRouteHash(viewKey, params = {}, replace = true) {
  if (typeof window === 'undefined') return;
  const targetUrl = buildRouteUrl(viewKey, params);
  if (replace && window.history && typeof window.history.replaceState === 'function') {
    window.history.replaceState(null, '', targetUrl);
  } else {
    window.location.hash = targetUrl.replace(/^#/, '');
  }
}

export function parseQueryParams(queryStringOrHash = '') {
  const raw = String(queryStringOrHash || '');
  const queryPart = raw.includes('?') ? raw.split('?')[1] : raw;
  const searchParams = new URLSearchParams(queryPart);
  const out = {};
  for (const [k, v] of searchParams.entries()) {
    out[k] = v;
  }
  return out;
}
