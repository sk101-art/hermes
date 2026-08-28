/**
 * HERMES API Endpoints
 * Structured service calls mapping to backend FastAPI transport contracts,
 * routed through centralized requestManager for deduplication, race protection,
 * and route-level cancellation.
 */

import { requestManager } from '../state/request-manager.js';
import { request as baseRequest } from './client.js';

export const api = {
  // Direct base request without route lifecycle (for health check / probes)
  raw: baseRequest,

  // System & Health
  health: (options = {}) => requestManager.request('/health', { viewKey: 'system', ...options }),
  runtime: (options = {}) => requestManager.request('/runtime', { viewKey: 'runtime', ...options }),
  sources: (options = {}) => requestManager.request('/sources', { viewKey: 'runtime', ...options }),

  // Inbox & Feed
  getInbox: (params = { limit: 40 }, options = {}) => {
    return requestManager.request('/inbox', {
      params,
      viewKey: 'today',
      ...options,
    });
  },
  getBriefing: (params = {}, options = {}) => {
    return requestManager.request('/briefing', {
      params,
      viewKey: 'briefing',
      ...options,
    });
  },

  // Stories & Claims
  getStory: (clusterId, options = {}) => {
    return requestManager.request(`/stories/${encodeURIComponent(clusterId)}`, {
      viewKey: 'story',
      ...options,
    });
  },
  getClaim: (claimId, options = {}) => {
    return requestManager.request(`/claims/${encodeURIComponent(claimId)}`, {
      viewKey: 'story',
      ...options,
    });
  },

  // Search & Query
  search: (query, params = {}, options = {}) => {
    return requestManager.request('/search', {
      params: { q: query, limit: 30, explain: true, ...params },
      viewKey: 'search',
      ...options,
    });
  },

  // Projects & Context
  getProjects: (options = {}) => {
    return requestManager.request('/projects', {
      viewKey: 'projects',
      ...options,
    });
  },
  getProject: (projectId, options = {}) => {
    return requestManager.request(`/projects/${encodeURIComponent(projectId)}`, {
      viewKey: 'projects',
      ...options,
    });
  },
  getProjectIntelligence: (projectId, params = {}, options = {}) => {
    return requestManager.request(`/projects/${encodeURIComponent(projectId)}/intelligence`, {
      params,
      viewKey: 'projects',
      ...options,
    });
  },
  getProjectMatchComparison: (projectId, clusterId, options = {}) => {
    return requestManager.request(
      `/projects/${encodeURIComponent(projectId)}/matches/${encodeURIComponent(clusterId)}`,
      {
        viewKey: 'story',
        ...options,
      }
    );
  },

  // Saved Library
  getSavedItems: (params = { limit: 50, include_current: false }, options = {}) => {
    return requestManager.request('/saved', {
      params,
      viewKey: 'saved',
      ...options,
    });
  },
  saveItem: (data, options = {}) => {
    return requestManager.request('/saved', {
      method: 'POST',
      body: data,
      viewKey: 'saved',
      ...options,
    });
  },
  unsaveItem: (savedId, options = {}) => {
    return requestManager.request(`/saved/${encodeURIComponent(savedId)}`, {
      method: 'DELETE',
      viewKey: 'saved',
      ...options,
    });
  },

  // Longitudinal Changes
  getChanges: (params = { hours: 168, limit: 40 }, options = {}) => {
    return requestManager.request('/changes', {
      params,
      viewKey: 'changes',
      ...options,
    });
  },

  // Refresh Operations
  enqueueRefresh: (scope, idempotencyKey = null, options = {}) => {
    const body = { scope, idempotency_key: idempotencyKey };
    if (options.targetId) body.target_id = options.targetId;
    return requestManager.request('/runtime/refresh', {
      method: 'POST',
      body,
      viewKey: options.viewKey || 'runtime',
      ...options,
    });
  },
  getOperation: (operationId, options = {}) => {
    return requestManager.request(`/runtime/operations/${encodeURIComponent(operationId)}`, {
      viewKey: options.viewKey || 'runtime',
      ...options,
    });
  },
  getDailyStatus: (params = {}, options = {}) => {
    return requestManager.request('/daily/status', {
      params,
      viewKey: options.viewKey || 'runtime',
      ...options,
    });
  },

  // Project Management
  addProject: (data, options = {}) => {
    return requestManager.request('/projects', {
      method: 'POST',
      body: data,
      viewKey: 'projects',
      ...options,
    });
  },
  updateProject: (projectId, data, options = {}) => {
    return requestManager.request(`/projects/${encodeURIComponent(projectId)}`, {
      method: 'PUT',
      body: data,
      viewKey: 'projects',
      ...options,
    });
  },
  archiveProject: (projectId, reason = null, options = {}) => {
    const params = reason ? { reason } : {};
    return requestManager.request(`/projects/${encodeURIComponent(projectId)}`, {
      method: 'DELETE',
      params,
      viewKey: 'projects',
      ...options,
    });
  },
  restoreProject: (projectId, options = {}) => {
    return requestManager.request(`/projects/${encodeURIComponent(projectId)}/restore`, {
      method: 'POST',
      viewKey: 'projects',
      ...options,
    });
  },
  // Targeted project scan: enqueued as a project_scan refresh operation that
  // scans ONLY this project (never all projects). Returns a RefreshOperation
  // (202) whose id can be tracked via getOperation.
  scanProject: (projectId, idempotencyKey = null, options = {}) => {
    return requestManager.request('/runtime/refresh', {
      method: 'POST',
      body: {
        scope: 'project_scan',
        target_id: projectId,
        idempotency_key: idempotencyKey,
      },
      viewKey: 'projects',
      ...options,
    });
  },

  // Local folder access (native picker + approvals)
  // Opens the native OS folder dialog; resolves to an opaque selection token.
  // Long timeout: the user may take a while to browse.
  selectFolder: (options = {}) => {
    return requestManager.request('/local/folder-selection', {
      method: 'POST',
      timeoutMs: 320000,
      viewKey: 'projects',
      ...options,
    });
  },
  listFolderApprovals: (options = {}) => {
    return requestManager.request('/local/folder-approvals', {
      viewKey: 'projects',
      ...options,
    });
  },
  replaceFolderApproval: (projectId, selectionToken, options = {}) => {
    return requestManager.request('/local/folder-approvals/replace', {
      method: 'POST',
      body: { project_id: projectId, folder_selection_token: selectionToken },
      viewKey: 'projects',
      ...options,
    });
  },
  revokeFolderApproval: (projectId, options = {}) => {
    return requestManager.request('/local/folder-approvals/revoke', {
      method: 'POST',
      body: { project_id: projectId },
      viewKey: 'projects',
      ...options,
    });
  },
  openFolderInExplorer: (projectId, options = {}) => {
    return requestManager.request('/local/folder-approvals/open', {
      method: 'POST',
      body: { project_id: projectId },
      viewKey: 'projects',
      ...options,
    });
  },
};

export default api;
