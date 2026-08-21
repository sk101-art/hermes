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
import { trapFocus, announceToScreenReader } from './utils/a11y.js';

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

/**
 * Loads and renders an active view into the main content viewport.
 */
async function loadView(viewKey, renderFn, routeParams = {}) {
  store.setState({ view: viewKey, routeParams });
  
  // Close mobile drawer if open
  closeMobileDrawer();

  const contentContainer = document.getElementById('main-content');
  if (!contentContainer) return;

  // Render view
  await renderFn(contentContainer, store, routeParams);

  // Bind story card interactions within rendered view
  bindViewCardInteractions(contentContainer);

  // Announce view transition to screen readers
  announceToScreenReader(`Navigated to ${viewKey}`);
}

/**
 * Updates dynamic shell elements without re-rendering the whole shell.
 */
function updateShellState(state) {
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
    const currentView = store.getState().view;
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
  
  mobileToggle?.addEventListener('click', () => {
    const isOpen = sidebar?.classList.toggle('open');
    mobileToggle.setAttribute('aria-expanded', String(Boolean(isOpen)));
  });

  // Close sidebar on click outside in mobile view
  document.addEventListener('click', (e) => {
    if (sidebar?.classList.contains('open')) {
      const isClickInside = sidebar.contains(e.target) || mobileToggle?.contains(e.target);
      if (!isClickInside) {
        closeMobileDrawer();
      }
    }
  });
}

function closeMobileDrawer() {
  const sidebar = document.getElementById('app-sidebar');
  const mobileToggle = document.getElementById('mobile-menu-toggle');
  if (sidebar?.classList.contains('open')) {
    sidebar.classList.remove('open');
    mobileToggle?.setAttribute('aria-expanded', 'false');
  }
}

/**
 * Bind click and keyboard events on story cards.
 */
function bindViewCardInteractions(container) {
  const cards = container.querySelectorAll('[data-story-id]');
  cards.forEach((card) => {
    const storyId = card.getAttribute('data-story-id');
    if (!storyId) return;

    card.addEventListener('click', () => {
      router.navigate(`story/${encodeURIComponent(storyId)}`);
    });

    card.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        router.navigate(`story/${encodeURIComponent(storyId)}`);
      }
    });
  });

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
  window.addEventListener('keydown', (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
      e.preventDefault();
      router.navigate('search');
    }

    if (e.key === 'Escape') {
      closeMobileDrawer();
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
