/**
 * HERMES Application State Store
 * Simple, reactive state container for global UI and connectivity states.
 */

class Store {
  constructor() {
    this.state = {
      view: 'today',
      routeParams: {},
      selectedStoryId: null,
      searchQuery: '',
      connectionStatus: 'unknown', // 'healthy' | 'degraded' | 'offline' | 'unknown'
      isOffline: false,
      lastError: null,
      isLoading: false,
      viewData: {},
    };
    this.listeners = new Set();
  }

  getState() {
    return this.state;
  }

  setState(partial) {
    this.state = { ...this.state, ...partial };
    this.notify();
  }

  subscribe(listener) {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  notify() {
    for (const listener of this.listeners) {
      listener(this.state);
    }
  }

  setConnection(status, error = null) {
    this.setState({
      connectionStatus: status,
      isOffline: status === 'offline',
      lastError: error,
    });
  }

  setViewData(viewKey, data) {
    this.setState({
      viewData: {
        ...this.state.viewData,
        [viewKey]: data,
      },
    });
  }
}

export const store = new Store();
export default store;
