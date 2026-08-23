/**
 * HERMES Frontend Application Root
 * Architecture: Modular ES Modules + Hash Deep-Linking Router + Observability Store.
 */

import './styles/index.css';
import { api } from './api/endpoints.js';
import { getApiBaseUrl } from './api/client.js';
import { router } from './state/router.js';
import { store } from './state/store.js';
import { renderShell } from './components/shell.js';
import {
  trapFocus,
  announceToScreenReader,
  focusPageHeading,
  openMobileDrawer,
  closeMobileDrawer,
  VIEW_TITLES
} from './utils/a11y.js';
export { VIEW_TITLES, openMobileDrawer, closeMobileDrawer, focusPageHeading };

// Views
import { renderTodayView } from './views/today.js';
import { renderBriefingView } from './views/briefing.js';
import { renderSearchView } from './views/search.js';
import { renderProjectsView } from './views/projects.js';
import { renderSavedView } from './views/saved.js';
import { renderChangesView } from './views/changes.js';
import { renderRuntimeView } from './views/runtime.js';
import { renderStoryDetailView } from './views/story-detail.js';

const appRoot = document.getElementById('app');

/**
 * Mount and initialize the HERMES Application.
 */
export function initApp() {
  if (!appRoot) return;

  // Initial shell render
  appRoot.innerHTML = renderShell(store.getState());

  // Bind shell-level interactive elements
  bindShellEvents();

  // Subscribe store changes to update shell indicators (connection, banner, active nav)
  store.subscribe((state) => {
    updateShellState(state);
  });

  // Register routes with the router
  setupRoutes();

  // Check initial backend health
  checkBackendHealth();

  // Initialize router
  router.init();

  // Setup global shortcuts (e.g. Cmd+K / Ctrl+K for search)
  setupKeyboardShortcuts();
}

/**
 * Configure view routes in the Hash Router.
 */
function setupRoutes() {
  router
    .on('today', (route) => loadView('today', renderTodayView, route.params))
    .on('briefing', (route) => loadView('briefing', renderBriefingView, route.params))
    .on('search', (route) => loadView('search', renderSearchView, route.params))
    .on('projects', (route) => loadView('projects', renderProjectsView, route.params))
    .on('saved', (route) => loadView('saved', renderSavedView, route.params))
    .on('changes', (route) => loadView('changes', renderChangesView, route.params))
    .on('runtime', (route) => loadView('runtime', renderRuntimeView, route.params))
    .on('story', (route) => loadView('story', renderStoryDetailView, route.params))
    .on('*', () => router.navigate('today'));
}

let lastActiveElementBeforeStory = null;
let lastInitiatingStoryId = null;

/**
 * Loads and renders an active view into the main content viewport.
 */
async function loadView(viewKey, renderFn, routeParams = {}) {
  const isEnteringStory = viewKey === 'story';
  const isLeavingStory = store.getState().view === 'story' && viewKey !== 'story';

  if (isEnteringStory && typeof document !== 'undefined') {
    lastActiveElementBeforeStory = document.activeElement;
    if (routeParams.id) {
      lastInitiatingStoryId = routeParams.id;
    }
  }

  store.setState({ view: viewKey, routeParams });
  
  // Close mobile drawer if open
  closeMobileDrawer(false);

  const contentContainer = document.getElementById('main-content');
  if (!contentContainer) return;

  // Update document title
  const pageTitle = VIEW_TITLES[viewKey] || 'Intelligence Engine';
  if (typeof document !== 'undefined') {
    document.title = `HERMES | ${pageTitle}`;
  }

  // Render view
  await renderFn(contentContainer, store, routeParams);

  // Bind view-level interactive elements (retry, cards)
  bindViewInteractions(contentContainer);

  // Focus management: restore to initiating card/link if returning from story, else focus h1/container
  if (isLeavingStory && typeof document !== 'undefined') {
    let restored = false;
    if (lastActiveElementBeforeStory && document.body.contains(lastActiveElementBeforeStory) && typeof lastActiveElementBeforeStory.focus === 'function') {
      lastActiveElementBeforeStory.focus();
      restored = true;
    } else if (lastInitiatingStoryId) {
      const escapedId = typeof CSS !== 'undefined' && CSS.escape ? CSS.escape(lastInitiatingStoryId) : lastInitiatingStoryId;
      const targetLink = contentContainer.querySelector(
        `[data-story-id="${escapedId}"] .story-title-link, ` +
        `[data-result-id="${escapedId}"] .search-result-title-link, ` +
        `[data-saved-id] a[href*="${encodeURIComponent(lastInitiatingStoryId)}"], ` +
        `[data-cluster-id="${escapedId}"] a, ` +
        `a[href*="#/story/${encodeURIComponent(lastInitiatingStoryId)}"]`
      );
      if (targetLink && typeof targetLink.focus === 'function') {
        targetLink.focus();
        restored = true;
      }
    }
    lastInitiatingStoryId = null;
    lastActiveElementBeforeStory = null;
    if (!restored) {
      focusPageHeading(contentContainer);
    }
  } else {
    focusPageHeading(contentContainer);
  }

  // Announce view transition to screen readers
  announceToScreenReader(`Navigated to ${pageTitle}`);
}

/**
 * Updates dynamic shell elements without re-rendering the whole shell.
 */
function updateShellState(state) {
  if (typeof document === 'undefined') return;

  // Update active nav link
  const navLinks = document.querySelectorAll('.nav-link');
  navLinks.forEach((link) => {
    const navId = link.getAttribute('data-nav-id');
    const isActive = state.view === navId;
    link.classList.toggle('active', isActive);
    if (isActive) {
      link.setAttribute('aria-current', 'page');
    } else {
      link.removeAttribute('aria-current');
    }
  });

  // Update connection status indicators
  const dots = document.querySelectorAll('.connection-indicator .status-dot, #btn-api-status .status-dot');
  dots.forEach((dot) => {
    dot.className = `status-dot ${state.connectionStatus || 'unknown'}`;
  });

  const connectionLabel = document.querySelector('.connection-indicator span:last-child');
  if (connectionLabel) {
    connectionLabel.textContent = state.connectionStatus === 'healthy'
      ? 'Local API · Online'
      : (state.connectionStatus === 'degraded' ? 'Local API · Degraded' : (state.connectionStatus === 'offline' ? 'Local API · Offline' : 'Connecting…'));
  }
}

/**
 * Bind event listeners for global shell controls.
 */
function bindShellEvents() {
  const refreshBtn = document.getElementById('btn-refresh');
  refreshBtn?.addEventListener('click', () => {
    router._handleHashChange();
    checkBackendHealth();
  });

  const apiStatusBtn = document.getElementById('btn-api-status');
  apiStatusBtn?.addEventListener('click', () => {
    const baseUrl = getApiBaseUrl();
    window.open(`${baseUrl}/docs`, '_blank', 'noopener,noreferrer');
  });

  const mobileToggle = document.getElementById('mobile-menu-toggle');
  const sidebar = document.getElementById('app-sidebar');
  const closeBtn = document.getElementById('sidebar-close-btn');
  const backdrop = document.getElementById('sidebar-backdrop');

  mobileToggle?.addEventListener('click', (e) => {
    e.stopPropagation();
    const isOpen = sidebar?.classList.contains('open');
    if (isOpen) {
      closeMobileDrawer(true);
    } else {
      openMobileDrawer();
    }
  });

  closeBtn?.addEventListener('click', () => {
    closeMobileDrawer(true);
  });

  backdrop?.addEventListener('click', () => {
    closeMobileDrawer(true);
  });

  // Close drawer when any nav-link inside sidebar is clicked
  sidebar?.querySelectorAll('.nav-link').forEach((link) => {
    link.addEventListener('click', () => {
      if (sidebar.classList.contains('open')) {
        closeMobileDrawer(false);
      }
    });
  });

  // Handle skip link click navigation explicitly for single-page app accessibility
  document.addEventListener('click', (e) => {
    const skipLink = e.target.closest('.skip-link');
    if (skipLink) {
      e.preventDefault();
      const href = skipLink.getAttribute('href') || '';
      const targetId = href.startsWith('#') ? href.slice(1) : href;
      const targetEl = targetId ? document.getElementById(targetId) : null;
      if (targetEl) {
        targetEl.setAttribute('tabindex', '-1');
        targetEl.focus();
      }
    }
    if (sidebar?.classList.contains('open')) {
      const isClickInside = sidebar.contains(e.target) || mobileToggle?.contains(e.target);
      if (!isClickInside) {
        closeMobileDrawer(false);
      }
    }
  });
}

/**
 * Bind view-level controls.
 */
function bindViewInteractions(container) {
  // Retry buttons in error/offline states
  const retryBtn = container.querySelector('#retry-btn');
  retryBtn?.addEventListener('click', () => {
    router._handleHashChange();
    checkBackendHealth();
  });
}

/**
 * Setup keyboard shortcuts (Cmd+K / Ctrl+K for search, Escape to close drawer).
 */
function setupKeyboardShortcuts() {
  if (typeof window === 'undefined') return;

  window.addEventListener('keydown', (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
      e.preventDefault();
      router.navigate('search');
    }

    if (e.key === 'Escape') {
      closeMobileDrawer(true);
    }
  });
}

/**
 * Check backend connection on boot.
 */
async function checkBackendHealth() {
  try {
    const health = await api.health();
    const isOk = health.status === 'healthy' || health.status === 'ok';
    store.setConnection(isOk ? 'healthy' : 'degraded');
  } catch (err) {
    store.setConnection(err.isNetworkError ? 'offline' : 'degraded', err.message);
  }
}

// Auto-boot if running in browser
if (typeof window !== 'undefined' && typeof document !== 'undefined') {
  initApp();
}

export default { initApp };
