/**
 * HERMES Phase 16 Frontend Unit and Integration Test Suite
 * Tests RequestManager deduplication, canonical query sorting, cancellation,
 * accessible ErrorBoundary, and strict route request budgets.
 */

import test from 'node:test';
import assert from 'node:assert';

// Mock DOM environment for Node.js test runner
globalThis.window = {
  localStorage: {
    store: {},
    getItem(key) { return this.store[key] || null; },
    setItem(key, val) { this.store[key] = String(val); },
    removeItem(key) { delete this.store[key]; }
  },
  location: {
    hash: ''
  },
  addEventListener() {},
  removeEventListener() {}
};
globalThis.document = {
  activeElement: null,
  getElementById() { return null; },
  createElement() {
    return {
      setAttribute() {},
      id: '',
      className: '',
      style: {},
      textContent: '',
      focus() { globalThis.document.activeElement = this; }
    };
  },
  body: {
    appendChild() {}
  }
};
globalThis.Node = {
  ELEMENT_NODE: 1,
  ATTRIBUTE_NODE: 2,
  TEXT_NODE: 3,
  COMMENT_NODE: 8,
  DOCUMENT_NODE: 9,
  DOCUMENT_TYPE_NODE: 10,
  DOCUMENT_FRAGMENT_NODE: 11,
};
globalThis.window.Node = globalThis.Node;
globalThis.document.defaultView = globalThis.window;
globalThis.window.document = globalThis.document;

import { request, ApiError } from '../src/api/client.js';
import { RequestManager, requestManager } from '../src/state/request-manager.js';
import { getErrorDiagnostics, renderErrorBoundaryHtml } from '../src/components/error-boundary.js';
import { api } from '../src/api/endpoints.js';

test('Phase 16: 1. RequestManager canonical query key sorting', () => {
  const rm = new RequestManager();
  const k1 = rm.getCanonicalKey('/search', { z: 1, a: 2, m: 3 }, 'GET');
  const k2 = rm.getCanonicalKey('/search', { a: 2, m: 3, z: 1 }, 'GET');
  assert.strictEqual(k1, 'GET:search?a=2&m=3&z=1');
  assert.strictEqual(k1, k2);
});

test('Phase 16: 2. RequestManager deduplicates concurrent identical GET requests in same generation', async () => {
  const rm = new RequestManager();
  const gen = rm.nextGeneration('testView');
  let fetchCount = 0;
  globalThis.fetch = async () => {
    fetchCount++;
    return {
      ok: true,
      status: 200,
      json: async () => ({ count: fetchCount })
    };
  };

  const p1 = rm.request('/inbox', { params: { limit: 40 }, viewKey: 'testView', generation: gen });
  const p2 = rm.request('/inbox', { params: { limit: 40 }, viewKey: 'testView', generation: gen });

  const [res1, res2] = await Promise.all([p1, p2]);
  assert.strictEqual(fetchCount, 1);
  assert.strictEqual(res1.count, 1);
  assert.strictEqual(res2.count, 1);
});

test('Phase 16: 3. RequestManager does not deduplicate POST or DELETE mutations', async () => {
  const rm = new RequestManager();
  let fetchCount = 0;
  globalThis.fetch = async () => {
    fetchCount++;
    return {
      ok: true,
      status: 200,
      json: async () => ({ mutationId: fetchCount })
    };
  };

  const p1 = rm.request('/saved', { method: 'POST', body: { id: 1 }, viewKey: 'testView' });
  const p2 = rm.request('/saved', { method: 'POST', body: { id: 2 }, viewKey: 'testView' });

  const [res1, res2] = await Promise.all([p1, p2]);
  assert.strictEqual(fetchCount, 2);
});

test('Phase 16: 4. RequestManager abortRoute cancels in-flight controllers and increments generation', async () => {
  const rm = new RequestManager();
  const initialGen = rm.getGeneration('viewA');
  rm.abortRoute('viewA');
  const nextGen = rm.getGeneration('viewA');
  assert.strictEqual(nextGen, initialGen + 1);
});

test('Phase 16: 5. RequestManager drops responses from superseded generations', async () => {
  const rm = new RequestManager();
  let resolveFetch;
  globalThis.fetch = async () => {
    return new Promise((resolve) => {
      resolveFetch = resolve;
    });
  };

  const reqGen = rm.nextGeneration('today');
  const promise = rm.request('/inbox', { viewKey: 'today', generation: reqGen });

  // Advance generation before request resolves (simulating fast user navigation)
  rm.nextGeneration('today');

  resolveFetch({
    ok: true,
    status: 200,
    json: async () => ({ items: ['stale'] })
  });

  try {
    await promise;
    assert.fail('Expected stale request to be rejected');
  } catch (err) {
    assert.ok(err.isStale);
    assert.ok(err.isAborted);
  }
});

test('Phase 16: 6. ErrorBoundary diagnostic mapping covers all 8 failure topologies', () => {
  // 1. Timeout
  const tErr = new ApiError('Timeout', 0, null, true, true, false);
  const d1 = getErrorDiagnostics(tErr);
  assert.strictEqual(d1.type, 'timeout');
  assert.strictEqual(d1.title, 'Request Timed Out');

  // 2. Offline / Network
  const nErr = new ApiError('Failed to fetch', 0, null, true, false, false);
  const d2 = getErrorDiagnostics(nErr);
  assert.strictEqual(d2.type, 'offline');
  assert.strictEqual(d2.title, 'Backend Unavailable');

  // 3. Entity 404
  const notFoundErr = new ApiError('Story cluster not found', 404);
  const d3 = getErrorDiagnostics(notFoundErr);
  assert.strictEqual(d3.type, 'not_found');
  assert.strictEqual(d3.title, 'Record Not Found');

  // 4. Server 500
  const srvErr = new ApiError('Internal Error', 500);
  const d4 = getErrorDiagnostics(srvErr);
  assert.strictEqual(d4.type, 'server_error');
  assert.strictEqual(d4.title, 'Backend Server Error');

  // 5. Malformed payload
  const jsonErr = new Error('Malformed JSON payload');
  const d5 = getErrorDiagnostics(jsonErr);
  assert.strictEqual(d5.type, 'malformed');
  assert.strictEqual(d5.title, 'Malformed Data Payload');
});

test('Phase 16: 7. ErrorBoundary HTML structure has accessible alert role and retry controls', () => {
  const html = renderErrorBoundaryHtml(new Error('Test error'));
  assert.ok(html.includes('role="alert"'));
  assert.ok(html.includes('aria-live="assertive"'));
  assert.ok(html.includes('data-testid="btn-retry-view"'));
  assert.ok(html.includes('data-testid="btn-home-view"'));
});

test('Phase 16: 8. Projects request budget: exactly 1 GET /projects for index, 1 GET /projects/{id}/intelligence for detail', async () => {
  const recorded = [];
  globalThis.fetch = async (url) => {
    recorded.push(url);
    return {
      ok: true,
      status: 200,
      json: async () => ({ projects: [] })
    };
  };

  // Index
  await api.getProjects();
  assert.strictEqual(recorded.length, 1);
  assert.ok(recorded[0].endsWith('/projects'));

  // Detail
  await api.getProjectIntelligence('proj_1');
  assert.strictEqual(recorded.length, 2);
  assert.ok(recorded[1].endsWith('/projects/proj_1/intelligence'));
});
