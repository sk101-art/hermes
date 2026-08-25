/**
 * HERMES Operation Manager
 * Manages background task enqueueing, active status polling, and callback hooks.
 */

import { api } from '../api/endpoints.js';

export class OperationManager {
  constructor() {
    this.activeOperations = new Map(); // scope -> operation details
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
   * Enqueues and monitors a refresh operation.
   * @param {string} scope - The refresh scope (e.g. 'daily_refresh', 'project_scan')
   * @param {string} [idempotencyKey] - Optional key
   * @returns {Promise<Object>} The final completed operation record
   */
  async startRefresh(scope, idempotencyKey = null) {
    const idKey = idempotencyKey || `idemp-${scope}-${Date.now()}`;
    
    this.notify(scope, { status: 'queued', progress: 0, message: 'Enqueuing refresh...' });

    try {
      const op = await api.enqueueRefresh(scope, idKey);
      this.monitor(scope, op.id);
      return op;
    } catch (err) {
      this.notify(scope, { status: 'failed', error: err.message || String(err) });
      throw err;
    }
  }

  /**
   * Starts monitoring an existing operation by ID.
   */
  monitor(scope, operationId) {
    if (this.activeOperations.has(scope)) {
      clearInterval(this.activeOperations.get(scope).intervalId);
    }

    const intervalId = setInterval(async () => {
      try {
        const op = await api.getOperation(operationId);
        
        if (op.status === 'completed') {
          clearInterval(intervalId);
          this.activeOperations.delete(scope);
          this.notify(scope, { status: 'completed', operation: op });
        } else if (op.status === 'failed') {
          clearInterval(intervalId);
          this.activeOperations.delete(scope);
          this.notify(scope, { status: 'failed', error: op.error_summary || 'Operation failed' });
        } else {
          this.notify(scope, { status: op.status, operation: op });
        }
      } catch (err) {
        console.warn("Polling operation status failed:", err);
      }
    }, 2000);

    this.activeOperations.set(scope, { operationId, intervalId });
  }

  /**
   * Checks if an operation is currently active for a scope.
   */
  isActive(scope) {
    return this.activeOperations.has(scope);
  }
}

export const operationManager = new OperationManager();
