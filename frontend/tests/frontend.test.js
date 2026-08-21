/**
 * HERMES Frontend Unit and Integration Test Suite
 * Executed via Node's native test runner (node --test).
 * 
 * Verifies all 18 Phase 5 frontend foundation and truthfulness contracts.
 */

import test from 'node:test';
import assert from 'node:assert';

// Mock DOM environment for testing browser-dependent modules under Node
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
      textContent: ''
    };
  },
  body: {
    appendChild() {}
  }
};
globalThis.localStorage = globalThis.window.localStorage;
try {
  Object.defineProperty(globalThis, 'navigator', {
    value: { onLine: true },
    configurable: true,
    writable: true,
  });
} catch {
  // Ignore if already set or non-configurable
}

// Mock global fetch for API client tests
let fetchMock = null;
globalThis.fetch = async (url, options) => {
  if (fetchMock) {
    return fetchMock(url, options);
  }
  return {
    ok: true,
    status: 200,
    json: async () => ({})
  };
};

// Import modules to test
import { request, ApiError, getApiBaseUrl, setApiBaseUrl } from '../src/api/client.js';
import {
  getVerificationMeta,
  getMaturityMeta,
  MATURITY_MAP,
  getRiskMeta,
  getEvidenceStanceMeta
} from '../src/utils/semantic.js';
import {
  escapeHtml,
  formatDate,
  formatScorePercentage,
  formatScoreDecimal,
  toTitleCase,
  truncateText
} from '../src/utils/adapters.js';
import {
  renderVerificationBadge,
  renderMaturityBadge,
  renderRiskBadge,
  renderEvidenceStanceBadge,
  renderRankingBadge,
  renderSourcePill
} from '../src/components/badges.js';
import {
  renderLoadingState,
  renderEmptyState,
  renderOfflineState,
  renderErrorState,
  renderDegradedState
} from '../src/components/ui-states.js';
import { renderStoryCard } from '../src/components/story-card.js';
import { renderShell, NAV_ITEMS } from '../src/components/shell.js';

/* ==========================================================================
   1. API Client Contracts
   ========================================================================== */

test('API client preserves null values exactly', async () => {
  fetchMock = async (url) => {
    return {
      ok: true,
      status: 200,
      json: async () => ({
        verification_score: null,
        maturity_stage: null,
        risk_score: null,
        why_it_matters: null
      })
    };
  };

  const res = await request('/test-endpoint');
  assert.strictEqual(res.verification_score, null);
  assert.strictEqual(res.maturity_stage, null);
  assert.strictEqual(res.risk_score, null);
  assert.strictEqual(res.why_it_matters, null);
});

test('API client surfaces HTTP errors consistently with ApiError', async () => {
  fetchMock = async () => {
    return {
      ok: false,
      status: 403,
      statusText: 'Forbidden',
      json: async () => ({ detail: 'Access denied to corpus' })
    };
  };

  try {
    await request('/forbidden-route');
    assert.fail('Expected request to throw ApiError');
  } catch (err) {
    assert.ok(err instanceof ApiError);
    assert.strictEqual(err.status, 403);
    assert.strictEqual(err.message, 'Access denied to corpus');
    assert.strictEqual(err.isNetworkError, false);
  }
});

/* ==========================================================================
   2. Canonical Semantic Enums & Display Rules
   ========================================================================== */

test('All seven canonical maturity stages render correctly without default fallback', () => {
  const stages = [
    { key: 'concept', label: 'Concept', css: 'badge-maturity-concept' },
    { key: 'research', label: 'Research', css: 'badge-maturity-research' },
    { key: 'prototype', label: 'Prototype', css: 'badge-maturity-prototype' },
    { key: 'experimental', label: 'Experimental', css: 'badge-maturity-experimental' },
    { key: 'early_adoption', label: 'Early Adoption', css: 'badge-maturity-early_adoption' },
    { key: 'production_candidate', label: 'Production Candidate', css: 'badge-maturity-production_candidate' },
    { key: 'established', label: 'Established', css: 'badge-maturity-established' },
  ];
  
  stages.forEach(({ key, label, css }) => {
    const meta = getMaturityMeta(key);
    assert.strictEqual(meta.label, label);
    assert.strictEqual(meta.cssClass, css);
    
    const rendered = renderMaturityBadge(key);
    assert.ok(rendered.includes(css), `Expected ${css} in rendered maturity badge`);
    assert.ok(rendered.includes(label), `Expected ${label} in rendered maturity badge`);
  });

  // Null input must render "Not assessed"
  const unassessed = getMaturityMeta(null);
  assert.strictEqual(unassessed.label, 'Not assessed');
  assert.strictEqual(unassessed.cssClass, 'badge-maturity-not_assessed');

  // Unknown input must degrade safely to neutral unassessed
  const unknown = getMaturityMeta('unrecognized_future_stage');
  assert.strictEqual(unknown.label, 'Unrecognized Future Stage');
  assert.strictEqual(unknown.cssClass, 'badge-maturity-not_assessed');
});

test('All eight canonical ClaimStatus values render without invented fallback', () => {
  const statuses = [
    { key: 'strongly_supported', label: 'Strongly Supported', css: 'badge-verification-strongly_supported' },
    { key: 'supported', label: 'Supported', css: 'badge-verification-supported' },
    { key: 'weakly_supported', label: 'Weakly Supported', css: 'badge-verification-weakly_supported' },
    { key: 'mixed', label: 'Mixed Evidence', css: 'badge-verification-mixed' },
    { key: 'contradicted', label: 'Contradicted', css: 'badge-verification-contradicted' },
    { key: 'unverified', label: 'Unverified', css: 'badge-verification-unverified' },
    { key: 'superseded', label: 'Superseded', css: 'badge-verification-superseded' },
    { key: 'retracted', label: 'Retracted', css: 'badge-verification-retracted' },
  ];

  statuses.forEach(({ key, label, css }) => {
    const meta = getVerificationMeta(key);
    assert.strictEqual(meta.label, label);
    assert.strictEqual(meta.cssClass, css);
    
    const rendered = renderVerificationBadge(key);
    assert.ok(rendered.includes(label), `Expected ${label} in rendered verification badge`);
    assert.ok(rendered.includes(css), `Expected ${css} in rendered verification badge`);
  });

  // Null input must render "Not assessed"
  const unassessed = getVerificationMeta(null);
  assert.strictEqual(unassessed.label, 'Not assessed');
  assert.strictEqual(unassessed.cssClass, 'badge-verification-not_assessed');

  // Unknown input must degrade neutrally without positive fallback
  const unknown = getVerificationMeta('hypothetical_future_status');
  assert.strictEqual(unknown.label, 'Hypothetical Future Status');
  assert.strictEqual(unknown.cssClass, 'badge-verification-not_assessed');
});

test('Maturity alias normalization preserves neutrality for ungrounded strings', () => {
  // Backend supported aliases
  assert.strictEqual(getMaturityMeta('maturing').label, 'Early Adoption');
  assert.strictEqual(getMaturityMeta('production_ready').label, 'Established');
  assert.strictEqual(getMaturityMeta('stable').label, 'Established');

  // Ungrounded strings (must NOT silently map to established or concept)
  const matureMeta = getMaturityMeta('mature');
  assert.strictEqual(matureMeta.label, 'Mature');
  assert.strictEqual(matureMeta.cssClass, 'badge-maturity-not_assessed');

  const proposalMeta = getMaturityMeta('proposal');
  assert.strictEqual(proposalMeta.label, 'Proposal');
  assert.strictEqual(proposalMeta.cssClass, 'badge-maturity-not_assessed');

  const arbitraryMeta = getMaturityMeta('some_arbitrary_string');
  assert.strictEqual(arbitraryMeta.label, 'Some Arbitrary String');
  assert.strictEqual(arbitraryMeta.cssClass, 'badge-maturity-not_assessed');
});

test('Maturity descriptions contain no unsupported production-readiness claims', () => {
  const forbiddenPhrases = [
    'feature-complete',
    'audit',
    'safe for production',
    'guarantee',
    'lts',
    'production-proven',
    'recommended for deployment',
  ];

  Object.entries(MATURITY_MAP).forEach(([stage, meta]) => {
    const descLower = (meta.description || '').toLowerCase();
    forbiddenPhrases.forEach((phrase) => {
      assert.ok(
        !descLower.includes(phrase),
        `Maturity stage "${stage}" description contains forbidden overreach phrase "${phrase}": ${meta.description}`
      );
    });
  });
});

test('Canonical evidence stances render correctly and unknown stance renders neutrally without context styling', () => {
  const stances = [
    { key: 'supports', label: 'Supports', css: 'badge-stance-supports' },
    { key: 'contradicts', label: 'Contradicts', css: 'badge-stance-contradicts' },
    { key: 'context', label: 'Context', css: 'badge-stance-context' },
  ];

  stances.forEach(({ key, label, css }) => {
    const meta = getEvidenceStanceMeta(key);
    assert.strictEqual(meta.label, label);
    assert.strictEqual(meta.cssClass, css);

    const rendered = renderEvidenceStanceBadge(key);
    assert.ok(rendered.includes(label));
    assert.ok(rendered.includes(css));
  });

  // Explicit check: context never renders as supports
  const contextMeta = getEvidenceStanceMeta('context');
  assert.strictEqual(contextMeta.label, 'Context');
  assert.ok(!contextMeta.cssClass.includes('badge-stance-supports'));
  const renderedContext = renderEvidenceStanceBadge('context');
  assert.ok(renderedContext.includes('Context'));
  assert.ok(!renderedContext.includes('Supports'));

  // Unknown stance degrades neutrally to .badge-stance-unknown (not .badge-stance-context)
  const unknown = getEvidenceStanceMeta('tangential_citation');
  assert.strictEqual(unknown.label, 'Tangential Citation');
  assert.strictEqual(unknown.cssClass, 'badge-stance-unknown');
  assert.ok(!unknown.cssClass.includes('badge-stance-context'));

  const nullStance = getEvidenceStanceMeta(null);
  assert.strictEqual(nullStance.label, 'Unspecified');
  assert.strictEqual(nullStance.cssClass, 'badge-stance-unknown');
  assert.ok(!nullStance.cssClass.includes('badge-stance-context'));

  const renderedUnknown = renderEvidenceStanceBadge('unrecognized_stance');
  assert.ok(renderedUnknown.includes('badge-stance-unknown'));
  assert.ok(!renderedUnknown.includes('badge-stance-context'));
  assert.ok(!renderedUnknown.includes('Context'));
});

test('Risk levels include critical, high, medium, low with accurate status handling', () => {
  // Critical risk
  const critical = getRiskMeta('assessed', 'critical', 0.95);
  assert.strictEqual(critical.label, 'Critical risk (95%)');
  assert.strictEqual(critical.cssClass, 'badge-risk-critical');
  const renderedCrit = renderRiskBadge('assessed', 'critical', 0.95);
  assert.ok(renderedCrit.includes('Critical risk (95%)'));
  assert.ok(renderedCrit.includes('badge-risk-critical'));

  // High risk
  const high = getRiskMeta('assessed', 'high', 0.80);
  assert.strictEqual(high.label, 'High risk (80%)');
  assert.strictEqual(high.cssClass, 'badge-risk-high');

  // Medium risk
  const medium = getRiskMeta('assessed', 'medium', 0.50);
  assert.strictEqual(medium.label, 'Medium risk (50%)');
  assert.strictEqual(medium.cssClass, 'badge-risk-medium');

  // Low risk
  const low = getRiskMeta('assessed', 'low', 0.15);
  assert.strictEqual(low.label, 'Low risk (15%)');
  assert.strictEqual(low.cssClass, 'badge-risk-low');

  // not_assessed risk is NOT rendered as Low
  const notAssessed = getRiskMeta('not_assessed', null);
  assert.strictEqual(notAssessed.label, 'Risk: Not assessed');
  assert.strictEqual(notAssessed.cssClass, 'badge-risk-not_assessed');
  assert.ok(!notAssessed.label.includes('Low'));
  
  const renderedNotAssessed = renderRiskBadge('not_assessed', null);
  assert.ok(renderedNotAssessed.includes('Risk: Not assessed'));
  assert.ok(!renderedNotAssessed.includes('Low'));

  // insufficient_data risk differs from Medium
  const insufficient = getRiskMeta('insufficient_data', null);
  assert.strictEqual(insufficient.label, 'Risk: Insufficient data');
  assert.strictEqual(insufficient.cssClass, 'badge-risk-insufficient_data');
  assert.ok(!insufficient.label.includes('Medium'));

  const renderedInsufficient = renderRiskBadge('insufficient_data', null);
  assert.ok(renderedInsufficient.includes('Risk: Insufficient data'));
  assert.ok(!renderedInsufficient.includes('Medium'));
});

test('ranking score is not labeled Verification or Confidence', () => {
  const rendered = renderRankingBadge(0.85);
  assert.ok(rendered.includes('Relevance: 85%'));
  assert.ok(!rendered.includes('Verification'));
  assert.ok(!rendered.includes('Confidence'));
});

test('no semantic display helper fabricates a positive state from null', () => {
  const verif = getVerificationMeta(null);
  assert.strictEqual(verif.label, 'Not assessed');
  
  const maturity = getMaturityMeta(null);
  assert.strictEqual(maturity.label, 'Not assessed');
  
  const risk = getRiskMeta(null, null);
  assert.strictEqual(risk.label, 'Risk: Not assessed');
  
  const stance = getEvidenceStanceMeta(null);
  assert.strictEqual(stance.label, 'Unspecified');
});

test('Phase 4 canonical payload rendering integration tests', () => {
  // Test 1: Production Candidate with Strongly Supported and Critical Risk
  const storyProd = {
    story_cluster_id: 'cluster:p4-deepseek-v3',
    title: 'DeepSeek-V3 Architecture Release',
    summary: 'Multi-head latent attention model candidate with verified benchmarks.',
    verification_status: 'strongly_supported',
    verification_score: 0.94,
    maturity_stage: 'production_candidate',
    risk_status: 'assessed',
    risk_level: 'critical',
    risk_score: 0.88,
    cluster_score: 0.92
  };

  const cardHtml1 = renderStoryCard(storyProd);
  assert.ok(cardHtml1.includes('DeepSeek-V3 Architecture Release'));
  assert.ok(cardHtml1.includes('Strongly Supported (94%)'));
  assert.ok(cardHtml1.includes('badge-verification-strongly_supported'));
  assert.ok(cardHtml1.includes('Production Candidate'));
  assert.ok(cardHtml1.includes('badge-maturity-production_candidate'));
  assert.ok(cardHtml1.includes('Critical risk (88%)'));
  assert.ok(cardHtml1.includes('badge-risk-critical'));
  assert.ok(cardHtml1.includes('Relevance: 92%'));

  // Test 2: Established technology with Mixed verification and Low Risk
  const storyEst = {
    story_cluster_id: 'cluster:p4-vllm-perf',
    title: 'vLLM Kernel Optimization',
    summary: 'PagedAttention throughput improvements across GPU architectures.',
    verification_status: 'mixed',
    maturity_stage: 'established',
    risk_status: 'assessed',
    risk_level: 'low',
    risk_score: 0.12,
  };

  const cardHtml2 = renderStoryCard(storyEst);
  assert.ok(cardHtml2.includes('Mixed Evidence'));
  assert.ok(cardHtml2.includes('badge-verification-mixed'));
  assert.ok(cardHtml2.includes('Established'));
  assert.ok(cardHtml2.includes('badge-maturity-established'));
  assert.ok(cardHtml2.includes('Low risk (12%)'));
  assert.ok(cardHtml2.includes('badge-risk-low'));

  // Test 3: Research preprint with Superseded & Insufficient Data Risk
  const storyResearch = {
    story_cluster_id: 'cluster:p4-speculative-decoding',
    title: 'Speculative Decoding Analysis',
    summary: 'Early algorithmic formulation for draft model acceleration.',
    verification_status: 'superseded',
    maturity_stage: 'research',
    risk_status: 'insufficient_data',
    risk_level: null,
  };

  const cardHtml3 = renderStoryCard(storyResearch);
  assert.ok(cardHtml3.includes('Superseded'));
  assert.ok(cardHtml3.includes('badge-verification-superseded'));
  assert.ok(cardHtml3.includes('Research'));
  assert.ok(cardHtml3.includes('badge-maturity-research'));
  assert.ok(cardHtml3.includes('Risk: Insufficient data'));
  assert.ok(cardHtml3.includes('badge-risk-insufficient_data'));

  // Test 4: Retracted claim & Context evidence badges
  const retractedBadge = renderVerificationBadge('retracted');
  assert.ok(retractedBadge.includes('Retracted'));
  assert.ok(retractedBadge.includes('badge-verification-retracted'));

  const contextBadge = renderEvidenceStanceBadge('context');
  assert.ok(contextBadge.includes('Context'));
  assert.ok(contextBadge.includes('badge-stance-context'));
  assert.ok(!contextBadge.includes('Supports'));
});

/* ==========================================================================
   3. Navigation, Shell, UI States & Accessibility
   ========================================================================== */

test('shell navigation links map correct path hashes', () => {
  const state = { view: 'today', connectionStatus: 'healthy', isOffline: false };
  const rendered = renderShell(state);
  
  NAV_ITEMS.forEach(item => {
    assert.ok(rendered.includes(`href="#/${item.id}"`));
    assert.ok(rendered.includes(`data-nav-id="${item.id}"`));
  });
});

test('active navigation link carries aria-current="page"', () => {
  const state = { view: 'briefing', connectionStatus: 'healthy', isOffline: false };
  const rendered = renderShell(state);
  
  // briefing should be marked current
  assert.ok(rendered.includes(`data-nav-id="briefing"\n                 title="Distilled executive read"\n                 aria-current="page"`));
  // today should not be marked current
  assert.ok(rendered.includes(`data-nav-id="today"\n                 title="Daily incoming intelligence"\n                 >`));
});

test('loading state renders spinner and description', () => {
  const rendered = renderLoadingState('Retrieving updates');
  assert.ok(rendered.includes('spinner'));
  assert.ok(rendered.includes('Retrieving updates'));
});

test('empty state does not imply error', () => {
  const rendered = renderEmptyState('No records', 'Corpus empty');
  assert.ok(rendered.includes('No records'));
  assert.ok(rendered.includes('Corpus empty'));
  assert.ok(!rendered.includes('error'));
  assert.ok(!rendered.includes('failed'));
});

test('offline state informs user clearly with retry action', () => {
  const rendered = renderOfflineState('http://localhost:8765', 'Err Connection Refused');
  assert.ok(rendered.includes('Unable to Connect to HERMES API'));
  assert.ok(rendered.includes('http://localhost:8765'));
  assert.ok(rendered.includes('Err Connection Refused'));
  assert.ok(rendered.includes('Retry Connection'));
});

test('responsive shell smoke test contains landmarks', () => {
  const state = { view: 'today', connectionStatus: 'healthy', isOffline: false };
  const rendered = renderShell(state);
  
  assert.ok(rendered.includes('class="sidebar"'));
  assert.ok(rendered.includes('role="banner"'));
  assert.ok(rendered.includes('role="main"'));
  assert.ok(rendered.includes('id="main-content"'));
});

test('no Unicode/emoji nav icons remain in nav items', () => {
  NAV_ITEMS.forEach(item => {
    // Emojis/Unicode symbols shouldn't be in the label
    assert.ok(!/[⌂◒⌕▦☆↗⌁]/.test(item.label));
  });
});

test('adapter formatters preserve null and do not coerce to zero', () => {
  assert.strictEqual(formatScorePercentage(null), '—');
  assert.strictEqual(formatScorePercentage(undefined), '—');
  assert.strictEqual(formatScorePercentage(0), '0%');
  assert.strictEqual(formatScorePercentage(0.854), '85%');

  assert.strictEqual(formatScoreDecimal(null), '—');
  assert.strictEqual(formatScoreDecimal(undefined), '—');
  assert.strictEqual(formatScoreDecimal(0), '0.00');
  assert.strictEqual(formatScoreDecimal(0.755), '0.76');

  assert.strictEqual(formatDate(null), '—');
  assert.strictEqual(escapeHtml('<script>alert("xss")</script>'), '&lt;script&gt;alert(&quot;xss&quot;)&lt;/script&gt;');
  assert.strictEqual(truncateText('short text', 20), 'short text');
  assert.ok(truncateText('this is a very long text that needs truncation', 15).includes('…'));
});

test('story card does not fabricate badges for unassessed stories', () => {
  const unassessedStory = {
    id: 'cluster:999',
    title: 'Unassessed Development',
    summary: 'Raw ingested item with no downstream intelligence computed yet.',
    verification_status: null,
    maturity_stage: null,
    risk_status: 'not_assessed',
    cluster_score: null
  };

  const rendered = renderStoryCard(unassessedStory);
  assert.ok(rendered.includes('Unassessed Development'));
  // Should NOT render badges for null verification, null maturity, or unassessed risk
  assert.ok(!rendered.includes('badge-verification-supported'));
  assert.ok(!rendered.includes('badge-maturity-experimental'));
  assert.ok(!rendered.includes('badge-risk-low'));
  assert.ok(!rendered.includes('Relevance:'));
});

test('error and degraded UI states render correctly', () => {
  const errorHtml = renderErrorState('Network Timeout', 'The backend took too long to reply.');
  assert.ok(errorHtml.includes('Network Timeout'));
  assert.ok(errorHtml.includes('The backend took too long to reply.'));
  assert.ok(errorHtml.includes('Try Again'));

  const degradedHtml = renderDegradedState('Backend Degraded', 'Source pipeline is recovering.');
  assert.ok(degradedHtml.includes('Backend Degraded'));
  assert.ok(degradedHtml.includes('Source pipeline is recovering.'));
});

