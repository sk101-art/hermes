/**
 * HERMES Hash Router
 * Lightweight, accessible hash-based router supporting deep links.
 * Works seamlessly in static local/Vite environments without server rewrite dependencies.
 */

export class Router {
  constructor() {
    this.routes = new Map();
    this.currentRoute = { path: 'today', params: {}, rawHash: '' };
    this.listeners = new Set();
    this._handleHashChange = this._handleHashChange.bind(this);
  }

  /**
   * Register a route handler or pattern.
   * @param {string} path - e.g. "today", "story/:id", "search"
   * @param {Function} handler 
   */
  on(path, handler) {
    this.routes.set(path, handler);
    return this;
  }

  /**
   * Subscribe to route change events.
   * @param {(route: { path: string, params: Object, rawHash: string }) => void} listener 
   * @returns {() => void} Unsubscribe function
   */
  subscribe(listener) {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  /**
   * Starts listening to hashchange events and executes the initial route.
   */
  init() {
    if (typeof window === 'undefined') return;
    window.addEventListener('hashchange', this._handleHashChange);
    this._handleHashChange();
  }

  /**
   * Programmatic navigation.
   * @param {string} target - e.g. "today", "story/cluster:123", "search?q=vllm"
   */
  navigate(target) {
    if (typeof window === 'undefined') return;
    const cleanTarget = target.replace(/^#\/?/, '');
    window.location.hash = `/${cleanTarget}`;
  }

  /**
   * Destroy router event listeners.
   */
  destroy() {
    if (typeof window === 'undefined') return;
    window.removeEventListener('hashchange', this._handleHashChange);
    this.listeners.clear();
  }

  _handleHashChange() {
    const rawHash = typeof window !== 'undefined' ? window.location.hash : '';
    const clean = rawHash.replace(/^#\/?/, '').trim();
    
    let path = 'today';
    const params = {};

    if (clean) {
      // Check query string
      const [pathPart, queryPart] = clean.split('?');
      if (queryPart) {
        const searchParams = new URLSearchParams(queryPart);
        for (const [k, v] of searchParams.entries()) {
          params[k] = v;
        }
      }

      // Check parametric routes e.g. story/cluster:123
      const segments = pathPart.split('/');
      if (segments.length >= 2 && segments[0] === 'story') {
        path = 'story';
        params.storyId = segments.slice(1).join('/');
      } else {
        path = segments[0] || 'today';
      }
    }

    this.currentRoute = { path, params, rawHash };

    // Execute matching route handler
    const handler = this.routes.get(path) || this.routes.get('*');
    if (handler) {
      handler(this.currentRoute);
    }

    // Notify subscribers
    for (const listener of this.listeners) {
      listener(this.currentRoute);
    }
  }
}

export const router = new Router();
export default router;
