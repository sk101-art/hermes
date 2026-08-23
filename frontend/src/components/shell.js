/**
 * HERMES Application Shell Component
 * Main layout shell: Sidebar, Topbar, Content Viewport, Connection Status, and Mobile Drawer.
 */

import { getIcon } from '../icons/index.js';
import { escapeHtml } from '../utils/adapters.js';

export const NAV_ITEMS = [
  { id: 'today', label: 'Today', icon: 'today', hint: 'Daily incoming intelligence' },
  { id: 'briefing', label: 'Morning Briefing', icon: 'briefing', hint: 'Distilled executive read' },
  { id: 'search', label: 'Search', icon: 'search', hint: 'Query intelligence corpus' },
  { id: 'projects', label: 'My Projects', icon: 'projects', hint: 'Contextual project matches' },
  { id: 'saved', label: 'Saved Library', icon: 'saved', hint: 'Longitudinal saved items' },
  { id: 'changes', label: 'Changes', icon: 'changes', hint: 'Intelligence delta tracking' },
  { id: 'runtime', label: 'Runtime', icon: 'runtime', hint: 'Engine & source health' },
];

/**
 * Render the entire App Shell layout.
 * @param {Object} state - Store state
 * @returns {string} HTML string
 */
export function renderShell(state) {
  const currentNav = NAV_ITEMS.find((n) => n.id === state.view) || NAV_ITEMS[0];
  const connectionClass = state.connectionStatus || 'unknown';
  const connectionLabel = state.connectionStatus === 'healthy'
    ? 'Local API · Online'
    : (state.connectionStatus === 'degraded' ? 'Local API · Degraded' : (state.connectionStatus === 'offline' ? 'Local API · Offline' : 'Connecting…'));

  return `<a href="#main-content" class="skip-link">Skip to main content</a>
  <div class="app-shell">
    <!-- Sidebar Navigation Landmark -->
    <aside class="sidebar" id="app-sidebar" aria-label="Sidebar">
      <div class="brand-section">
        <div class="brand-mark" aria-hidden="true">H</div>
        <div class="brand-info">
          <span class="brand-title">HERMES</span>
          <span class="brand-subtitle">Intelligence Engine</span>
        </div>
        <button class="sidebar-close-btn" id="sidebar-close-btn" aria-label="Close navigation menu">
          ${getIcon('x')}
        </button>
      </div>

      <nav class="nav-section" aria-label="Primary Navigation">
        <div class="nav-label">Workspace</div>
        <ul class="nav-list" role="list">
          ${NAV_ITEMS.map((item) => {
            const isActive = state.view === item.id;
            return `<li class="nav-item" role="listitem">
              <a href="#/${item.id}" 
                 class="nav-link ${isActive ? 'active' : ''}" 
                 data-nav-id="${item.id}"
                 title="${escapeHtml(item.hint)}"
                 ${isActive ? 'aria-current="page"' : ''}>
                <span class="nav-icon-wrapper" aria-hidden="true">${getIcon(item.icon)}</span>
                <span>${escapeHtml(item.label)}</span>
              </a>
            </li>`;
          }).join('')}
        </ul>
      </nav>

      <div class="sidebar-footer">
        <div class="connection-indicator">
          <span class="status-dot ${connectionClass}" aria-hidden="true"></span>
          <span>${escapeHtml(connectionLabel)}</span>
        </div>
        <div class="text-xs text-faint mono" style="margin-top:2px;">
          Local-first · 127.0.0.1
        </div>
      </div>
    </aside>

    <!-- Mobile Drawer Backdrop -->
    <div class="sidebar-backdrop" id="sidebar-backdrop" aria-hidden="true"></div>

    <!-- Main Content Landmark -->
    <div class="main-wrapper" id="app-main-wrapper">
      <header class="topbar" role="banner">
        <div class="breadcrumb-area">
          <button class="mobile-menu-btn" id="mobile-menu-toggle" aria-label="Toggle navigation menu" aria-expanded="false" aria-controls="app-sidebar">
            ${getIcon('menu')}
          </button>
          <span class="breadcrumb-root">HERMES</span>
          <span class="breadcrumb-separator" aria-hidden="true">/</span>
          <span class="breadcrumb-current text-sm text-semibold">${escapeHtml(currentNav.label)}</span>
        </div>

        <div class="topbar-actions">
          <button class="btn-icon" id="btn-refresh" title="Refresh intelligence feed" aria-label="Refresh">
            ${getIcon('refresh')}
          </button>
          <a href="#/search" class="btn-icon" id="btn-top-search" title="Search corpus" aria-label="Search corpus">
            ${getIcon('search')}
          </a>
          <button class="btn btn-secondary btn-sm" id="btn-api-status" title="View backend OpenAPI docs" aria-label="View API Documentation">
            <span class="status-dot ${connectionClass}" aria-hidden="true"></span>
            <span>API Docs</span>
          </button>
        </div>
      </header>

      ${state.isOffline ? `<div class="global-banner global-banner-offline" role="alert">
        ${getIcon('wifiOff')}
        <span>The local HERMES API is unreachable. Running in offline mode.</span>
      </div>` : ''}

      ${state.connectionStatus === 'degraded' ? `<div class="global-banner global-banner-degraded" role="alert">
        ${getIcon('alertTriangle')}
        <span>The local HERMES engine is in a degraded state. Check runtime status for details.</span>
      </div>` : ''}

      <main class="content-area" id="main-content" role="main" tabindex="-1">
        <!-- Dynamic View Content Inserted Here -->
      </main>
    </div>
  </div>`;
}
