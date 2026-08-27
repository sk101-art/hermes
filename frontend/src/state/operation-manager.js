/**
 * HERMES Operation Manager
 * Manages background task enqueueing, active status polling, and callback hooks.
 *
 * Phase 4 Req 6 contracts:
 * - Pre-Sync readiness probe (/health/ready) distinguishes API-unavailable vs
 *   read-only/baseline DB vs timeout vs daemon-stopped vs operation failure.
 * - Polls immediately after enqueue (no dead first interval), then every 2s.
 * - Active operation IDs persist in localStorage keyed by scope so monitoring
 *   survives navigation and full page reloads.
 * - Handles queued / running / partial / completed / failed / conflict.
 * - Polling failures are bounded (MAX_CONSECUTIVE_POLL_FAILURES) and total
 *   wait is bounded (MAX_TOTAL_WAIT_MS) — the UI can never spin forever.
 * - Route transitions pause intervals WITHOUT cancelling backend work; the
 *   operation keeps running server-side and monitoring resumes on return.
 * - An operation stuck in 'queued' past QUEUED_DAEMON_THRESHOLD_MS surfaces a
 *   daemon-not-running message with the exact command to start it.
 * - All connectivity errors include the resolved API URL and an actionable
 *   fix instead of a generic "Failed to fetch".
 */

import { api } from '../api/endpoints.js';
import { getApiBaseUrl } from '../api/client.js';

export const POLL_INTERVAL_MS = 2000;
export const MAX_CONSECUTIVE_POLL_FAILURES = 5;
export const MAX_TOTAL_WAIT_MS = 30 * 60 * 1000; // 30 minutes
export const QUEUED_DAEMON_THRESHOLD_MS = 60 * 1000; // queued > 60s → daemon likely down
export const READINESS_TIMEOUT_MS = 5000;
export const OPERATIONS_STORAGE_KEY = 'hermes_active_operations';

export const DAEMON_START_HINT = 'python -m app.runtime.runner';
export const API_START_HINT = 'python -m app.api.server --port 8765';

function _now() {
  return Date.now();
}

/**
 * Turns an ApiError (or anything) into a user-actionable message that always
 * includes the resolved API base URL.
 */
export function describeApiError(err) {
  const baseUrl = getApiBaseUrl();
  if (err && err.isTimeout) {
    return `The HERMES API at ${baseUrl} did not respond in time. Verify the API server is running (${API_START_HINT}).`;
  }
  if (err && err.isAborted) {
    return 'The request was cancelled.';
  }
  if (err && err.status === 409) {
    return (err.message || 'An active refresh operation is already queued or running for this scope.') + ' Wait for it to finish, then retry.';
  }
  if (err && err.isNetworkError) {
    return `Cannot reach the HERMES API at ${baseUrl}. Start it with: ${API_START_HINT} — or fix the stored URL: localStorage.setItem('hermes_api_url', 'http://127.0.0.1:8765')`;
  }
  if (err && err.message) {
    return err.message;
  }
  return String(err);
}

export class OperationManager {
  constructor() {
    this.activeOperations = new Map(); // scope -> { operationId, startedAt, intervalId, consecutiveFailures }
    this.listeners = new Map(); // scope -> Set of callbacks
  }

  /**
   * Subscribes a listener to a scope.
   */
  subscribe(scope, callback) {
    if (!this.listeners.has(scope)) {
      this.listeners.set(scope, new Set());
    }
    this.listeners.get(scope).add(callback);
    return () => {
      const set = this.listeners.get(scope);
      if (set) {
        set.delete(callback);
      }
    };
  }

  /**
   * Notifies listeners of state updates.
   */
  notify(scope, data) {
    const set = this.listeners.get(scope);
    if (set) {
      for (const cb of set) {
        try {
          cb(data);
        } catch (e) {
          console.error("Error in OperationManager listener:", e);
        }
      }
    }
  }

  /**
   * Pre-Sync readiness probe against /health/ready (raw request, no route
   * lifecycle). Returns a structured verdict so callers can distinguish:
   *   api_unavailable | timeout | read_only_db | ready (with daemon flag)
   */
  async probeReadiness(options = {}) {
    try {
      const data = await api.raw('/health/ready', { timeoutMs: options.readinessTimeoutMs || READINESS_TIMEOUT_MS });
      return {
        ok: true,
        apiReachable: true,
        daemonAlive: Boolean(data && data.daemon_heartbeat_alive),
        dbWritable: Boolean(!data || data.database_writable !== false),
        isBaseline: Boolean(data && data.is_baseline),
        data,
      };
    } catch (err) {
      if (err && err.status === 503) {
        return {
          ok: false,
          apiReachable: true,
          message: 'read_only_db',
          detail: (err.data && err.data.detail) || err.message,
          error: err,
        };
      }
      if (err && err.isTimeout) {
        return { ok: false, apiReachable: false, message: 'timeout', error: err };
      }
      return { ok: false, apiReachable: false, message: 'api_unavailable', error: err };
    }
  }

  /**
   * Enqueues and monitors a refresh operation.
   * @param {string} scope - The refresh scope (e.g. 'daily_refresh', 'project_scan')
   * @param {string} [idempotencyKey] - Optional key
   * @param {Object} [options] - Extra options (targetId for targeted scopes)
   * @returns {Promise<Object>} The enqueued operation record
   */
  async startRefresh(scope, idempotencyKey = null, options = {}) {
    const idKey = idempotencyKey || `idemp-${scope}-${Date.now()}`;

    // Pre-flight: probe readiness so failures are truthful and actionable.
    this.notify(scope, { status: 'queued', progress: 0, message: 'Checking API readiness...' });
    const ready = await this.probeReadiness(options);
    if (!ready.ok) {
      let error;
      if (ready.message === 'read_only_db') {
        error = `Sync refused: the API is operating on the read-only baseline database. ${ready.detail || 'Point HERMES_DB_PATH at the writable runtime database and restart the API.'}`;
      } else {
        error = describeApiError(ready.error);
      }
      this.notify(scope, { status: 'failed', error });
      const e = new Error(error);
      e.cause = ready.error;
      throw e;
    }
    if (!ready.daemonAlive) {
      this.notify(scope, {
        status: 'queued',
        daemonWarning: true,
        message: `The background daemon is not reporting a live heartbeat — the operation will wait in the queue until it starts (${DAEMON_START_HINT}).`,
      });
    }

    this.notify(scope, { status: 'queued', progress: 0, message: 'Enqueuing refresh...' });

    try {
      const op = await api.enqueueRefresh(scope, idKey, options);
      this.monitor(scope, op.id);
      return op;
    } catch (err) {
      this.notify(scope, { status: 'failed', error: describeApiError(err) });
      throw err;
    }
  }

  /**
   * Starts monitoring an existing operation by ID. Polls immediately, then
   * every POLL_INTERVAL_MS. Replaces any existing monitor for the scope.
   */
  monitor(scope, operationId) {
    const existing = this.activeOperations.get(scope);
    if (existing && existing.intervalId !== null) {
      clearInterval(existing.intervalId);
    }
    const state = {
      operationId,
      startedAt: (existing && existing.startedAt) || _now(),
      intervalId: null,
      consecutiveFailures: 0,
    };
    this.activeOperations.set(scope, state);
    this._persist();
    this._attachPolling(scope);
  }

  /**
   * Attaches the polling interval for an active entry. Safe to call repeatedly.
   */
  _attachPolling(scope) {
    const state = this.activeOperations.get(scope);
    if (!state || state.intervalId !== null) return;

    const poll = async () => {
      const current = this.activeOperations.get(scope);
      if (!current) return;

      let op;
      try {
        op = await api.getOperation(current.operationId);
        current.consecutiveFailures = 0;
      } catch (err) {
        current.consecutiveFailures = (current.consecutiveFailures || 0) + 1;
        if (current.consecutiveFailures >= MAX_CONSECUTIVE_POLL_FAILURES) {
          this._settle(scope, {
            status: 'failed',
            error: `Lost contact with the HERMES API while tracking this operation. ${describeApiError(err)}`,
          });
        } else {
          this.notify(scope, {
            status: 'reconnecting',
            message: `Reconnecting to the API (${current.consecutiveFailures}/${MAX_CONSECUTIVE_POLL_FAILURES})...`,
          });
        }
        return;
      }

      if (op.status === 'completed') {
        this._settle(scope, { status: 'completed', operation: op });
        return;
      }
      if (op.status === 'failed' || op.status === 'conflict') {
        this._settle(scope, {
          status: 'failed',
          error: op.error_summary || `Operation ${op.status}.`,
          operation: op,
        });
        return;
      }

      // queued / running / partial — still in progress.
      const payload = { status: op.status, operation: op };
      if (op.status === 'queued' && _now() - current.startedAt > QUEUED_DAEMON_THRESHOLD_MS) {
        payload.daemonWarning = true;
        payload.message = `Still queued — the background daemon does not appear to be running. Start it with: ${DAEMON_START_HINT}`;
      }
      if (_now() - current.startedAt > MAX_TOTAL_WAIT_MS) {
        this._settle(scope, {
          status: 'failed',
          error: `Stopped waiting after ${Math.round(MAX_TOTAL_WAIT_MS / 60000)} minutes. The operation may still finish in the background — check the Runtime view.`,
          operation: op,
        });
        return;
      }
      this.notify(scope, payload);
    };

    state.intervalId = setInterval(poll, POLL_INTERVAL_MS);
    // Poll immediately so the UI gets first state without waiting a full interval.
    poll();
  }

  /**
   * Terminal settle: stop polling, drop tracking + persistence, notify.
   */
  _settle(scope, payload) {
    const state = this.activeOperations.get(scope);
    if (state && state.intervalId !== null) {
      clearInterval(state.intervalId);
    }
    this.activeOperations.delete(scope);
    this._persist();
    this.notify(scope, payload);
  }

  /**
   * Pauses polling for a scope WITHOUT cancelling the backend operation.
   * Used on route transitions; the operation keeps running server-side and
   * the persisted ID lets monitoring resume later.
   */
  pauseMonitoring(scope) {
    const state = this.activeOperations.get(scope);
    if (state && state.intervalId !== null) {
      clearInterval(state.intervalId);
      state.intervalId = null;
    }
  }

  /**
   * Pauses all polling (route transitions / teardown). Backend work continues.
   */
  pauseAllMonitoring() {
    for (const scope of Array.from(this.activeOperations.keys())) {
      this.pauseMonitoring(scope);
    }
  }

  /**
   * Resumes polling for a paused scope (e.g. returning to its view).
   */
  resumeMonitoring(scope) {
    const state = this.activeOperations.get(scope);
    if (state && state.intervalId === null) {
      this._attachPolling(scope);
    }
  }

  /**
   * Restores monitoring for operations persisted in localStorage (survives
   * navigation and full page reloads). Call once at app startup.
   */
  resumePersistedOperations() {
    if (typeof window === 'undefined' || !window.localStorage) return;
    let persisted = {};
    try {
      persisted = JSON.parse(window.localStorage.getItem(OPERATIONS_STORAGE_KEY) || '{}') || {};
    } catch {
      persisted = {};
    }
    for (const [scope, entry] of Object.entries(persisted)) {
      if (!entry || !entry.operationId) continue;
      if (!this.activeOperations.has(scope)) {
        this.activeOperations.set(scope, {
          operationId: entry.operationId,
          startedAt: entry.startedAt || _now(),
          intervalId: null,
          consecutiveFailures: 0,
        });
      }
      this._attachPolling(scope);
    }
  }

  /**
   * Persists active operation IDs keyed by scope.
   */
  _persist() {
    if (typeof window === 'undefined' || !window.localStorage) return;
    const payload = {};
    for (const [scope, state] of this.activeOperations.entries()) {
      payload[scope] = { operationId: state.operationId, startedAt: state.startedAt };
    }
    try {
      if (Object.keys(payload).length > 0) {
        window.localStorage.setItem(OPERATIONS_STORAGE_KEY, JSON.stringify(payload));
      } else {
        window.localStorage.removeItem(OPERATIONS_STORAGE_KEY);
      }
    } catch {
      // Storage unavailable — monitoring still works for this page lifetime.
    }
  }

  /**
   * Checks if an operation is currently tracked for a scope (active or paused).
   */
  isActive(scope) {
    return this.activeOperations.has(scope);
  }
}

export const operationManager = new OperationManager();
