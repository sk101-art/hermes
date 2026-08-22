/**
 * HERMES API Endpoints
 * Structured service calls mapping to backend FastAPI transport contracts.
 */

import { request } from './client.js';

export const api = {
  // System & Health
  health: () => request('/health'),
  runtime: () => request('/runtime'),
  sources: () => request('/sources'),

  // Inbox & Feed
  getInbox: (params = { limit: 40 }) => request('/inbox', { params }),
  getBriefing: (params = {}) => request('/briefing', { params }),

  // Stories & Claims
  getStory: (clusterId) => request(`/stories/${encodeURIComponent(clusterId)}`),
  getClaim: (claimId) => request(`/claims/${encodeURIComponent(claimId)}`),

  // Search & Query
  search: (query, params = {}) => {
    return request('/search', {
      params: { q: query, limit: 30, explain: true, ...params },
    });
  },

  // Projects & Context
  getProjects: () => request('/projects'),
  getProject: (projectId) => request(`/projects/${encodeURIComponent(projectId)}`),
  getProjectIntelligence: (projectId, params = {}) => request(`/projects/${encodeURIComponent(projectId)}/intelligence`, { params }),

  // Saved Library (Phase 4 Contract)
  getSavedItems: (params = { limit: 50, include_current: false }) => {
    return request('/saved', { params });
  },
  saveItem: (data) => {
    return request('/saved', {
      method: 'POST',
      body: data,
    });
  },
  unsaveItem: (savedId) => {
    return request(`/saved/${encodeURIComponent(savedId)}`, {
      method: 'DELETE',
    });
  },

  // Longitudinal Changes
  getChanges: (params = { hours: 168, limit: 40 }) => request('/changes', { params }),
};

export default api;
