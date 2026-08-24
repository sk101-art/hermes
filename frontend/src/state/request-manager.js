/**
 * HERMES In-Flight Request Manager
 * Centralized in-flight promise sharing, generation-token stale response protection,
 * and deterministic route-level cancellation.
 */

import { request as baseRequest, ApiError } from '../api/client.js';

export class RequestManager {
  constructor() {
    this.inFlight = new Map(); // key -> Promise
    this.routeControllers = new Map(); // viewKey -> Set<AbortController>
    this.viewGenerations = new Map(); // viewKey -> current token integer
    this.globalGeneration = 0;
  }

  /**
   * Computes a canonical deterministic deduplication key for a request.
   * @param {string} endpoint 
   * @param {Object} [params]
   * @param {string} [method='GET']
   * @param {number} [gen=null]
   * @returns {string}
   */
  getCanonicalKey(endpoint, params = null, method = 'GET', gen = null) {
    const cleanEndpoint = String(endpoint || '').replace(/^\/+/, '');
    const upperMethod = String(method || 'GET').toUpperCase();
    let qs = '';
    if (params && typeof params === 'object') {
      const sortedKeys = Object.keys(params).sort();
      const searchParams = new URLSearchParams();
      for (const k of sortedKeys) {
        const val = params[k];
        if (val !== undefined && val !== null) {
          searchParams.append(k, String(val));
        }
      }
      qs = searchParams.toString();
    }
    const baseKey = qs ? `${upperMethod}:${cleanEndpoint}?${qs}` : `${upperMethod}:${cleanEndpoint}`;
    return gen !== null && gen !== undefined ? `${baseKey}#gen:${gen}` : baseKey;
  }

  /**
   * Advances the generation token for a view, invalidating any pending responses.
   * @param {string} viewKey 
   * @returns {number} The new generation token
   */
  nextGeneration(viewKey = 'global') {
    this.globalGeneration += 1;
    const nextGen = (this.viewGenerations.get(viewKey) || 0) + 1;
    this.viewGenerations.set(viewKey, nextGen);
    return nextGen;
  }

  /**
   * Retrieves the current generation token for a view.
   * @param {string} viewKey 
   * @returns {number}
   */
  getGeneration(viewKey = 'global') {
    return this.viewGenerations.get(viewKey) || 0;
  }

  /**
   * Checks whether a given generation token is still the active, newest generation.
   * @param {string} viewKey 
   * @param {number} gen 
   * @returns {boolean}
   */
  isCurrent(viewKey, gen) {
    if (gen === undefined || gen === null) return true;
    const current = this.viewGenerations.get(viewKey) || 0;
    return gen === current;
  }

  /**
   * Aborts all in-flight requests associated with a specific view route.
   * @param {string} viewKey 
   */
  abortRoute(viewKey) {
    if (!viewKey) return;
    const controllers = this.routeControllers.get(viewKey);
    if (controllers && controllers.size > 0) {
      for (const ctrl of controllers) {
        try {
          ctrl.abort();
        } catch {}
      }
      controllers.clear();
    }
    this.nextGeneration(viewKey);
  }

  /**
   * Aborts all in-flight requests across the entire application.
   */
  abortAll() {
    for (const [viewKey, controllers] of this.routeControllers.entries()) {
      for (const ctrl of controllers) {
        try {
          ctrl.abort();
        } catch {}
      }
      controllers.clear();
    }
    this.inFlight.clear();
    this.globalGeneration += 1;
  }

  /**
   * Dispatches a deduplicated HTTP request with race-protection and route cancellation tracking.
   * @param {string} endpoint - API path
   * @param {Object} [options] - Options passed to client.request
   * @param {string} [options.viewKey] - View route context for generation & cancellation
   * @param {number} [options.generation] - Expected generation token
   * @returns {Promise<any>}
   */
  async request(endpoint, options = {}) {
    const {
      viewKey,
      generation: reqGen,
      ...fetchOptions
    } = options;

    const method = String(fetchOptions.method || 'GET').toUpperCase();
    const isGet = method === 'GET';
    const assignedGen = reqGen !== undefined ? reqGen : (viewKey ? this.getGeneration(viewKey) : this.globalGeneration);
    const canonicalKey = this.getCanonicalKey(endpoint, fetchOptions.params, method, assignedGen);

    // Reuse in-flight GET requests within the same generation
    if (isGet && this.inFlight.has(canonicalKey)) {
      return this.inFlight.get(canonicalKey);
    }

    // Setup route-level AbortController
    const controller = new AbortController();
    if (viewKey) {
      if (!this.routeControllers.has(viewKey)) {
        this.routeControllers.set(viewKey, new Set());
      }
      this.routeControllers.get(viewKey).add(controller);
    }

    let promise;
    promise = (async () => {
      try {
        const data = await baseRequest(endpoint, {
          ...fetchOptions,
          signal: controller.signal,
        });

        // Stale generation check
        if (viewKey && !this.isCurrent(viewKey, assignedGen)) {
          const staleErr = new ApiError('Response dropped due to navigation / stale generation', 0, null, false);
          staleErr.isStale = true;
          staleErr.isAborted = true;
          throw staleErr;
        }

        return data;
      } finally {
        if (isGet) {
          if (this.inFlight.get(canonicalKey) === promise) {
            this.inFlight.delete(canonicalKey);
          }
        }
        if (viewKey && this.routeControllers.has(viewKey)) {
          this.routeControllers.get(viewKey).delete(controller);
        }
      }
    })();

    if (isGet) {
      this.inFlight.set(canonicalKey, promise);
    }

    return promise;
  }
}

export const requestManager = new RequestManager();
export default requestManager;
