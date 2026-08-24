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
};

export default api;
