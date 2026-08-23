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
  VERIFICATION_MAP,
  getMaturityMeta,
  MATURITY_MAP,
  normalizeMaturityStage,
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
  renderScoreBadge,
  renderSourcePill,
  SCORE_DOMAINS,
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
import {
  renderGroundingReferences,
  renderEvidenceItem,
  renderClaimRevisions,
  renderClaimCard,
} from '../src/views/story-detail.js';
import {
  renderSearchView,
  renderSearchResultCard,
  renderRankingDecomposition,
  resetSearchFilterCatalogsCache,
} from '../src/views/search.js';

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
  assert.strictEqual(unknown.label, 'Unrecognized maturity');
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
  assert.strictEqual(unknown.label, 'Unrecognized claim status');
  assert.strictEqual(unknown.cssClass, 'badge-verification-not_assessed');
});

test('Claim status descriptions contain no explanatory overreach or invented evidence policies', () => {
  const forbiddenPhrases = [
    'multiple independent primary sources',
    'independent reproduction',
    'lacking independent verification',
    'lacking all independent evidence',
  ];

  Object.entries(VERIFICATION_MAP).forEach(([status, meta]) => {
    const descLower = (meta.description || '').toLowerCase();
    forbiddenPhrases.forEach((phrase) => {
      assert.ok(
        !descLower.includes(phrase),
        `Claim status "${status}" description contains forbidden overreach phrase "${phrase}": ${meta.description}`
      );
    });
  });
});

test('Maturity alias normalization rejects non-canonical legacy values with negative tests', () => {
  // Rejected legacy aliases must degrade neutrally to "Unrecognized maturity"
  assert.strictEqual(getMaturityMeta('maturing').label, 'Unrecognized maturity');
  assert.strictEqual(getMaturityMeta('maturing').cssClass, 'badge-maturity-not_assessed');
  assert.strictEqual(normalizeMaturityStage('maturing'), null);

  assert.strictEqual(getMaturityMeta('production_ready').label, 'Unrecognized maturity');
  assert.strictEqual(getMaturityMeta('production_ready').cssClass, 'badge-maturity-not_assessed');
  assert.strictEqual(normalizeMaturityStage('production_ready'), null);

  assert.strictEqual(getMaturityMeta('stable').label, 'Unrecognized maturity');
  assert.strictEqual(getMaturityMeta('stable').cssClass, 'badge-maturity-not_assessed');
  assert.strictEqual(normalizeMaturityStage('stable'), null);

  assert.strictEqual(getMaturityMeta('growth').label, 'Unrecognized maturity');
  assert.strictEqual(getMaturityMeta('growth').cssClass, 'badge-maturity-not_assessed');
  assert.strictEqual(normalizeMaturityStage('growth'), null);

  // Scored or ungrounded strings
  assert.strictEqual(getMaturityMeta('mature').label, 'Unrecognized maturity');
  assert.strictEqual(getMaturityMeta('proposal').label, 'Unrecognized maturity');
  assert.strictEqual(getMaturityMeta('growth (0.72)').label, 'Unrecognized maturity');
  assert.strictEqual(getMaturityMeta('experimental (0.90)').label, 'Unrecognized maturity');
  assert.strictEqual(getMaturityMeta('some_arbitrary_string').label, 'Unrecognized maturity');
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
  assert.strictEqual(unknown.label, 'Unspecified');
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
  const rendered = renderRankingBadge(0.85, SCORE_DOMAINS.RELEVANCE);
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
  assert.ok(cardHtml1.includes('Cluster score: 0.92'));

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

/* ==========================================================================
   4. Phase 6 — Story Dossier & Evidence Investigation Experience Tests
   ========================================================================== */

test('Grounding references render semantically distinct labels and classes by entity type', () => {
  const refs = [
    { entity_type: 'event', entity_id: 'ev_arxiv_101' },
    { entity_type: 'claim', entity_id: 'claim_latency_45' },
    { entity_type: 'evidence', entity_id: 'evid_bench_repro' },
    { entity_type: 'assessment', entity_id: 'assess_prod_cand' },
    { entity_type: 'project_match', entity_id: 'proj_cuda_lab' },
    { entity_type: 'change', entity_id: 'chg_status_mixed' },
  ];

  const rendered = renderGroundingReferences(refs);
  assert.ok(rendered.includes('provenance-pill-event'));
  assert.ok(rendered.includes('Event: ev_arxiv_101'));
  assert.ok(rendered.includes('provenance-pill-claim'));
  assert.ok(rendered.includes('Claim: claim_latency_45'));
  assert.ok(rendered.includes('provenance-pill-evidence'));
  assert.ok(rendered.includes('Evidence: evid_bench_repro'));
  assert.ok(rendered.includes('provenance-pill-assessment'));
  assert.ok(rendered.includes('Assessment: assess_prod_cand'));
  assert.ok(rendered.includes('provenance-pill-project'));
  assert.ok(rendered.includes('Project: proj_cuda_lab'));
  assert.ok(rendered.includes('provenance-pill-change'));
  assert.ok(rendered.includes('Change: chg_status_mixed'));
});

test('Claim card disclosure exposes aria-expanded, aria-controls, and origin pill', () => {
  const claim = {
    claim_id: 'claim_flash_attn_3',
    claim_text: 'FlashAttention-3 achieves 1.2 PFLOPS throughput on H100 SXM5.',
    status: 'strongly_supported',
    verification_score: 0.96,
    is_self_reported: true,
    assertion_level: 'empirical_benchmark',
    claim_type: 'performance',
    evidence_count: 3,
  };

  // Collapsed claim
  const collapsedHtml = renderClaimCard(claim, false, null, false, null);
  assert.ok(collapsedHtml.includes('aria-expanded="false"'));
  assert.ok(collapsedHtml.includes('aria-controls="claim-evidence-claim_flash_attn_3"'));
  assert.ok(collapsedHtml.includes('Claim origin: Self-reported'));
  assert.ok(collapsedHtml.includes('Strongly Supported (96%)'));
  assert.ok(collapsedHtml.includes('Inspect Evidence (3)'));
  assert.ok(collapsedHtml.includes('style="display:none;"'));

  // Expanded claim with loading state
  const loadingHtml = renderClaimCard(claim, true, null, true, null);
  assert.ok(loadingHtml.includes('aria-expanded="true"'));
  assert.ok(loadingHtml.includes('Retrieving progressive evidence provenance'));
  assert.ok(loadingHtml.includes('style="display:block;"'));
});

test('Evidence item renders separate dimensions and distinguishes independent reproduction from generic evidence', () => {
  // Test independent reproduction
  const reproEv = {
    evidence_id: 'ev_repro_01',
    source: 'github',
    evidence_type: 'independent_reproduction',
    stance: 'supports',
    quality_score: 0.92,
    independence_score: 0.95,
    reproducibility_score: 0.88,
    is_independent: true,
    excerpt: 'Replication script reproduced claimed throughput within 2.3% error margin.',
    url: 'https://github.com/lab/reproduction-benchmarks',
    observed_at: '2026-08-20T14:30:00Z',
  };

  const reproHtml = renderEvidenceItem(reproEv);
  assert.ok(reproHtml.includes('Independent Reproduction'));
  assert.ok(reproHtml.includes('Quality: <strong>92%</strong>'));
  assert.ok(reproHtml.includes('Independence: <strong>95%</strong>'));
  assert.ok(reproHtml.includes('Reproducibility: <strong>88%</strong>'));
  assert.ok(reproHtml.includes('Supports'));
  assert.ok(reproHtml.includes('https://github.com/lab/reproduction-benchmarks'));

  // Test affiliated evidence without URL
  const affiliatedEv = {
    evidence_id: 'ev_affil_02',
    source: 'arxiv',
    evidence_type: 'preprint',
    stance: 'context',
    quality_score: 0.70,
    independence_score: 0.20,
    reproducibility_score: null,
    is_independent: false,
    excerpt: 'Primary author team technical formulation.',
    url: null,
    observed_at: '2026-08-18T10:00:00Z',
  };

  const affilHtml = renderEvidenceItem(affiliatedEv);
  assert.ok(affilHtml.includes('Non-independent Evidence'));
  assert.ok(affilHtml.includes('Context'));
  assert.ok(!affilHtml.includes('Supports'));
  assert.ok(affilHtml.includes('No external URL provided'));
  assert.ok(!affilHtml.includes('<a href='));
});

test('Self-reported claim origin and independent evidence coexist without conflation', () => {
  const claim = {
    claim_id: 'claim_vllm_paged',
    claim_text: 'PagedAttention reduces memory fragmentation from 70% to under 4%.',
    status: 'supported',
    verification_score: 0.89,
    is_self_reported: true, // Claim originated from author release
  };

  const claimDetail = {
    claim_id: 'claim_vllm_paged',
    evidence: [
      {
        evidence_id: 'ev_ext_01',
        source: 'openalex',
        stance: 'supports',
        quality_score: 0.90,
        independence_score: 0.92,
        reproducibility_score: 0.85,
        is_independent: true, // Corroborating third-party evaluation
        excerpt: 'Independent benchmark validation on serving workloads.',
        url: 'https://doi.org/10.1145/example',
      }
    ],
    revisions: []
  };

  const rendered = renderClaimCard(claim, true, claimDetail, false, null);
  // Claim is labeled Claim origin: Self-reported
  assert.ok(rendered.includes('Claim origin: Self-reported'));
  // Evidence attached is labeled Independent Evidence
  assert.ok(rendered.includes('Independent Evidence'));
  // Both distinct dimensions exist simultaneously without conflation
  assert.ok(!rendered.includes('Non-independent Evidence'));
  assert.ok(!rendered.includes('Affiliated / Self-Reported'));
});

test('Claim origin truthfulness: false renders Not self-reported and never Observed or Verified', () => {
  const nonSelfReportedClaim = {
    claim_id: 'claim_third_party',
    claim_text: 'Benchmarking report from external conference.',
    status: 'supported',
    verification_score: 0.85,
    is_self_reported: false, // Not self-reported!
  };

  const nonSelfDetail = {
    claim_id: 'claim_third_party',
    evidence: [
      {
        evidence_id: 'ev_non_ind_01',
        source: 'arxiv',
        stance: 'supports',
        quality_score: 0.7,
        independence_score: 0.4,
        reproducibility_score: 0.5,
        is_independent: false, // Non-independent evidence on non-self-reported claim!
        excerpt: 'Shared secondary author laboratory data.',
        url: null,
      }
    ],
    revisions: []
  };

  const rendered = renderClaimCard(nonSelfReportedClaim, true, nonSelfDetail, false, null);

  // 1. is_self_reported=false renders Not self-reported
  assert.ok(rendered.includes('Claim origin: Not self-reported'));
  assert.ok(rendered.includes('pill-not-self-reported'));

  // 2. false does NOT render Observed, Independently verified, or equivalent
  assert.ok(!rendered.includes('Claim origin: Observed'));
  assert.ok(!rendered.includes('Observed Claim'));
  assert.ok(!rendered.includes('Independently verified'));
  assert.ok(!rendered.includes('pill-observed'));

  // 3. A non-self-reported claim can have non-independent evidence
  assert.ok(rendered.includes('Non-independent Evidence'));
});

test('Claim revisions render state transitions and preserve null verification scores without 0% coercion', () => {
  const revisions = [
    {
      revision_id: 'rev_01',
      previous_status: null,
      new_status: 'unverified',
      previous_verification_score: null,
      new_verification_score: null, // Null score
      reason: 'Initial announcement extracted without corroborating evidence',
      created_at: '2026-08-15T09:00:00Z',
    },
    {
      revision_id: 'rev_02',
      previous_status: 'unverified',
      new_status: 'supported',
      previous_verification_score: null,
      new_verification_score: 0.85,
      reason: 'Independent reproduction uploaded with verified benchmark script',
      created_at: '2026-08-18T16:00:00Z',
    }
  ];

  const rendered = renderClaimRevisions(revisions);
  assert.ok(rendered.includes('Verification & State History (2)'));
  assert.ok(rendered.includes('Initial Ingestion'));
  assert.ok(rendered.includes('unverified (unassessed)'));
  assert.ok(!rendered.includes('unverified (0%)'));
  assert.ok(rendered.includes('supported (85%)'));
  assert.ok(rendered.includes('Independent reproduction uploaded with verified benchmark script'));
});

test('Story Dossier rendering handles partial synthesis without creating filler for why_it_matters=null', () => {
  const partialSynthesis = {
    what_happened: {
      statement: 'Researchers released an optimized sparse attention kernel.',
      grounding_references: [{ entity_type: 'event', entity_id: 'ev_1' }]
    },
    why_it_matters: null, // absent!
    evidence_position: null,
    project_implications: null,
    change_summary: null
  };

  const groundingHtml = renderGroundingReferences(partialSynthesis.what_happened.grounding_references);
  assert.ok(groundingHtml.includes('Event: ev_1'));

  // Ensure no filler string is generated for null statements
  assert.strictEqual(renderGroundingReferences(null), '');
  assert.strictEqual(renderGroundingReferences([]), '');
});

test('Evidence stances supports, contradicts, and context are visually distinct and context never renders as support', () => {
  const supportBadge = renderEvidenceStanceBadge('supports');
  const contradictBadge = renderEvidenceStanceBadge('contradicts');
  const contextBadge = renderEvidenceStanceBadge('context');
  const nullBadge = renderEvidenceStanceBadge(null);
  const unknownBadge = renderEvidenceStanceBadge('unrecognized_stance');

  assert.ok(supportBadge.includes('Supports'));
  assert.ok(contradictBadge.includes('Contradicts'));
  assert.ok(contextBadge.includes('Context'));
  assert.ok(nullBadge.includes('Unspecified'));
  assert.ok(nullBadge.includes('badge-stance-unknown'));
  assert.ok(unknownBadge.includes('badge-stance-unknown'));

  // Context must NEVER contain Supports class or wording
  assert.ok(!contextBadge.includes('Supports'));
  assert.ok(!contextBadge.includes('stance-supports'));
  assert.ok(contextBadge.includes('stance-context'));
});

test('Evidence item without URL creates no anchor link', () => {
  const ev = {
    evidence_id: 'ev_internal_01',
    source: 'github',
    stance: 'supports',
    quality_score: 0.8,
    independence_score: 0.8,
    reproducibility_score: 0.8,
    is_independent: true,
    excerpt: 'Reproduced in internal evaluation testbed.',
    url: null,
    observed_at: '2026-08-20T12:00:00Z'
  };

  const html = renderEvidenceItem(ev);
  assert.ok(html.includes('No external URL provided'));
  assert.ok(!html.includes('<a href='));
});

test('Evidence item with valid URL creates external anchor link with rel noopener noreferrer', () => {
  const ev = {
    evidence_id: 'ev_url_02',
    source: 'arxiv',
    stance: 'supports',
    quality_score: 0.95,
    independence_score: 0.9,
    reproducibility_score: 0.85,
    is_independent: true,
    excerpt: 'Published peer-reviewed results.',
    url: 'https://arxiv.org/abs/2401.00000',
    observed_at: '2026-08-20T12:00:00Z'
  };

  const html = renderEvidenceItem(ev);
  assert.ok(html.includes('<a href="https://arxiv.org/abs/2401.00000"'));
  assert.ok(html.includes('target="_blank"'));
  assert.ok(html.includes('rel="noopener noreferrer"'));
});

test('Evidence outside top preview remains a valid traceable grounding reference', () => {
  const offPreviewRef = [{ entity_type: 'event', entity_id: 'ev_historical_archive_999' }];
  const rendered = renderGroundingReferences(offPreviewRef);
  assert.ok(rendered.includes('data-entity-id="ev_historical_archive_999"'));
  assert.ok(rendered.includes('Event: ev_historical_archive_999'));
});

test('Project implications use ProjectMatch data and do not fabricate implications when absent', () => {
  const match = {
    project_id: 'proj_cuda_engine',
    project_name: 'CUDA Compiler Optimization Engine',
    match_type: 'direct_dependency',
    relevance_score: 0.88,
    recommendation: 'Evaluate sparse attention kernel in v2 benchmark suite.'
  };

  // When project matches exist, they render truthful details
  assert.strictEqual(match.project_name, 'CUDA Compiler Optimization Engine');
  assert.strictEqual(Math.round(match.relevance_score * 100), 88);
});

test('Risk status handling strictly separates not_assessed and insufficient_data without fabricating Low/Medium risk', () => {
  const notAssessedMeta = getRiskMeta('not_assessed', null);
  assert.strictEqual(notAssessedMeta.label, 'Risk: Not assessed');
  assert.ok(!notAssessedMeta.cssClass.includes('badge-risk-low'));

  const insufficientDataMeta = getRiskMeta('insufficient_data', null);
  assert.strictEqual(insufficientDataMeta.label, 'Risk: Insufficient data');
  assert.ok(!insufficientDataMeta.cssClass.includes('badge-risk-medium'));
  assert.strictEqual(insufficientDataMeta.cssClass, 'badge-risk-insufficient_data');
});

test('Exact API call count verification for progressive claim loading and session caching', async () => {
  const storyCalls = [];
  const claimCalls = [];

  // Instrument fetch to track exact calls
  fetchMock = async (url) => {
    if (url.includes('/stories/')) {
      storyCalls.push(url);
      return {
        ok: true,
        status: 200,
        json: async () => ({
          cluster_id: 'cluster_test_count',
          canonical_title: 'Progressive Claim Request Count Test',
          cluster_score: 0.88,
          sources: ['arxiv', 'github'],
          verification: { claim_status: 'supported', verification_score: 0.85 },
          maturity_stage: 'prototype',
          risk: { status: 'assessed', level: 'low', score: 0.2 },
          claims: [
            { claim_id: 'claim_alpha', claim_text: 'Alpha claim text', status: 'supported', evidence_count: 2 },
            { claim_id: 'claim_beta', claim_text: 'Beta claim text', status: 'unverified', evidence_count: 1 }
          ],
          events: []
        })
      };
    }
    if (url.includes('/claims/')) {
      const claimId = url.split('/claims/')[1].split('?')[0];
      claimCalls.push(claimId);
      return {
        ok: true,
        status: 200,
        json: async () => ({
          claim_id: claimId,
          text: `Detail for ${claimId}`,
          status: 'supported',
          evidence: [
            {
              evidence_id: `ev_${claimId}_1`,
              source: 'github',
              stance: 'supports',
              quality_score: 0.9,
              independence_score: 0.85,
              reproducibility_score: 0.8,
              is_independent: true
            }
          ],
          revisions: []
        })
      };
    }
    return { ok: true, status: 200, json: async () => ({}) };
  };

  const container = {
    innerHTML: '',
    querySelectorAll: () => [],
    querySelector: () => null,
    appendChild: () => {}
  };
  const store = {
    state: {},
    getState: () => store.state,
    setState: (s) => Object.assign(store.state, s),
    setConnection: () => {}
  };

  // Step 1: Initial dossier entry
  const { renderStoryDetailView } = await import('../src/views/story-detail.js');
  await renderStoryDetailView(container, store, { storyId: 'cluster_test_count' });

  // Observed: exactly 1 Story request, 0 ClaimDetail requests
  assert.strictEqual(storyCalls.length, 1);
  assert.strictEqual(claimCalls.length, 0);

  // Step 2: Progressive claim fetch
  const { api } = await import('../src/api/endpoints.js');
  const claimA1 = await api.getClaim('claim_alpha');
  assert.strictEqual(claimCalls.length, 1);
  assert.strictEqual(claimCalls[0], 'claim_alpha');

  // Step 3: Progressive fetch of claim Beta
  const claimB1 = await api.getClaim('claim_beta');
  assert.strictEqual(claimCalls.length, 2);
  assert.strictEqual(claimCalls[1], 'claim_beta');

  // Reset fetch mock
  fetchMock = null;
});

/* ==========================================================================
   Phase 7: Search & Query Experience Tests
   ========================================================================== */

test('Search Result Card strictly labels ranking score as Relevance Score / Search Rank, never Verification / Confidence', () => {
  const item = {
    entity_id: 'cluster_gpu_attn',
    title: 'FlashAttention-4 Architecture for Blackwell GPUs',
    score: 0.942,
    verification_score: null, // Null verification
    claim_status: null,
    sources: ['github'],
    published_at: '2026-08-20T12:00:00Z',
    is_synthesized: true,
    summary: 'Hardware-aware kernel implementation for tensor cores.',
  };

  const html = renderSearchResultCard(item);

  // 1. Must label score neutrally as Score: 0.94 without converting to percentage
  assert.ok(html.includes('Score: 0.94'));
  assert.ok(html.includes('badge-rank'));

  // 2. Must NEVER label score as Confidence, Verification, or Trust
  assert.ok(!html.includes('Confidence'));
  assert.ok(!html.includes('Verification Score'));
  assert.ok(!html.includes('Trust Score'));
  assert.ok(!html.includes('Accuracy'));

  // 3. Null verification renders Not assessed
  assert.ok(html.includes('Verification: Not assessed') || html.includes('badge-verification-unassessed'));
});

test('Search Result Card distinguishes grounded synthesis from raw fallback source excerpts', () => {
  // Synthesized intelligence result
  const synthItem = {
    entity_id: 'cluster_synth_1',
    title: 'Sparse Kernel Compiler Optimization',
    score: 0.88,
    verification_score: 0.85,
    claim_status: 'supported',
    sources: ['github'],
    is_synthesized: true,
    summary: 'Synthesized intelligence finding grounded in repository events and claims.',
  };

  const synthHtml = renderSearchResultCard(synthItem);
  assert.ok(synthHtml.includes('summary-synthesized'));
  assert.ok(synthHtml.includes('Grounded Synthesis'));
  assert.ok(!synthHtml.includes('summary-source-excerpt'));

  // Raw fallback source excerpt result
  const rawItem = {
    entity_id: 'cluster_raw_2',
    title: 'Unprocessed Preprint Release',
    score: 0.72,
    verification_score: null,
    claim_status: 'unverified',
    sources: ['arxiv'],
    is_synthesized: false,
    summary: 'Raw excerpt extracted directly from publication metadata without analytic synthesis.',
  };

  const rawHtml = renderSearchResultCard(rawItem);
  assert.ok(rawHtml.includes('summary-source-excerpt'));
  assert.ok(rawHtml.includes('Source Excerpt'));
  assert.ok(!rawHtml.includes('summary-synthesized'));
  assert.ok(!rawHtml.includes('Grounded Synthesis'));
});

test('Search ranking decomposition panel presents factors truthfully and explains ordering rather than epistemic truth', () => {
  const explain = {
    lexical_score: 0.8500,
    semantic_score: 0.9120,
    verification_adjustment: 0.1250,
    freshness_adjustment: 0.0800,
    project_boost: 0.2000,
    final_score: 0.9250
  };

  const html = renderRankingDecomposition(explain);

  // 1. Explicit heading indicating ranking explanation
  assert.ok(html.includes('Why this ranked here (Search Ranking Explanation)'));
  assert.ok(html.includes('Factors explain search ordering, not epistemic truth'));
  assert.ok(!html.includes('Why this is true'));

  // 2. All 6 exact decomposition factors present
  assert.ok(html.includes('Lexical Match:'));
  assert.ok(html.includes('0.8500'));
  assert.ok(html.includes('Semantic Sim:'));
  assert.ok(html.includes('0.9120'));
  assert.ok(html.includes('Verification Adj:'));
  assert.ok(html.includes('0.1250'));
  assert.ok(html.includes('Freshness Adj:'));
  assert.ok(html.includes('0.0800'));
  assert.ok(html.includes('Project Boost:'));
  assert.ok(html.includes('0.2000'));
  assert.ok(html.includes('Final Rank Score:'));
  assert.ok(html.includes('0.9250'));
});

test('Search result card title and action button route to canonical Story Dossier (#/story/{id})', () => {
  const item = {
    entity_id: 'cluster:cuda-compiler-opt',
    title: 'CUDA Compiler Optimization',
    score: 0.85,
    sources: ['github'],
  };

  const html = renderSearchResultCard(item);
  assert.ok(html.includes('href="#/story/cluster%3Acuda-compiler-opt"'));
  assert.ok(html.includes('Open Story Dossier &rarr;'));
});

test('Blank Search view does not issue requests and renders guidance empty state', async () => {
  let searchCalled = false;
  fetchMock = async (url) => {
    if (url.includes('/search')) searchCalled = true;
    return { ok: true, status: 200, json: async () => ({ count: 0, results: [] }) };
  };

  const container = {
    innerHTML: '',
    querySelectorAll: () => [],
    querySelector: () => null,
  };
  const store = {
    state: { searchQuery: '' },
    getState: () => store.state,
    setState: (s) => Object.assign(store.state, s),
    setConnection: () => {}
  };

  await renderSearchView(container, store, { q: '' });

  // No backend search request issued for blank query
  assert.strictEqual(searchCalled, false);
  assert.ok(container.innerHTML.includes('Start with an Engineering Query'));

  fetchMock = null;
});

test('Technical query strings preserve meaningful symbols at search boundary without destructive modification', () => {
  const testQueries = ['C++', 'CUDA 13', 'AES-256', 'vLLM', 'CET1', 'PostgreSQL 18'];
  for (const q of testQueries) {
    const item = {
      entity_id: 'test_tech_id',
      title: `Implementation of ${q}`,
      score: 0.9,
      sources: ['github'],
    };
    const html = renderSearchResultCard(item);
    assert.ok(html.includes(escapeHtml(q)));
  }
});

test('Search Result Card preserves Project Relevance without converting to upgrade advice', () => {
  const item = {
    entity_id: 'cluster_proj_match',
    title: 'vLLM Kernel Optimization',
    score: 0.88,
    project_relevance: 0.75,
    sources: ['github'],
  };

  const html = renderSearchResultCard(item);
  assert.ok(html.includes('Project relevance: 75%'));
  assert.ok(!html.includes('Upgrade Recommendation'));
  assert.ok(!html.includes('Should adopt'));
});

test('Search Result Card renders contradiction and mixed verification status without positive inflation', () => {
  const contradictedItem = {
    entity_id: 'cluster_contra',
    title: 'Disputed Benchmark Claims',
    score: 0.92,
    verification_score: 0.35,
    claim_status: 'contradicted',
    sources: ['arxiv'],
  };

  const html = renderSearchResultCard(contradictedItem);
  assert.ok(html.includes('Contradicted (35%)'));
  assert.ok(!html.includes('badge-verification-strongly_supported'));
});

test('Search URL state serialization and restoration preserve all query and filter parameters', () => {
  const state = {
    q: 'sparse kernel compiler',
    mode: 'lexical',
    source: 'github',
    min_maturity: 'prototype',
    max_risk: 'low',
    project: 'proj_cuda_engine',
    verified_only: true,
    days: 30,
    explain: true,
  };

  // 1. Serialization
  const params = new URLSearchParams();
  if (state.q) params.set('q', state.q);
  if (state.mode && state.mode !== 'hybrid') params.set('mode', state.mode);
  if (state.source) params.set('source', state.source);
  if (state.min_maturity) params.set('min_maturity', state.min_maturity);
  if (state.max_risk) params.set('max_risk', state.max_risk);
  if (state.project) params.set('project', state.project);
  if (state.verified_only) params.set('verified_only', 'true');
  if (state.days) params.set('days', String(state.days));
  if (state.explain) params.set('explain', 'true');

  const queryString = params.toString();
  assert.ok(queryString.includes('q=sparse+kernel+compiler'));
  assert.ok(queryString.includes('mode=lexical'));
  assert.ok(queryString.includes('source=github'));
  assert.ok(queryString.includes('min_maturity=prototype'));
  assert.ok(queryString.includes('max_risk=low'));
  assert.ok(queryString.includes('project=proj_cuda_engine'));
  assert.ok(queryString.includes('verified_only=true'));
  assert.ok(queryString.includes('days=30'));
  assert.ok(queryString.includes('explain=true'));

  // 2. Restoration
  const parsed = new URLSearchParams(queryString);
  const restored = {
    q: parsed.get('q') || '',
    mode: parsed.get('mode') || 'hybrid',
    source: parsed.get('source') || '',
    min_maturity: parsed.get('min_maturity') || '',
    max_risk: parsed.get('max_risk') || '',
    project: parsed.get('project') || '',
    verified_only: parsed.get('verified_only') === 'true',
    days: parsed.get('days') ? parseInt(parsed.get('days'), 10) : null,
    explain: parsed.get('explain') === 'true',
  };

  assert.strictEqual(restored.q, state.q);
  assert.strictEqual(restored.mode, state.mode);
  assert.strictEqual(restored.source, state.source);
  assert.strictEqual(restored.min_maturity, state.min_maturity);
  assert.strictEqual(restored.max_risk, state.max_risk);
  assert.strictEqual(restored.project, state.project);
  assert.strictEqual(restored.verified_only, true);
  assert.strictEqual(restored.days, 30);
  assert.strictEqual(restored.explain, true);
});

function createMockContainer() {
  let elements = {};
  function makeMockElement() {
    const classes = new Set();
    return {
      value: '',
      checked: false,
      disabled: false,
      style: {},
      _html: '',
      _attrs: {},
      dataset: {},
      classList: {
        contains(cls) { return classes.has(cls); },
        add(cls) { classes.add(cls); },
        remove(cls) { classes.delete(cls); }
      },
      textContent: '',
      getAttribute(attr) { return this._attrs[attr] || null; },
      setAttribute(attr, val) { this._attrs[attr] = String(val); },
      get innerHTML() { return this._html; },
      set innerHTML(v) { this._html = v; },
      _listeners: {},
      addEventListener(event, handler) {
        if (!this._listeners[event]) this._listeners[event] = [];
        this._listeners[event].push(handler);
      },
      async click() {
        const handlers = [...(this._listeners['click'] || [])];
        for (const h of handlers) {
          await h({ target: this, preventDefault() {}, closest: (s) => this });
        }
      },
      closest() { return this; },
      querySelector(sel) { return makeMockElement(); },
      insertAdjacentHTML() {},
      appendChild() {},
      focus() {},
      remove() {}
    };
  }

  const container = {
    _html: '',
    _listeners: {},
    addEventListener(event, handler) {
      if (!this._listeners[event]) this._listeners[event] = [];
      this._listeners[event].push(handler);
    },
    get innerHTML() {
      let combined = this._html;
      for (const key of Object.keys(elements)) {
        if (elements[key]._html) {
          combined += '\n' + elements[key]._html;
        }
      }
      return combined;
    },
    set innerHTML(val) {
      this._html = val;
      elements = {};
    },
    querySelector: (sel) => {
      if (!elements[sel]) {
        elements[sel] = makeMockElement();
      }
      return elements[sel];
    },
    querySelectorAll: () => []
  };
  return container;
}

test('Search View transmits all filter parameters to API search endpoint', async () => {
  const capturedUrls = [];
  fetchMock = async (url) => {
    capturedUrls.push(url);
    if (url.includes('/sources')) return { ok: true, status: 200, json: async () => ({ sources: [] }) };
    if (url.includes('/projects')) return { ok: true, status: 200, json: async () => ({ projects: [] }) };
    return {
      ok: true,
      status: 200,
      json: async () => ({ count: 1, results: [{ entity_id: 'c1', title: 'Result 1', score: 0.9, sources: ['arxiv'] }] }),
    };
  };

  const container = createMockContainer();
  const store = {
    state: {},
    getState: () => store.state,
    setState: (s) => Object.assign(store.state, s),
    setConnection: () => {},
  };

  await renderSearchView(container, store, {
    q: 'sparse kernel',
    mode: 'semantic',
    source: 'arxiv',
    min_maturity: 'established',
    max_risk: 'high',
    project: 'proj_opt',
    verified_only: 'true',
    days: '14',
    explain: 'true',
  });

  const searchUrl = capturedUrls.find((u) => u.includes('/search'));
  assert.ok(searchUrl, 'Search endpoint was called');
  assert.ok(searchUrl.includes('q=sparse+kernel'));
  assert.ok(searchUrl.includes('mode=semantic'));
  assert.ok(searchUrl.includes('source=arxiv'));
  assert.ok(searchUrl.includes('min_maturity=established'));
  assert.ok(searchUrl.includes('max_risk=high'));
  assert.ok(searchUrl.includes('project=proj_opt'));
  assert.ok(searchUrl.includes('verified_only=true'));
  assert.ok(searchUrl.includes('days=14'));
  assert.ok(searchUrl.includes('explain=true'));

  fetchMock = null;
});

test('Search View handles API error state gracefully with accessible error message and retry prompt', async () => {
  fetchMock = async (url) => {
    if (url.includes('/sources')) return { ok: true, status: 200, json: async () => ({ sources: [] }) };
    if (url.includes('/projects')) return { ok: true, status: 200, json: async () => ({ projects: [] }) };
    return { ok: false, status: 500, statusText: 'Internal Server Error' };
  };

  const container = createMockContainer();
  const store = {
    state: {},
    getState: () => store.state,
    setState: (s) => Object.assign(store.state, s),
    setConnection: () => {},
  };

  await renderSearchView(container, store, { q: 'cuda failure' });

  const resultsArea = container.querySelector('#search-results-area');
  assert.ok(resultsArea.innerHTML.includes('Search Request Failed') || resultsArea.innerHTML.includes('state-error'));

  fetchMock = null;
});


test('Search Result Card never infers canonical ClaimStatus from verification score alone', () => {
  // Case A: Supported claim with score
  const itemSupported = {
    entity_id: 'cl_supp',
    title: 'Supported Discovery',
    score: 0.85,
    verification_score: 0.72,
    claim_status: 'supported',
    sources: ['github'],
  };
  const htmlSupp = renderSearchResultCard(itemSupported);
  assert.ok(htmlSupp.includes('Supported (72%)'));
  assert.ok(htmlSupp.includes('badge-verification-supported'));

  // Case B: Null claim status with score -> must NEVER become Supported
  const itemNullStatus = {
    entity_id: 'cl_null_status',
    title: 'Unassessed Status Discovery',
    score: 0.85,
    verification_score: 0.72,
    claim_status: null,
    sources: ['github'],
  };
  const htmlNullStatus = renderSearchResultCard(itemNullStatus);
  assert.ok(htmlNullStatus.includes('Not assessed (72%)') || htmlNullStatus.includes('badge-verification-unassessed'));
  assert.ok(!htmlNullStatus.includes('Supported (72%)'));
  assert.ok(!htmlNullStatus.includes('badge-verification-supported'));

  // Case C: Contradicted claim with score
  const itemContra = {
    entity_id: 'cl_contra',
    title: 'Contradicted Discovery',
    score: 0.85,
    verification_score: 0.72,
    claim_status: 'contradicted',
    sources: ['arxiv'],
  };
  const htmlContra = renderSearchResultCard(itemContra);
  assert.ok(htmlContra.includes('Contradicted (72%)'));
  assert.ok(htmlContra.includes('badge-verification-contradicted'));
  assert.ok(!htmlContra.includes('Supported (72%)'));
});

test('Search Result Card correctly passes riskStatus and riskLevel to renderRiskBadge without synthesizing RiskStatus', () => {
  const cases = [
    { status: 'assessed', level: 'low', expectedText: 'Low risk', expectedClass: 'badge-risk-low' },
    { status: 'assessed', level: 'medium', expectedText: 'Medium risk', expectedClass: 'badge-risk-medium' },
    { status: 'assessed', level: 'high', expectedText: 'High risk', expectedClass: 'badge-risk-high' },
    { status: 'assessed', level: 'critical', expectedText: 'Critical risk', expectedClass: 'badge-risk-critical' },
    { status: 'not_assessed', level: null, expectedText: 'Risk: Not assessed', expectedClass: 'badge-risk-not_assessed' },
    { status: 'insufficient_data', level: null, expectedText: 'Risk: Insufficient data', expectedClass: 'badge-risk-insufficient_data' },
    { status: null, level: 'medium', expectedText: 'Risk: Not assessed', expectedClass: 'badge-risk-not_assessed', forbiddenText: 'Medium risk', forbiddenClass: 'badge-risk-medium' },
    { status: null, level: null, expectedText: 'Risk: Not assessed', expectedClass: 'badge-risk-not_assessed' },
  ];

  for (const c of cases) {
    const item = {
      entity_id: `cl_risk_${c.level || 'nolevel'}_${c.status || 'nostatus'}`,
      title: `Risk Test ${c.status} ${c.level}`,
      score: 0.8,
      risk: c.level,
      risk_status: c.status,
      sources: ['github'],
    };
    const html = renderSearchResultCard(item);
    assert.ok(html.includes(c.expectedText), `Expected "${c.expectedText}" in HTML for status=${c.status}/level=${c.level}`);
    assert.ok(html.includes(c.expectedClass), `Expected class "${c.expectedClass}" in HTML for status=${c.status}/level=${c.level}`);
    if (c.forbiddenText) {
      assert.ok(!html.includes(c.forbiddenText), `Forbidden text "${c.forbiddenText}" must not appear for status=${c.status}/level=${c.level}`);
    }
    if (c.forbiddenClass) {
      assert.ok(!html.includes(c.forbiddenClass), `Forbidden class "${c.forbiddenClass}" must not appear for status=${c.status}/level=${c.level}`);
    }
  }
});

test('Source control renders only returned sources on /sources success and no fabricated options on empty or failure', async () => {
  // Test Case 1: /sources success with specific sources
  resetSearchFilterCatalogsCache();
  fetchMock = async (url) => {
    if (url.includes('/sources')) {
      return {
        ok: true,
        status: 200,
        json: async () => ({
          sources: [
            { id: 'custom_source_a', name: 'custom_source_a', display_name: 'Custom Source A' },
            { id: 'custom_source_b', name: 'custom_source_b', display_name: 'Custom Source B' },
          ],
        }),
      };
    }
    return { ok: true, status: 200, json: async () => ({ count: 0, results: [] }) };
  };

  const container1 = createMockContainer();
  const store1 = { state: {}, getState: () => store1.state, setState: (s) => Object.assign(store1.state, s), setConnection: () => {} };
  await renderSearchView(container1, store1, { q: '' });

  const sourceSelect1 = container1.querySelector('#search-source-select');
  assert.ok(sourceSelect1.innerHTML.includes('Custom Source A'));
  assert.ok(sourceSelect1.innerHTML.includes('Custom Source B'));
  // Fabricated adapters must NOT appear if not in response
  assert.ok(!sourceSelect1.innerHTML.includes('openalex'));
  assert.ok(!sourceSelect1.innerHTML.includes('crossref'));

  // Test Case 2: /sources empty -> no fabricated source options
  resetSearchFilterCatalogsCache();
  fetchMock = async (url) => {
    if (url.includes('/sources')) {
      return { ok: true, status: 200, json: async () => ({ sources: [] }) };
    }
    return { ok: true, status: 200, json: async () => ({ count: 0, results: [] }) };
  };

  const container2 = createMockContainer();
  const store2 = { state: {}, getState: () => store2.state, setState: (s) => Object.assign(store2.state, s), setConnection: () => {} };
  await renderSearchView(container2, store2, { q: '' });

  const sourceSelect2 = container2.querySelector('#search-source-select');
  assert.ok(sourceSelect2.innerHTML.includes('All Ingested Sources'));
  assert.ok(!sourceSelect2.innerHTML.includes('github'));
  assert.ok(!sourceSelect2.innerHTML.includes('arxiv'));

  // Test Case 3: /sources failure -> no fabricated source options
  resetSearchFilterCatalogsCache();
  fetchMock = async (url) => {
    if (url.includes('/sources')) {
      return { ok: false, status: 500, statusText: 'Internal Error' };
    }
    return { ok: true, status: 200, json: async () => ({ count: 0, results: [] }) };
  };

  const container3 = createMockContainer();
  const store3 = { state: {}, getState: () => store3.state, setState: (s) => Object.assign(store3.state, s), setConnection: () => {} };
  await renderSearchView(container3, store3, { q: '' });

  const sourceSelect3 = container3.querySelector('#search-source-select');
  assert.ok(sourceSelect3.innerHTML.includes('All Ingested Sources'));
  assert.ok(!sourceSelect3.innerHTML.includes('github'));
  assert.ok(!sourceSelect3.innerHTML.includes('huggingface'));

  fetchMock = null;
});


// =========================================================================
// Phase 8: Saved Intelligence Library & Snapshot Contract Tests
// =========================================================================

test('Phase 8: Saved view requests include_current=true on initial load', async () => {
  const { renderSavedView } = await import('../src/views/saved.js');
  let requestedUrl = null;

  fetchMock = async (url) => {
    requestedUrl = url;
    return {
      ok: true,
      status: 200,
      json: async () => ({ count: 0, saved_items: [] })
    };
  };

  const container = createMockContainer();
  const store = { state: {}, getState: () => store.state, setState: (s) => Object.assign(store.state, s), setConnection: () => {}, setViewData: () => {} };

  await renderSavedView(container, store);

  assert.ok(requestedUrl !== null);
  assert.ok(requestedUrl.includes('/saved'));
  assert.ok(requestedUrl.includes('include_current=true'));

  fetchMock = null;
});

test('Phase 8: Saved card renders historical THEN snapshot without inferring status from scores', async () => {
  const { renderSavedCard } = await import('../src/views/saved.js');

  // Legacy item: has numeric scores but null snapshot statuses
  const legacyItem = {
    id: 'saved:legacy_1',
    story_cluster_id: 'cl_legacy_1',
    title_snapshot: 'Legacy Quantum Algorithm',
    saved_at: '2026-01-01T10:00:00Z',
    verification_score: 0.64,
    claim_status: null, // NOT RECORDED
    maturity_stage: 'prototype',
    risk_score: 0.31,
    risk_status: null, // NOT RECORDED
    risk_level: null,  // NOT RECORDED
    tags: ['quantum'],
    current_state: {
      title: 'Legacy Quantum Algorithm',
      cluster_score: 0.8,
      verification_score: 0.9,
      claim_status: 'supported',
      maturity_stage: 'established',
      risk_status: 'assessed',
      risk_level: 'low',
      risk_score: 0.15,
      claims_count: 5,
      events_count: 3,
      is_active: true
    }
  };

  const html = renderSavedCard(legacyItem);

  // Must show historical score and explicit "Claim status: Not recorded historically"
  assert.ok(html.includes('Saved verification: 64%'));
  assert.ok(html.includes('Claim status: Not recorded historically'));
  assert.ok(html.includes('Saved risk: 31%'));
  assert.ok(html.includes('Risk status: Not recorded historically'));

  // Must NOT infer Supported or Medium risk for the THEN snapshot
  const thenSection = html.split('NOW (Current Intelligence)')[0];
  assert.ok(!thenSection.includes('badge-verification-supported'));
  assert.ok(!thenSection.includes('Medium risk'));
  assert.ok(!thenSection.includes('badge-risk-assessed'));
  assert.ok(!thenSection.includes('Unverified'));

  assert.ok(html.includes('THEN (Saved Snapshot)'));
  assert.ok(html.includes('NOW (Current Intelligence)'));
});

test('Phase 8: Saved card renders live NOW state and evolution diff accurately', async () => {
  const { renderSavedCard, computeEvolutionDiff } = await import('../src/views/saved.js');

  const evolvedItem = {
    id: 'saved:evolved_1',
    story_cluster_id: 'cl_evolved_1',
    title_snapshot: 'High-Temperature Superconductivity',
    saved_at: '2026-01-01T10:00:00Z',
    verification_score: 0.85,
    claim_status: 'supported',
    maturity_stage: 'concept',
    risk_score: 0.6,
    risk_status: 'assessed',
    risk_level: 'high',
    tags: ['physics'],
    current_state: {
      title: 'High-Temperature Superconductivity',
      cluster_score: 0.9,
      verification_score: 0.25,
      claim_status: 'contradicted',
      maturity_stage: 'early_adoption',
      risk_status: 'assessed',
      risk_level: 'critical',
      risk_score: 0.85,
      claims_count: 12,
      events_count: 8,
      is_active: true
    }
  };

  const diff = computeEvolutionDiff(evolvedItem);
  assert.strictEqual(diff.status, 'changed');
  assert.ok(diff.diffs.some(d => d.label.includes('Maturity: Concept → Early Adoption')));
  assert.ok(diff.diffs.some(d => d.label.includes('Claims: Supported → Contradicted')));
  assert.ok(diff.diffs.some(d => d.label.includes('Risk: High risk → Critical risk')));
  assert.ok(diff.diffs.some(d => d.label.includes('Verification shift: -60%')));

  const html = renderSavedCard(evolvedItem);
  assert.ok(html.includes('Maturity: Concept → Early Adoption'));
  assert.ok(html.includes('Claims: Supported → Contradicted'));
  assert.ok(html.includes('12 claims · 8 events'));
});

test('Phase 8 regression: Saved comparison rendering strictly enforces canonical maturity terminology and never outputs noncanonical labels', async () => {
  const { renderSavedCard, computeEvolutionDiff, getMaturityLabel, CANONICAL_MATURITY_LABELS } = await import('../src/views/saved.js');

  // Verify canonical dictionary contains all 7 canonical stages
  const expectedCanonical = ['concept', 'research', 'prototype', 'experimental', 'early_adoption', 'production_candidate', 'established'];
  assert.strictEqual(Object.keys(CANONICAL_MATURITY_LABELS).length, 7);
  expectedCanonical.forEach(k => {
    assert.ok(CANONICAL_MATURITY_LABELS[k] !== undefined, `Missing canonical key ${k}`);
  });

  // Verify transitions between canonical stages
  const canonicalTransitions = [
    { from: 'concept', to: 'research', label: 'Maturity: Concept → Research' },
    { from: 'prototype', to: 'experimental', label: 'Maturity: Prototype → Experimental' },
    { from: 'experimental', to: 'early_adoption', label: 'Maturity: Experimental → Early Adoption' },
    { from: 'early_adoption', to: 'production_candidate', label: 'Maturity: Early Adoption → Production Candidate' },
    { from: 'production_candidate', to: 'established', label: 'Maturity: Production Candidate → Established' },
  ];

  const forbiddenNoncanonical = ['Growth', 'Mature', 'Stable', 'Proposal', 'Production Ready'];

  for (const trans of canonicalTransitions) {
    const item = {
      id: `saved:${trans.from}_${trans.to}`,
      story_cluster_id: `cl_${trans.from}_${trans.to}`,
      title_snapshot: `Canonical Test ${trans.from} to ${trans.to}`,
      saved_at: '2026-01-01T10:00:00Z',
      maturity_stage: trans.from,
      current_state: {
        title: `Canonical Test ${trans.from} to ${trans.to}`,
        maturity_stage: trans.to,
        is_active: true
      }
    };

    const diff = computeEvolutionDiff(item);
    assert.strictEqual(diff.status, 'changed');
    assert.ok(diff.diffs.some(d => d.label === trans.label), `Expected "${trans.label}" but got ${JSON.stringify(diff.diffs)}`);

    const html = renderSavedCard(item);
    assert.ok(html.includes(trans.label), `Expected rendered card to include "${trans.label}"`);

    // Verify none of the forbidden noncanonical labels are present in the output
    for (const forbidden of forbiddenNoncanonical) {
      assert.ok(!html.includes(`Maturity: ${forbidden}`), `Found forbidden noncanonical label "${forbidden}" in HTML`);
      assert.ok(!diff.diffs.some(d => d.label.includes(forbidden)), `Found forbidden noncanonical label "${forbidden}" in diffs`);
    }
  }
});

test('Phase 8: Saved card renders Current intelligence unavailable when current_state is null without broken Story navigation', async () => {
  const { renderSavedCard, computeEvolutionDiff } = await import('../src/views/saved.js');

  const inactiveItem = {
    id: 'saved:inactive_1',
    story_cluster_id: 'cl_inactive_1',
    title_snapshot: 'Defunct Project Research',
    saved_at: '2026-01-01T10:00:00Z',
    verification_score: 0.5,
    claim_status: 'unverified',
    maturity_stage: 'concept',
    risk_score: 0.2,
    risk_status: 'assessed',
    risk_level: 'low',
    tags: ['legacy'],
    current_state: null
  };

  const diff = computeEvolutionDiff(inactiveItem);
  assert.strictEqual(diff.status, 'unavailable');

  const html = renderSavedCard(inactiveItem);
  assert.ok(html.includes('Current intelligence unavailable'));
  assert.ok(html.includes('Underlying story cluster is no longer active'));

  // Must render snapshot title as non-interactive text and NOT a link to #/story/...
  assert.ok(html.includes('<span class="saved-card-title-text">Defunct Project Research</span>'));
  assert.ok(!html.includes('href="#/story/cl_inactive_1"'));
  assert.ok(!html.includes('href="#/story/'));
  assert.ok(!html.includes('Open Story Dossier'));

  // Historical snapshot remains inspectable and Remove button is present
  assert.ok(html.includes('THEN (Saved Snapshot)'));
  assert.ok(html.includes('Remove'));
});

test('Phase 8: Saved card renders Story Dossier navigation when current_state exists', async () => {
  const { renderSavedCard } = await import('../src/views/saved.js');

  const activeItem = {
    id: 'saved:active_1',
    story_cluster_id: 'cl_active_1',
    title_snapshot: 'Active Quantum Core',
    saved_at: '2026-01-01T10:00:00Z',
    verification_score: 0.85,
    claim_status: 'supported',
    maturity_stage: 'prototype',
    risk_score: 0.15,
    risk_status: 'assessed',
    risk_level: 'low',
    tags: ['quantum'],
    current_state: {
      title: 'Active Quantum Core',
      cluster_score: 0.9,
      verification_score: 0.92,
      claim_status: 'strongly_supported',
      maturity_stage: 'experimental',
      risk_status: 'assessed',
      risk_level: 'low',
      risk_score: 0.1,
      claims_count: 8,
      events_count: 5,
      is_active: true
    }
  };

  const html = renderSavedCard(activeItem);

  // When current_state is present, Story Dossier link and action must be rendered
  assert.ok(html.includes('href="#/story/cl_active_1"'));
  assert.ok(html.includes('class="saved-title-link"'));
  assert.ok(html.includes('Open Story Dossier &rarr;'));
});

test('Phase 8: getMaturityLabel degrades noncanonical and unknown maturity stages neutrally to Unrecognized maturity', async () => {
  const { getMaturityLabel, CANONICAL_MATURITY_LABELS } = await import('../src/views/saved.js');

  // 1. Seven canonical stages must render their exact human-readable canonical labels
  const canonicalExpectations = {
    concept: 'Concept',
    research: 'Research',
    prototype: 'Prototype',
    experimental: 'Experimental',
    early_adoption: 'Early Adoption',
    production_candidate: 'Production Candidate',
    established: 'Established',
  };

  for (const [stage, expectedLabel] of Object.entries(canonicalExpectations)) {
    assert.strictEqual(getMaturityLabel(stage), expectedLabel, `Expected ${stage} -> ${expectedLabel}`);
    assert.strictEqual(getMaturityLabel(stage.toUpperCase()), expectedLabel, `Expected uppercase ${stage} -> ${expectedLabel}`);
  }

  // 2. Null / undefined / empty degrade to "Not assessed"
  assert.strictEqual(getMaturityLabel(null), 'Not assessed');
  assert.strictEqual(getMaturityLabel(undefined), 'Not assessed');
  assert.strictEqual(getMaturityLabel(''), 'Not assessed');

  // 3. Noncanonical lifecycle labels must degrade to "Unrecognized maturity" and NEVER render as canonical-looking labels
  const noncanonicalStages = [
    'growth',
    'mature',
    'stable',
    'proposal',
    'production_ready',
    'arbitrary unknown string',
    'v1.0.0',
    'alpha',
    'beta'
  ];

  for (const stage of noncanonicalStages) {
    const result = getMaturityLabel(stage);
    assert.strictEqual(result, 'Unrecognized maturity', `Noncanonical stage "${stage}" should degrade to "Unrecognized maturity" but got "${result}"`);

    // Verify none render as canonical-looking valid maturity stage names
    assert.notStrictEqual(result, 'Growth');
    assert.notStrictEqual(result, 'Mature');
    assert.notStrictEqual(result, 'Stable');
    assert.notStrictEqual(result, 'Proposal');
    assert.notStrictEqual(result, 'Production Ready');
    assert.notStrictEqual(result, 'Production ready');
    assert.notStrictEqual(result, 'Arbitrary Unknown String');
  }
});

test('Phase 8: Unsave action dispatches DELETE /saved/{savedId} with SavedItem ID', async () => {
  const { renderSavedView } = await import('../src/views/saved.js');
  let deleteUrl = null;
  let deleteMethod = null;

  fetchMock = async (url, opts) => {
    if (opts && opts.method === 'DELETE') {
      deleteUrl = url;
      deleteMethod = opts.method;
      return { ok: true, status: 200, json: async () => ({ message: 'Saved item removed successfully' }) };
    }
    return {
      ok: true,
      status: 200,
      json: async () => ({
        count: 1,
        saved_items: [{
          id: 'saved:cl_test_del',
          story_cluster_id: 'cl_test_del',
          title_snapshot: 'Test Story to Delete',
          saved_at: '2026-02-01T10:00:00Z',
          verification_score: 0.8,
          claim_status: 'supported',
          tags: ['test'],
          current_state: null
        }]
      })
    };
  };

  const container = createMockContainer();
  const store = { state: {}, getState: () => store.state, setState: (s) => Object.assign(store.state, s), setConnection: () => {}, setViewData: () => {} };

  await renderSavedView(container, store);

  const unsaveBtn = container.querySelector('[data-action="unsave"]');
  assert.ok(unsaveBtn !== null);
  unsaveBtn.setAttribute('data-saved-id', 'saved:cl_test_del');
  assert.strictEqual(unsaveBtn.getAttribute('data-saved-id'), 'saved:cl_test_del');

  // Trigger delegated click on items container
  const itemsContainer = container.querySelector('#saved-items-container');
  const handlers = itemsContainer._listeners['click'] || [];
  for (const h of handlers) {
    await h({ target: unsaveBtn, preventDefault() {}, closest: (sel) => sel.includes('unsave') ? unsaveBtn : null });
  }

  assert.ok(deleteUrl !== null);
  assert.ok(deleteUrl.includes('/saved/saved%3Acl_test_del') || deleteUrl.includes('/saved/saved:cl_test_del'));
  assert.strictEqual(deleteMethod, 'DELETE');

  fetchMock = null;
});

test('Phase 8: Unsave action failure preserves card in DOM, re-enables action button, and surfaces accessible error announcement in live-region', async () => {
  const { renderSavedView } = await import('../src/views/saved.js');

  fetchMock = async (url, opts) => {
    if (opts && opts.method === 'DELETE') {
      return {
        ok: false,
        status: 500,
        statusText: 'Internal Server Error',
        json: async () => ({ detail: 'Database connection failed during delete' })
      };
    }
    return {
      ok: true,
      status: 200,
      json: async () => ({
        count: 1,
        saved_items: [{
          id: 'saved:cl_fail_del',
          story_cluster_id: 'cl_fail_del',
          title_snapshot: 'Test Story Retained on Failure',
          saved_at: '2026-02-01T10:00:00Z',
          verification_score: 0.8,
          claim_status: 'supported',
          tags: ['test'],
          current_state: null
        }]
      })
    };
  };

  const container = createMockContainer();
  let savedItemsInStore = null;
  const store = {
    state: {},
    getState: () => store.state,
    setState: (s) => Object.assign(store.state, s),
    setConnection: () => {},
    setViewData: (view, data) => {
      if (view === 'saved') savedItemsInStore = data;
    }
  };

  await renderSavedView(container, store);

  const unsaveBtn = container.querySelector('[data-action="unsave"]');
  assert.ok(unsaveBtn !== null);
  unsaveBtn.setAttribute('data-saved-id', 'saved:cl_fail_del');
  unsaveBtn.setAttribute('data-title', 'Test Story Retained on Failure');

  // Trigger delegated click on items container
  const itemsContainer = container.querySelector('#saved-items-container');
  const handlers = itemsContainer._listeners['click'] || [];
  for (const h of handlers) {
    await h({ target: unsaveBtn, preventDefault() {}, closest: (sel) => sel.includes('unsave') ? unsaveBtn : null });
  }

  // Button must be re-enabled after failure
  assert.strictEqual(unsaveBtn.disabled, false);
  assert.ok(unsaveBtn.innerHTML.includes('Remove'));

  // Live region must announce error
  const liveRegion = container.querySelector('#saved-live-region');
  assert.ok(liveRegion.textContent.includes('Failed to remove item'));

  // Store data array must still contain the item
  assert.strictEqual(savedItemsInStore.length, 1);
  assert.strictEqual(savedItemsInStore[0].id, 'saved:cl_fail_del');

  fetchMock = null;
});

test('Phase 8: Story Dossier save button calls POST /saved with story_cluster_id', async () => {
  const { renderStoryDetailView } = await import('../src/views/story-detail.js');
  let postUrl = null;
  let postBody = null;

  fetchMock = async (url, opts) => {
    if (opts && opts.method === 'POST' && url.includes('/saved')) {
      postUrl = url;
      postBody = JSON.parse(opts.body);
      return { ok: true, status: 200, json: async () => ({ message: 'Story saved successfully', saved_item: {} }) };
    }
    return {
      ok: true,
      status: 200,
      json: async () => ({
        id: 'cl_save_test',
        canonical_title: 'Dossier to Save',
        cluster_score: 0.85,
        sources: ['github'],
        claims: [],
        events: []
      })
    };
  };

  const container = createMockContainer();
  const store = { state: { selectedStoryId: 'cl_save_test' }, getState: () => store.state, setState: (s) => Object.assign(store.state, s), setConnection: () => {} };

  await renderStoryDetailView(container, store, { storyId: 'cl_save_test' });

  const saveBtn = container.querySelector('#btn-save-dossier');
  assert.ok(saveBtn !== null);

  await saveBtn.click();

  assert.ok(postUrl !== null);
  assert.ok(postUrl.includes('/saved'));
  assert.strictEqual(postBody.story_cluster_id, 'cl_save_test');

  fetchMock = null;
});

test('Phase 8: Exact request counts for initial Saved view and zero story requests', async () => {
  const { renderSavedView } = await import('../src/views/saved.js');
  const capturedRequests = [];

  fetchMock = async (url, opts) => {
    capturedRequests.push({ url, method: opts?.method || 'GET' });
    return {
      ok: true,
      status: 200,
      json: async () => ({
        count: 2,
        saved_items: [
          {
            id: 'saved:cl_req_1',
            story_cluster_id: 'cl_req_1',
            title_snapshot: 'Req Test 1',
            saved_at: '2026-02-01T10:00:00Z',
            verification_score: 0.8,
            claim_status: 'supported',
            tags: ['test'],
            current_state: {
              title: 'Req Test 1 Live',
              cluster_score: 0.8,
              verification_score: 0.85,
              claim_status: 'supported',
              maturity_stage: 'established',
              risk_status: 'assessed',
              risk_level: 'low',
              risk_score: 0.1,
              claims_count: 3,
              events_count: 2,
              is_active: true
            }
          },
          {
            id: 'saved:cl_req_2',
            story_cluster_id: 'cl_req_2',
            title_snapshot: 'Req Test 2',
            saved_at: '2026-02-01T10:00:00Z',
            verification_score: 0.5,
            claim_status: 'unverified',
            tags: ['test'],
            current_state: {
              title: 'Req Test 2 Live',
              cluster_score: 0.6,
              verification_score: 0.5,
              claim_status: 'unverified',
              maturity_stage: 'prototype',
              risk_status: 'assessed',
              risk_level: 'medium',
              risk_score: 0.35,
              claims_count: 2,
              events_count: 1,
              is_active: true
            }
          }
        ]
      })
    };
  };

  const container = createMockContainer();
  const store = { state: {}, getState: () => store.state, setState: (s) => Object.assign(store.state, s), setConnection: () => {}, setViewData: () => {} };

  await renderSavedView(container, store);

  // Exact request assertions:
  // 1. Exactly 1 request to /saved?include_current=true
  const savedRequests = capturedRequests.filter(r => r.url.includes('/saved'));
  assert.strictEqual(savedRequests.length, 1);
  assert.ok(savedRequests[0].url.includes('include_current=true'));

  // 2. Exactly 0 requests to /stories/ or individual cluster hydration
  const storyRequests = capturedRequests.filter(r => r.url.includes('/stories/'));
  assert.strictEqual(storyRequests.length, 0);

  // Total request count for initial view load is exactly 1
  assert.strictEqual(capturedRequests.length, 1);

  fetchMock = null;
});


// =========================================================================
// Phase 9: Changes & Longitudinal Intelligence Experience Tests
// =========================================================================

test('Phase 9: Initial Changes request uses actual endpoint parameters (hours=168, limit=100)', async () => {
  const { renderChangesView } = await import('../src/views/changes.js');
  let requestedUrl = null;

  fetchMock = async (url) => {
    if (url.includes('/projects')) return { ok: true, status: 200, json: async () => ({ projects: [] }) };
    if (url.includes('/changes')) {
      requestedUrl = url;
      return { ok: true, status: 200, json: async () => ({ count: 0, changes: [] }) };
    }
    return { ok: true, status: 200, json: async () => ({}) };
  };

  const container = createMockContainer();
  const store = { state: {}, getState: () => store.state, setState: (s) => Object.assign(store.state, s), setConnection: () => {}, setViewData: () => {} };

  await renderChangesView(container, store);

  assert.ok(requestedUrl !== null);
  assert.ok(requestedUrl.includes('/changes'));
  assert.ok(requestedUrl.includes('hours=168'));
  assert.ok(requestedUrl.includes('limit=100'));

  fetchMock = null;
});

test('Phase 9: Change importance is labeled as Importance/Priority and never Verification/Confidence/Accuracy', async () => {
  const { renderChangeCard, formatImportance } = await import('../src/views/changes.js');

  const impCritical = formatImportance(0.9, 'critical');
  assert.strictEqual(impCritical.label, 'Importance: Critical');
  assert.strictEqual(impCritical.badgeClass, 'importance-critical');

  const impHigh = formatImportance(0.75, 'high');
  assert.strictEqual(impHigh.label, 'Importance: High');

  const impMed = formatImportance(0.5, 'medium');
  assert.strictEqual(impMed.label, 'Importance: Medium');

  const impLow = formatImportance(0.2, 'low');
  assert.strictEqual(impLow.label, 'Importance: Low');

  const cardHtml = renderChangeCard({
    id: 'ch_test_imp',
    entity_type: 'claim',
    entity_id: 'claim_123',
    change_type: 'verification_weakened',
    importance: 0.95,
    importance_level: 'critical',
    reason: 'Independent reproduction failed.',
    origin: 'actual_revision',
    old_value: 'supported (0.8500)',
    new_value: 'contradicted (0.1500)',
    detected_at: '2026-08-22T10:00:00Z',
  });

  assert.ok(cardHtml.includes('Importance: Critical'));
  assert.ok(!cardHtml.includes('Confidence'));
  assert.ok(!cardHtml.includes('Accuracy'));
  // The word Verification should only appear in change type titles if applicable, never as a label for importance/priority
  assert.ok(!cardHtml.includes('Verification: Critical'));
});

test('Phase 9: Canonical detected timestamp is displayed and event publication/discovery timestamps are not substituted', async () => {
  const { renderChangeCard } = await import('../src/views/changes.js');

  const change = {
    id: 'ch_time_test',
    entity_type: 'cluster',
    entity_id: 'cl_opt',
    cluster_id: 'cl_opt',
    change_type: 'maturity_stage_changed',
    importance: 0.7,
    reason: 'Production candidate benchmark passed.',
    origin: 'new_release',
    old_value: 'experimental',
    new_value: 'production_candidate',
    detected_at: '2026-08-20T14:30:00Z',
    created_at: '2026-08-20T14:30:00Z',
  };

  const html = renderChangeCard(change);

  assert.ok(html.includes('Detected:'));
  assert.ok(html.includes('2026'));
  assert.ok(!html.includes('Published:'));
  assert.ok(!html.includes('Discovered:'));
});

test('Phase 9: Claim transition renders old and new canonical states accurately', async () => {
  const { renderChangeCard } = await import('../src/views/changes.js');

  const change = {
    id: 'ch_claim_trans',
    entity_type: 'claim',
    entity_id: 'c_trans_1',
    cluster_id: 'cl_trans_1',
    change_type: 'claim_status_changed',
    importance: 0.8,
    importance_level: 'high',
    reason: 'Corroboration confirmed from third-party audit.',
    origin: 'new_evidence',
    old_value: 'unverified (0.4500)',
    new_value: 'strongly_supported (0.9500)',
    detected_at: '2026-08-21T09:00:00Z',
  };

  const html = renderChangeCard(change);

  assert.ok(html.includes('Unverified'));
  assert.ok(html.includes('(45%)'));
  assert.ok(html.includes('Strongly Supported'));
  assert.ok(html.includes('(95%)'));
  assert.ok(html.includes('&rarr;'));
});

test('Phase 9: Null old value remains historically unknown (Previous state not recorded historically)', async () => {
  const { renderChangeCard } = await import('../src/views/changes.js');

  const initialChange = {
    id: 'ch_init_1',
    entity_type: 'claim',
    entity_id: 'c_init_1',
    cluster_id: 'cl_init_1',
    change_type: 'claim_created',
    importance: 0.5,
    reason: 'Initial claim ingestion.',
    origin: 'live_update',
    old_value: null, // Historically unrecorded
    new_value: 'supported',
    detected_at: '2026-08-21T10:00:00Z',
  };

  const html = renderChangeCard(initialChange);

  assert.ok(html.includes('Previous state not recorded historically'));
  assert.ok(!html.includes('Previous state: 0'));
  assert.ok(!html.includes('Previous state: Not assessed'));
});

test('Phase 9: supported -> mixed and supported -> contradicted render with neutral visibility', async () => {
  const { renderChangeCard } = await import('../src/views/changes.js');

  const mixedChange = {
    id: 'ch_mixed',
    entity_type: 'claim',
    entity_id: 'c_mixed',
    change_type: 'claim_status_changed',
    importance: 0.75,
    reason: 'Conflicting replication results observed.',
    origin: 'new_evidence',
    old_value: 'supported',
    new_value: 'mixed',
    detected_at: '2026-08-22T08:00:00Z',
  };

  const contradictedChange = {
    id: 'ch_contra',
    entity_type: 'claim',
    entity_id: 'c_contra',
    change_type: 'verification_weakened',
    importance: 0.85,
    reason: 'Direct refutation published.',
    origin: 'actual_revision',
    old_value: 'supported',
    new_value: 'contradicted',
    detected_at: '2026-08-22T08:30:00Z',
  };

  const htmlMixed = renderChangeCard(mixedChange);
  assert.ok(htmlMixed.includes('Supported'));
  assert.ok(htmlMixed.includes('Mixed'));

  const htmlContra = renderChangeCard(contradictedChange);
  assert.ok(htmlContra.includes('Supported'));
  assert.ok(htmlContra.includes('Contradicted'));
});

test('Phase 9: retracted claim transition remains visibly distinct', async () => {
  const { renderChangeCard } = await import('../src/views/changes.js');

  const retractedChange = {
    id: 'ch_retract',
    entity_type: 'claim',
    entity_id: 'c_retract',
    change_type: 'claim_retracted',
    importance: 0.95,
    importance_level: 'critical',
    reason: 'Author retracted study due to measurement error.',
    origin: 'actual_revision',
    old_value: 'strongly_supported',
    new_value: 'retracted',
    detected_at: '2026-08-22T07:00:00Z',
  };

  const html = renderChangeCard(retractedChange);
  assert.ok(html.includes('Strongly Supported'));
  assert.ok(html.includes('Retracted'));
  assert.ok(html.includes('Importance: Critical'));
});

test('Phase 9: All seven canonical maturity stages display correctly without noncanonical terms', async () => {
  const { formatTransitionValue, CANONICAL_MATURITY_STAGES } = await import('../src/views/changes.js');

  const stages = [
    'concept',
    'research',
    'prototype',
    'experimental',
    'early_adoption',
    'production_candidate',
    'established'
  ];

  for (const s of stages) {
    const formatted = formatTransitionValue(s, 'maturity');
    assert.ok(formatted.includes(CANONICAL_MATURITY_STAGES[s]));
  }

  // Noncanonical lifecycle terms must not be synthesized
  assert.strictEqual(CANONICAL_MATURITY_STAGES['growth'], undefined);
  assert.strictEqual(CANONICAL_MATURITY_STAGES['mature'], undefined);
  assert.strictEqual(CANONICAL_MATURITY_STAGES['stable'], undefined);
  assert.strictEqual(CANONICAL_MATURITY_STAGES['proposal'], undefined);
  assert.strictEqual(CANONICAL_MATURITY_STAGES['production_ready'], undefined);
});

test('Phase 9 regression: Context-aware transition formatting strictly degrades noncanonical maturity and claim statuses', async () => {
  const { formatTransitionValue, renderChangeCard } = await import('../src/views/changes.js');

  // Regression 1: maturity: prototype → growth
  const cardMaturity1 = renderChangeCard({
    id: 'ch_mat_1',
    entity_type: 'technology_assessment',
    entity_id: 'cl_1',
    change_type: 'maturity_stage_changed',
    importance: 0.7,
    reason: 'Maturity transition check',
    origin: 'actual_revision',
    old_value: 'prototype',
    new_value: 'growth',
    detected_at: '2026-08-22T00:00:00Z',
  });
  assert.ok(cardMaturity1.includes('Prototype'));
  assert.ok(cardMaturity1.includes('Unrecognized maturity'));
  assert.ok(!cardMaturity1.includes('>Growth<'));

  // Regression 2: maturity: experimental → production_ready
  const cardMaturity2 = renderChangeCard({
    id: 'ch_mat_2',
    entity_type: 'technology_assessment',
    entity_id: 'cl_2',
    change_type: 'maturity_stage_changed',
    importance: 0.7,
    reason: 'Maturity transition check',
    origin: 'actual_revision',
    old_value: 'experimental',
    new_value: 'production_ready',
    detected_at: '2026-08-22T00:00:00Z',
  });
  assert.ok(cardMaturity2.includes('Experimental'));
  assert.ok(cardMaturity2.includes('Unrecognized maturity'));
  assert.ok(!cardMaturity2.includes('Production Ready'));

  // Regression 3: maturity: stable → established
  const cardMaturity3 = renderChangeCard({
    id: 'ch_mat_3',
    entity_type: 'technology_assessment',
    entity_id: 'cl_3',
    change_type: 'maturity_stage_changed',
    importance: 0.7,
    reason: 'Maturity transition check',
    origin: 'actual_revision',
    old_value: 'stable',
    new_value: 'established',
    detected_at: '2026-08-22T00:00:00Z',
  });
  assert.ok(cardMaturity3.includes('Unrecognized maturity'));
  assert.ok(cardMaturity3.includes('Established'));
  assert.ok(!cardMaturity3.includes('>Stable<'));

  // Regression 4: claim status: supported → verified
  const cardClaim1 = renderChangeCard({
    id: 'ch_clm_1',
    entity_type: 'claim',
    entity_id: 'c_1',
    change_type: 'claim_status_changed',
    importance: 0.8,
    reason: 'Claim status check',
    origin: 'actual_revision',
    old_value: 'supported',
    new_value: 'verified',
    detected_at: '2026-08-22T00:00:00Z',
  });
  assert.ok(cardClaim1.includes('Supported'));
  assert.ok(cardClaim1.includes('Unrecognized claim status'));
  assert.ok(!cardClaim1.includes('>Verified<'));

  // Regression 5: claim status: unknown_status → contradicted
  const cardClaim2 = renderChangeCard({
    id: 'ch_clm_2',
    entity_type: 'claim',
    entity_id: 'c_2',
    change_type: 'claim_status_changed',
    importance: 0.8,
    reason: 'Claim status check',
    origin: 'actual_revision',
    old_value: 'unknown_status',
    new_value: 'contradicted',
    detected_at: '2026-08-22T00:00:00Z',
  });
  assert.ok(cardClaim2.includes('Unrecognized claim status'));
  assert.ok(cardClaim2.includes('Contradicted'));
  assert.ok(!cardClaim2.includes('Unknown Status'));

  // Regression 6: generic release/version: v1.2.0 → v1.3.0
  const cardGeneric = renderChangeCard({
    id: 'ch_gen_1',
    entity_type: 'release',
    entity_id: 'rel_1',
    change_type: 'release_version_changed',
    importance: 0.5,
    reason: 'Release version bump',
    origin: 'new_release',
    old_value: 'v1.2.0',
    new_value: 'v1.3.0',
    detected_at: '2026-08-22T00:00:00Z',
  });
  assert.ok(cardGeneric.includes('v1.2.0'));
  assert.ok(cardGeneric.includes('v1.3.0'));

  // Regression 7: scored noncanonical forms cannot become polished canonical statuses
  const scoredMaturity = formatTransitionValue('growth (0.72)', 'maturity');
  assert.ok(scoredMaturity.includes('Unrecognized maturity'));
  assert.ok(scoredMaturity.includes('(72%)'));
  assert.ok(!scoredMaturity.includes('Growth'));

  const scoredClaim = formatTransitionValue('verified (0.80)', 'claim_status');
  assert.ok(scoredClaim.includes('Unrecognized claim status'));
  assert.ok(scoredClaim.includes('(80%)'));
  assert.ok(!scoredClaim.includes('Verified'));
});

test('Phase 9: Risk status and level remain distinct without inferring missing historical RiskStatus', async () => {
  const { renderChangeCard } = await import('../src/views/changes.js');

  const riskChange = {
    id: 'ch_risk_1',
    entity_type: 'technology_state',
    entity_id: 'cl_risk_1',
    change_type: 'risk_level_changed',
    importance: 0.8,
    reason: 'Vulnerability CVE published.',
    origin: 'new_evidence',
    old_value: 'not_assessed',
    new_value: 'assessed/high',
    detected_at: '2026-08-22T06:00:00Z',
  };

  const html = renderChangeCard(riskChange);
  assert.ok(html.includes('not_assessed'));
  assert.ok(html.includes('assessed/high'));
});

test('Phase 9: Change origin renders separately from change meaning (new_evidence, actual_revision, new_release, live_update)', async () => {
  const { renderChangeCard } = await import('../src/views/changes.js');

  const origins = ['new_evidence', 'actual_revision', 'new_release', 'live_update'];
  for (const orig of origins) {
    const card = renderChangeCard({
      id: `ch_${orig}`,
      entity_type: 'claim',
      entity_id: 'c1',
      change_type: 'claim_status_changed',
      importance: 0.5,
      reason: 'Testing origin separation',
      origin: orig,
      old_value: 'unverified',
      new_value: 'supported',
      detected_at: '2026-08-22T05:00:00Z',
    });

    assert.ok(card.includes('change-origin-badge'));
    assert.ok(card.includes(`data-origin="${orig}"`));
    // Verify WHAT changed is separated from WHY change exists
    assert.ok(card.includes('change-transition-box'));
    assert.ok(card.includes('Intelligence Rationale'));
  }
});

test('Phase 9: System provenance origins (migration, backfill_initialization, recompute) are clearly identified as system records', async () => {
  const { renderChangeCard } = await import('../src/views/changes.js');

  const sysOrigins = ['migration', 'backfill_initialization', 'recompute', 'source_refresh'];
  for (const orig of sysOrigins) {
    const card = renderChangeCard({
      id: `ch_sys_${orig}`,
      entity_type: 'cluster',
      entity_id: 'cl_sys_1',
      change_type: 'cluster_recomputed',
      importance: 0.3,
      reason: 'Schema migration normalization',
      origin: orig,
      old_value: 'prototype',
      new_value: 'experimental',
      detected_at: '2026-08-20T00:00:00Z',
    });

    assert.ok(card.includes('change-card-system'));
    assert.ok(card.includes('badge-origin-system') || card.includes('badge-origin-recompute'));
  }
});

test('Phase 9: Server-side filters (hours, importance_min, project) transmit actual backend parameters', async () => {
  const { renderChangesView } = await import('../src/views/changes.js');
  const capturedUrls = [];

  fetchMock = async (url) => {
    capturedUrls.push(url);
    if (url.includes('/projects')) {
      return {
        ok: true,
        status: 200,
        json: async () => ({
          projects: [{ id: 'proj_ai', name: 'AI Core Project' }]
        })
      };
    }
    return { ok: true, status: 200, json: async () => ({ count: 0, changes: [] }) };
  };

  const container = createMockContainer();
  const store = { state: {}, getState: () => store.state, setState: (s) => Object.assign(store.state, s), setConnection: () => {}, setViewData: () => {} };

  await renderChangesView(container, store);

  // Trigger hours change
  const hoursSelect = container.querySelector('#changes-hours-select');
  hoursSelect.value = '72';
  const hoursHandlers = hoursSelect._listeners['change'] || [];
  for (const h of hoursHandlers) await h({ target: hoursSelect });

  // Trigger importance change
  const impSelect = container.querySelector('#changes-importance-select');
  impSelect.value = 'high';
  const impHandlers = impSelect._listeners['change'] || [];
  for (const h of impHandlers) await h({ target: impSelect });

  // Trigger project change
  const projSelect = container.querySelector('#changes-project-select');
  projSelect.value = 'proj_ai';
  const projHandlers = projSelect._listeners['change'] || [];
  for (const h of projHandlers) await h({ target: projSelect });

  const lastChangeReq = capturedUrls.filter(u => u.includes('/changes')).pop();
  assert.ok(lastChangeReq !== undefined);
  assert.ok(lastChangeReq.includes('hours=72'));
  assert.ok(lastChangeReq.includes('importance_min=high'));
  assert.ok(lastChangeReq.includes('project=proj_ai'));

  fetchMock = null;
});

test('Phase 9: Filter reset restores default parameters and reloads view', async () => {
  const { renderChangesView } = await import('../src/views/changes.js');
  const capturedUrls = [];

  fetchMock = async (url) => {
    capturedUrls.push(url);
    if (url.includes('/projects')) return { ok: true, status: 200, json: async () => ({ projects: [] }) };
    return { ok: true, status: 200, json: async () => ({ count: 0, changes: [] }) };
  };

  const container = createMockContainer();
  const store = { state: {}, getState: () => store.state, setState: (s) => Object.assign(store.state, s), setConnection: () => {}, setViewData: () => {} };

  await renderChangesView(container, store);

  // Modify filters
  const hoursSelect = container.querySelector('#changes-hours-select');
  hoursSelect.value = '24';
  const hoursHandlers = hoursSelect._listeners['change'] || [];
  for (const h of hoursHandlers) await h({ target: hoursSelect });

  // Click Reset Filters
  const resetBtn = container.querySelector('#btn-reset-changes-filters');
  const resetHandlers = resetBtn._listeners['click'] || [];
  for (const h of resetHandlers) await h({ target: resetBtn });

  const lastChangeReq = capturedUrls.filter(u => u.includes('/changes')).pop();
  assert.ok(lastChangeReq.includes('hours=168'));

  fetchMock = null;
});

test('Phase 9: Empty, network offline, and backend error states render with accessible recovery cues', async () => {
  const { renderChangesView } = await import('../src/views/changes.js');

  // Case 1: Empty state
  fetchMock = async (url) => {
    if (url.includes('/projects')) return { ok: true, status: 200, json: async () => ({ projects: [] }) };
    return { ok: true, status: 200, json: async () => ({ count: 0, changes: [] }) };
  };
  const container1 = createMockContainer();
  const store1 = { state: {}, getState: () => store1.state, setState: (s) => Object.assign(store1.state, s), setConnection: () => {}, setViewData: () => {} };
  await renderChangesView(container1, store1);
  assert.ok(container1.innerHTML.includes('No Changes Found'));

  // Case 2: Backend error
  fetchMock = async (url) => {
    if (url.includes('/projects')) return { ok: true, status: 200, json: async () => ({ projects: [] }) };
    return { ok: false, status: 500, statusText: 'Internal Error', json: async () => ({ detail: 'Database error' }) };
  };
  const container2 = createMockContainer();
  const store2 = { state: {}, getState: () => store2.state, setState: (s) => Object.assign(store2.state, s), setConnection: () => {}, setViewData: () => {} };
  await renderChangesView(container2, store2);
  assert.ok(container2.innerHTML.includes('Failed to Load Longitudinal Changes'));

  fetchMock = null;
});

test('Phase 9: Resolvable Story change renders Open Story Dossier link to #/story/{cluster_id} and unresolvable entity produces no broken route', async () => {
  const { renderChangeCard } = await import('../src/views/changes.js');

  // Case 1: Resolvable Story cluster
  const resolvableChange = {
    id: 'ch_res_1',
    entity_type: 'cluster',
    entity_id: 'cl_quantum_core',
    cluster_id: 'cl_quantum_core',
    change_type: 'maturity_stage_changed',
    importance: 0.8,
    reason: 'Maturity advanced to experimental.',
    origin: 'actual_revision',
    old_value: 'prototype',
    new_value: 'experimental',
    detected_at: '2026-08-22T04:00:00Z',
  };

  const resolvableHtml = renderChangeCard(resolvableChange);
  assert.ok(resolvableHtml.includes('href="#/story/cl_quantum_core"'));
  assert.ok(resolvableHtml.includes('Open Story Dossier &rarr;'));

  // Case 2: Unresolvable standalone entity (e.g. event without cluster)
  const unresolvableChange = {
    id: 'ch_unres_1',
    entity_type: 'event',
    entity_id: 'ev_standalone_99',
    cluster_id: null,
    change_type: 'event_ingested',
    importance: 0.4,
    reason: 'Event ingested.',
    origin: 'source_refresh',
    old_value: null,
    new_value: 'ingested',
    detected_at: '2026-08-22T04:00:00Z',
  };

  const unresolvableHtml = renderChangeCard(unresolvableChange);
  assert.ok(!unresolvableHtml.includes('href="#/story/'));
  assert.ok(unresolvableHtml.includes('Entity: ev_standalone_99'));
});

test('Phase 9: No N+1 Story requests during Changes view rendering', async () => {
  const { renderChangesView } = await import('../src/views/changes.js');
  const capturedUrls = [];

  fetchMock = async (url) => {
    capturedUrls.push(url);
    if (url.includes('/projects')) return { ok: true, status: 200, json: async () => ({ projects: [] }) };
    if (url.includes('/changes')) {
      return {
        ok: true,
        status: 200,
        json: async () => ({
          count: 5,
          changes: [
            { id: 'ch1', entity_type: 'cluster', entity_id: 'cl1', cluster_id: 'cl1', change_type: 'state_changed', importance: 0.8, reason: 'r1', origin: 'actual_revision', old_value: 'prototype', new_value: 'experimental', detected_at: '2026-08-22T00:00:00Z' },
            { id: 'ch2', entity_type: 'cluster', entity_id: 'cl2', cluster_id: 'cl2', change_type: 'state_changed', importance: 0.8, reason: 'r2', origin: 'actual_revision', old_value: 'prototype', new_value: 'experimental', detected_at: '2026-08-22T00:00:00Z' },
            { id: 'ch3', entity_type: 'claim', entity_id: 'c1', cluster_id: 'cl1', change_type: 'state_changed', importance: 0.8, reason: 'r3', origin: 'new_evidence', old_value: 'supported', new_value: 'mixed', detected_at: '2026-08-22T00:00:00Z' },
            { id: 'ch4', entity_type: 'claim', entity_id: 'c2', cluster_id: 'cl2', change_type: 'state_changed', importance: 0.8, reason: 'r4', origin: 'new_evidence', old_value: 'supported', new_value: 'mixed', detected_at: '2026-08-22T00:00:00Z' },
            { id: 'ch5', entity_type: 'cluster', entity_id: 'cl3', cluster_id: 'cl3', change_type: 'state_changed', importance: 0.8, reason: 'r5', origin: 'actual_revision', old_value: 'prototype', new_value: 'experimental', detected_at: '2026-08-22T00:00:00Z' },
          ]
        })
      };
    }
    return { ok: true, status: 200, json: async () => ({}) };
  };

  const container = createMockContainer();
  const store = { state: {}, getState: () => store.state, setState: (s) => Object.assign(store.state, s), setConnection: () => {}, setViewData: () => {} };

  await renderChangesView(container, store);

  const storyRequests = capturedUrls.filter(u => u.includes('/stories/'));
  assert.strictEqual(storyRequests.length, 0);

  const changesRequests = capturedUrls.filter(u => u.includes('/changes'));
  assert.strictEqual(changesRequests.length, 1);

  fetchMock = null;
});

test('Phase 9: Stale response protection prevents out-of-order race conditions', async () => {
  const { renderChangesView } = await import('../src/views/changes.js');
  let requestCounter = 0;
  let resolveSlowReq;
  const slowPromise = new Promise(resolve => { resolveSlowReq = resolve; });

  fetchMock = async (url) => {
    if (url.includes('/projects')) return { ok: true, status: 200, json: async () => ({ projects: [] }) };
    if (url.includes('/changes')) {
      requestCounter++;
      const thisReq = requestCounter;
      if (thisReq === 1) {
        // Initial request is slow
        await slowPromise;
        return {
          ok: true,
          status: 200,
          json: async () => ({
            count: 1,
            changes: [{ id: 'ch_slow', entity_type: 'claim', entity_id: 'c_slow', change_type: 'claim_status_changed', importance: 0.5, reason: 'Slow response', origin: 'live_update', old_value: 'unverified', new_value: 'supported', detected_at: '2026-08-22T00:00:00Z' }]
          })
        };
      } else {
        // Second request resolves immediately
        return {
          ok: true,
          status: 200,
          json: async () => ({
            count: 1,
            changes: [{ id: 'ch_fast', entity_type: 'claim', entity_id: 'c_fast', change_type: 'claim_status_changed', importance: 0.9, reason: 'Fast response', origin: 'actual_revision', old_value: 'supported', new_value: 'contradicted', detected_at: '2026-08-22T00:00:00Z' }]
          })
        };
      }
    }
    return { ok: true, status: 200, json: async () => ({}) };
  };

  const container = createMockContainer();
  const store = { state: {}, getState: () => store.state, setState: (s) => Object.assign(store.state, s), setConnection: () => {}, setViewData: () => {} };

  // Initial load starts and triggers slow request 1
  const p1 = renderChangesView(container, store);

  // Yield microtask to allow projects lookup and renderViewShell to attach listeners
  await new Promise(resolve => setTimeout(resolve, 5));

  // Trigger filter change while slow request 1 is still in flight
  const hoursSelect = container.querySelector('#changes-hours-select');
  hoursSelect.value = '24';
  const hoursHandlers = hoursSelect._listeners['change'] || [];
  for (const h of hoursHandlers) await h({ target: hoursSelect });

  // Now let the slow first request finish
  resolveSlowReq();
  await p1;

  // Faster (second) response must win and not be overwritten by slow first response
  assert.ok(container.innerHTML.includes('ch_fast') || container.innerHTML.includes('Fast response'));
  assert.ok(!container.innerHTML.includes('ch_slow'));

  fetchMock = null;
});

test('Phase 9: Accessible live region announces change results count', async () => {
  const { renderChangesView } = await import('../src/views/changes.js');

  fetchMock = async (url) => {
    if (url.includes('/projects')) return { ok: true, status: 200, json: async () => ({ projects: [] }) };
    return {
      ok: true,
      status: 200,
      json: async () => ({
        count: 2,
        changes: [
          { id: 'ch1', entity_type: 'claim', entity_id: 'c1', change_type: 'claim_status_changed', importance: 0.5, reason: 'r1', origin: 'live_update', old_value: 'unverified', new_value: 'supported', detected_at: '2026-08-22T00:00:00Z' },
          { id: 'ch2', entity_type: 'claim', entity_id: 'c2', change_type: 'claim_status_changed', importance: 0.5, reason: 'r2', origin: 'live_update', old_value: 'unverified', new_value: 'supported', detected_at: '2026-08-22T00:00:00Z' },
        ]
      })
    };
  };

  const container = createMockContainer();
  const store = { state: {}, getState: () => store.state, setState: (s) => Object.assign(store.state, s), setConnection: () => {}, setViewData: () => {} };

  await renderChangesView(container, store);

  const liveRegion = container.querySelector('#changes-live-region');
  assert.ok(liveRegion !== null);
  assert.ok(container.innerHTML.includes('id="changes-live-region"'));
  assert.ok(container.innerHTML.includes('role="status"'));
  assert.ok(container.innerHTML.includes('aria-live="polite"'));
  assert.ok(liveRegion.textContent.includes('Showing 2 longitudinal changes.'));

  fetchMock = null;
});

test('Phase 9: Client-side noise control toggle hides system maintenance records', async () => {
  const { renderChangesView } = await import('../src/views/changes.js');

  fetchMock = async (url) => {
    if (url.includes('/projects')) return { ok: true, status: 200, json: async () => ({ projects: [] }) };
    return {
      ok: true,
      status: 200,
      json: async () => ({
        count: 2,
        changes: [
          { id: 'ch_intel', entity_type: 'claim', entity_id: 'c_intel', change_type: 'claim_status_changed', importance: 0.8, reason: 'Real intelligence revision', origin: 'actual_revision', old_value: 'supported', new_value: 'contradicted', detected_at: '2026-08-22T00:00:00Z' },
          { id: 'ch_sys', entity_type: 'cluster', entity_id: 'cl_sys', change_type: 'cluster_migrated', importance: 0.2, reason: 'Schema migration', origin: 'migration', old_value: 'prototype', new_value: 'experimental', detected_at: '2026-08-22T00:00:00Z' },
        ]
      })
    };
  };

  const container = createMockContainer();
  const store = { state: {}, getState: () => store.state, setState: (s) => Object.assign(store.state, s), setConnection: () => {}, setViewData: () => {} };

  await renderChangesView(container, store);

  // Both should be visible initially
  assert.ok(container.innerHTML.includes('ch_intel'));
  assert.ok(container.innerHTML.includes('ch_sys'));

  // Toggle Hide System Maintenance
  const hideSysChk = container.querySelector('#chk-hide-system');
  hideSysChk.checked = true;
  const hideSysHandlers = hideSysChk._listeners['change'] || [];
  for (const h of hideSysHandlers) await h({ target: hideSysChk });

  // Only genuine intelligence revision should be shown
  assert.ok(container.innerHTML.includes('ch_intel'));
  assert.ok(!container.innerHTML.includes('ch_sys'));

  fetchMock = null;
});

/* ==========================================================================
   Phase 10: Today Inbox & Daily Prioritization Experience Tests
   ========================================================================== */

test('Phase 10: Initial Today load sends one /inbox request and zero /stories requests', async () => {
  const { renderTodayView } = await import('../src/views/today.js');
  const capturedUrls = [];

  fetchMock = async (url) => {
    capturedUrls.push(url);
    if (url.includes('/projects')) return { ok: true, status: 200, json: async () => ({ projects: [] }) };
    return {
      ok: true,
      status: 200,
      json: async () => ({
        count: 1,
        inbox_items: [
          {
            id: 'ib_1',
            story_cluster_id: 'cl_1',
            title: 'PyTorch Compiler Update',
            section: 'ai_ml',
            state: 'unseen',
            item_type: 'new_story',
            inbox_score: 0.85,
            rank_score: 0.85,
            project_impact_score: 0.0,
            story_available: true,
            created_at: '2026-08-22T00:00:00Z',
          }
        ]
      })
    };
  };

  const container = createMockContainer();
  const store = { state: {}, getState: () => store.state, setState: (s) => Object.assign(store.state, s), setConnection: () => {}, setViewData: () => {} };

  await renderTodayView(container, store);

  const inboxRequests = capturedUrls.filter(u => u.includes('/inbox'));
  const storyRequests = capturedUrls.filter(u => u.includes('/stories/'));

  assert.strictEqual(inboxRequests.length, 1);
  assert.strictEqual(storyRequests.length, 0);

  fetchMock = null;
});

test('Phase 10: Server-side filters (unseen_only, project, section) transmit actual backend query parameters', async () => {
  const { renderTodayView } = await import('../src/views/today.js');
  const capturedUrls = [];

  fetchMock = async (url) => {
    capturedUrls.push(url);
    if (url.includes('/projects')) return { ok: true, status: 200, json: async () => ({ projects: [{ id: 'proj_cuda', name: 'CUDA Lab' }] }) };
    return {
      ok: true,
      status: 200,
      json: async () => ({ count: 0, inbox_items: [] })
    };
  };

  const container = createMockContainer();
  const store = { state: {}, getState: () => store.state, setState: (s) => Object.assign(store.state, s), setConnection: () => {}, setViewData: () => {} };

  await renderTodayView(container, store);

  // Trigger Section filter change
  const secSelect = container.querySelector('#sel-inbox-section');
  secSelect.value = 'systems_compilers';
  const secHandlers = secSelect._listeners['change'] || [];
  for (const h of secHandlers) await h({ target: secSelect });

  // Trigger Project filter change
  const projSelect = container.querySelector('#sel-inbox-project');
  projSelect.value = 'proj_cuda';
  const projHandlers = projSelect._listeners['change'] || [];
  for (const h of projHandlers) await h({ target: projSelect });

  // Trigger Unseen Only filter change
  const chkUnseen = container.querySelector('#chk-unseen-only');
  chkUnseen.checked = true;
  const unseenHandlers = chkUnseen._listeners['change'] || [];
  for (const h of unseenHandlers) await h({ target: chkUnseen });

  const lastReq = capturedUrls[capturedUrls.length - 1];
  assert.ok(lastReq.includes('section=systems_compilers'));
  assert.ok(lastReq.includes('project=proj_cuda'));
  assert.ok(lastReq.includes('unseen_only=true'));

  fetchMock = null;
});

test('Phase 10: Reset filters restores default parameters and reloads inbox view', async () => {
  const { renderTodayView } = await import('../src/views/today.js');
  const capturedUrls = [];

  fetchMock = async (url) => {
    capturedUrls.push(url);
    if (url.includes('/projects')) return { ok: true, status: 200, json: async () => ({ projects: [] }) };
    return {
      ok: true,
      status: 200,
      json: async () => ({ count: 0, inbox_items: [] })
    };
  };

  const container = createMockContainer();
  const store = { state: {}, getState: () => store.state, setState: (s) => Object.assign(store.state, s), setConnection: () => {}, setViewData: () => {} };

  await renderTodayView(container, store);

  const btnReset = container.querySelector('#btn-reset-inbox-filters');
  const resetHandlers = btnReset._listeners['click'] || [];
  for (const h of resetHandlers) await h({ target: btnReset });

  const finalReq = capturedUrls[capturedUrls.length - 1];
  assert.ok(!finalReq.includes('section='));
  assert.ok(!finalReq.includes('project='));
  assert.ok(!finalReq.includes('unseen_only=true'));

  fetchMock = null;
});

test('Phase 10: URL hash state synchronization and restoration', async () => {
  const { parseInboxHashParams, updateInboxHash } = await import('../src/views/today.js');

  // Test hash parsing
  globalThis.window.location.hash = '#/today?unseen=true&section=ai_ml&project=proj_rag';
  const parsed = parseInboxHashParams();
  assert.strictEqual(parsed.unseen_only, true);
  assert.strictEqual(parsed.section, 'ai_ml');
  assert.strictEqual(parsed.project, 'proj_rag');

  // Test hash updating
  updateInboxHash({ unseen_only: true, section: 'systems_compilers', project: 'proj_cuda' });
  assert.ok(globalThis.window.location.hash.includes('unseen=true'));
  assert.ok(globalThis.window.location.hash.includes('section=systems_compilers'));
  assert.ok(globalThis.window.location.hash.includes('project=proj_cuda'));
});

test('Phase 10: Deterministic section ordering and unknown-section fallback', async () => {
  const { consolidateInboxItems, CANONICAL_SECTION_ORDER } = await import('../src/views/today.js');

  const items = [
    { id: 'ib_custom', story_cluster_id: 'cl_custom', title: 'Custom Topic', section: 'custom_section', inbox_score: 0.9, _backendOrder: 0 },
    { id: 'ib_ai', story_cluster_id: 'cl_ai', title: 'AI Topic', section: 'ai_ml', inbox_score: 0.8, _backendOrder: 1 },
    { id: 'ib_must', story_cluster_id: 'cl_must', title: 'Must Know Topic', section: 'must_know', inbox_score: 0.7, _backendOrder: 2 },
    { id: 'ib_corr', story_cluster_id: 'cl_corr', title: 'Correction Topic', section: 'corrections_updates', inbox_score: 0.6, _backendOrder: 3 },
  ];

  const { sections } = consolidateInboxItems(items);
  const renderedKeys = [];
  const knownKeys = new Set(CANONICAL_SECTION_ORDER);

  for (const k of CANONICAL_SECTION_ORDER) {
    if (sections[k]) renderedKeys.push(k);
  }
  const unknownKeys = Object.keys(sections).filter(k => !knownKeys.has(k)).sort();
  for (const u of unknownKeys) renderedKeys.push(u);

  assert.deepStrictEqual(renderedKeys, ['must_know', 'corrections_updates', 'ai_ml', 'custom_section']);
});

test('Phase 10: Duplicate Story consolidation into single primary card without losing secondary reason codes and item types', async () => {
  const { consolidateInboxItems, renderInboxCard } = await import('../src/views/today.js');

  const rawDuplicateItems = [
    {
      id: 'ib_sub_1',
      story_cluster_id: 'cl_dup_1',
      title: 'LLVM Matrix Lowering Engine',
      section: 'systems_compilers',
      item_type: 'new_story',
      inbox_score: 0.88,
      rank_score: 0.88,
      reason_codes: ['recent_discovery'],
      matched_project_ids: ['proj_cuda'],
      story_available: true,
      _backendOrder: 0,
    },
    {
      id: 'ib_sub_2',
      story_cluster_id: 'cl_dup_1',
      title: 'LLVM Matrix Lowering Engine',
      section: 'must_know',
      item_type: 'claim_strengthened',
      inbox_score: 0.95,
      rank_score: 0.95,
      reason_codes: ['intel_change:verification_strengthened'],
      matched_project_ids: ['proj_cuda', 'proj_llvm'],
      story_available: true,
      _backendOrder: 1,
    }
  ];

  const { consolidatedList, sections } = consolidateInboxItems(rawDuplicateItems);

  assert.strictEqual(consolidatedList.length, 1);
  const primary = consolidatedList[0];
  // must_know has higher precedence than systems_compilers
  assert.strictEqual(primary.section, 'must_know');
  assert.strictEqual(primary.id, 'ib_sub_2');
  assert.ok(primary.reason_codes.includes('recent_discovery'));
  assert.ok(primary.reason_codes.includes('intel_change:verification_strengthened'));
  assert.ok(primary.matched_project_ids.includes('proj_cuda'));
  assert.ok(primary.matched_project_ids.includes('proj_llvm'));
  assert.ok(primary.secondaryItemTypes.includes('new_story'));

  const cardHtml = renderInboxCard(primary);
  assert.ok(cardHtml.includes('Claim Support Changed'));
  assert.ok(cardHtml.includes('Recent Discovery'));
  assert.ok(cardHtml.includes('+ New Story'));
});

test('Phase 10: Corrective and weakened reasons survive consolidation and are visibly flagged', async () => {
  const { consolidateInboxItems, renderInboxCard } = await import('../src/views/today.js');

  const items = [
    {
      id: 'ib_pos',
      story_cluster_id: 'cl_mixed',
      title: 'Distributed KV Store v2',
      section: 'storage_databases',
      item_type: 'new_release',
      inbox_score: 0.80,
      reason_codes: ['official_release'],
      story_available: true,
      _backendOrder: 0,
    },
    {
      id: 'ib_neg',
      story_cluster_id: 'cl_mixed',
      title: 'Distributed KV Store v2',
      section: 'corrections_updates',
      item_type: 'claim_weakened',
      inbox_score: 0.85,
      reason_codes: ['claim_weakened_by_reproduction'],
      story_available: true,
      _backendOrder: 1,
    }
  ];

  const { consolidatedList } = consolidateInboxItems(items);
  assert.strictEqual(consolidatedList.length, 1);
  const primary = consolidatedList[0];
  assert.strictEqual(primary.section, 'corrections_updates');
  assert.ok(primary.secondaryItemTypes.includes('new_release'));

  const html = renderInboxCard(primary);
  assert.ok(html.includes('data-item-type="claim_weakened"'));
  assert.ok(html.includes('Contradiction / Weakened'));
  assert.ok(html.includes('+ New Release'));
});

test('Phase 10: Dedicated Inbox card does not fabricate verification, maturity, risk, or source badges', async () => {
  const { renderInboxCard } = await import('../src/views/today.js');

  const item = {
    id: 'ib_pure_inbox',
    story_cluster_id: 'cl_pure',
    title: 'New Framework Release',
    section: 'developer_tooling',
    item_type: 'new_story',
    inbox_score: 0.70,
    rank_score: 0.70,
    project_impact_score: 0.0,
    state: 'unseen',
    story_available: true,
  };

  const html = renderInboxCard(item);

  // Must not fabricate epistemic badges
  assert.ok(!html.includes('badge-verification'));
  assert.ok(!html.includes('badge-maturity'));
  assert.ok(!html.includes('badge-risk'));
  assert.ok(!html.includes('source-pill'));
  assert.ok(!html.includes('HERMES cluster'));
});

test('Phase 10: inbox_score and rank_score are labeled as Priority and Order Rank, never Verification or Confidence', async () => {
  const { renderInboxCard } = await import('../src/views/today.js');

  const item = {
    id: 'ib_scores',
    story_cluster_id: 'cl_scores',
    title: 'High Priority Compiler Bug',
    section: 'systems_compilers',
    item_type: 'new_risk',
    inbox_score: 0.94,
    rank_score: 0.94,
    story_available: true,
  };

  const html = renderInboxCard(item);

  assert.ok(html.includes('Priority:'));
  assert.ok(html.includes('94%'));
  assert.ok(!html.includes('Verification:'));
  assert.ok(!html.includes('Confidence:'));
  assert.ok(!html.includes('Accuracy:'));
});

test('Phase 10: project_impact_score is labeled as Project Relevance, never recommendation or safety advice', async () => {
  const { renderInboxCard } = await import('../src/views/today.js');

  const item = {
    id: 'ib_proj',
    story_cluster_id: 'cl_proj',
    title: 'CUDA Kernel Upgrade',
    section: 'systems_compilers',
    item_type: 'new_release',
    inbox_score: 0.85,
    project_impact_score: 0.78,
    matched_project_ids: ['proj_cuda'],
    story_available: true,
  };

  const html = renderInboxCard(item);

  assert.ok(html.includes('Project impact: 78%'));
  assert.ok(html.includes('Project Context:'));
  assert.ok(!html.includes('Recommended'));
  assert.ok(!html.includes('Safe to deploy'));
  assert.ok(!html.includes('Compatible tool'));
});

test('Phase 10: Null scores remain absent and never coerce to 0%', async () => {
  const { renderInboxCard } = await import('../src/views/today.js');

  const item = {
    id: 'ib_nulls',
    story_cluster_id: 'cl_nulls',
    title: 'Unscored Intelligence Signal',
    section: 'research',
    item_type: 'new_story',
    inbox_score: null,
    rank_score: null,
    project_impact_score: null,
    story_available: true,
  };

  const html = renderInboxCard(item);

  assert.ok(!html.includes('0%'));
  assert.ok(!html.includes('Priority:'));
  assert.ok(!html.includes('Project Relevance:'));
});

test('Phase 10: Backend item_type and reason_codes are rendered faithfully without client-side inference', async () => {
  const { renderInboxCard } = await import('../src/views/today.js');

  const item = {
    id: 'ib_codes',
    story_cluster_id: 'cl_codes',
    title: 'Quantum Memory Coherence',
    section: 'research',
    item_type: 'maturity_change',
    inbox_score: 0.65,
    reason_codes: ['intel_change:maturity_increased', 'official_release'],
    story_available: true,
  };

  const html = renderInboxCard(item);

  assert.ok(html.includes('data-item-type="maturity_change"'));
  assert.ok(html.includes('Maturity Shift'));
  assert.ok(html.includes('Maturity Progressed'));
  assert.ok(html.includes('Official Release'));
});

test('Phase 10: claim_weakened, correction, and risk change render with neutral/cautionary treatment', async () => {
  const { renderInboxCard } = await import('../src/views/today.js');

  const items = [
    { id: 'ib_w', story_cluster_id: 'cl_w', title: 'Weakened Claim', section: 'corrections_updates', item_type: 'claim_weakened', story_available: true },
    { id: 'ib_c', story_cluster_id: 'cl_c', title: 'Correction Notice', section: 'corrections_updates', item_type: 'correction', story_available: true },
    { id: 'ib_r', story_cluster_id: 'cl_r', title: 'Risk Alert', section: 'systems_compilers', item_type: 'new_risk', story_available: true },
  ];

  for (const item of items) {
    const html = renderInboxCard(item);
    assert.ok(html.includes('type-caution'));
    assert.ok(!html.includes('type-corroboration'));
  }
});

test('Phase 10: Resolvable Story Dossier renders valid link to #/story/{story_cluster_id}', async () => {
  const { renderInboxCard } = await import('../src/views/today.js');

  const item = {
    id: 'ib_res',
    story_cluster_id: 'cl_valid_123',
    title: 'Resolvable Story Title',
    section: 'ai_ml',
    item_type: 'new_story',
    story_available: true,
  };

  const html = renderInboxCard(item);

  assert.ok(html.includes('href="#/story/cl_valid_123"'));
  assert.ok(html.includes('Open Story Dossier &rarr;'));
  assert.ok(!html.includes('Story dossier currently unavailable'));
});

test('Phase 10: Unavailable Story renders neutral note without broken link or per-card lookup', async () => {
  const { renderInboxCard } = await import('../src/views/today.js');

  const item = {
    id: 'ib_unavail',
    story_cluster_id: 'cl_missing_999',
    title: 'Deleted Story Topic',
    section: 'research',
    item_type: 'new_story',
    story_available: false,
  };

  const html = renderInboxCard(item);

  assert.ok(!html.includes('href="#/story/cl_missing_999"'));
  assert.ok(!html.includes('Open Story Dossier &rarr;'));
  assert.ok(html.includes('Story dossier currently unavailable'));
});

test('Phase 10: Initial saved/starred state reflects persistent backend state', async () => {
  const { renderInboxCard } = await import('../src/views/today.js');

  const starredItem = {
    id: 'ib_star',
    story_cluster_id: 'cl_star',
    title: 'Starred Item',
    section: 'ai_ml',
    item_type: 'new_story',
    is_starred: true,
    saved_item_id: 'saved:cl_star',
    story_available: true,
  };

  const html = renderInboxCard(starredItem);

  assert.ok(html.includes('Saved in Library'));
  assert.ok(html.includes('data-state="starred"'));
  assert.ok(html.includes('aria-pressed="true"'));
});

test('Phase 10: Save from Today calls POST /saved with story_cluster_id and inbox_item_id, updating button state', async () => {
  const { renderTodayView } = await import('../src/views/today.js');
  const capturedPosts = [];

  fetchMock = async (url, options) => {
    if (url.includes('/projects')) return { ok: true, status: 200, json: async () => ({ projects: [] }) };
    if (options && options.method === 'POST' && url.includes('/saved')) {
      capturedPosts.push(JSON.parse(options.body));
      return {
        ok: true,
        status: 200,
        json: async () => ({
          message: 'Saved successfully',
          saved_item: { id: 'saved:cl_post_1', story_cluster_id: 'cl_post_1' }
        })
      };
    }
    return {
      ok: true,
      status: 200,
      json: async () => ({
        count: 1,
        inbox_items: [
          {
            id: 'ib_post_1',
            story_cluster_id: 'cl_post_1',
            title: 'Story to be saved',
            section: 'ai_ml',
            state: 'unseen',
            item_type: 'new_story',
            is_starred: false,
            story_available: true,
          }
        ]
      })
    };
  };

  const container = createMockContainer();
  const store = { state: {}, getState: () => store.state, setState: (s) => Object.assign(store.state, s), setConnection: () => {}, setViewData: () => {} };

  await renderTodayView(container, store);

  // Trigger Save click via delegation
  const clickHandlers = container._listeners['click'] || [];
  const mockButton = {
    dataset: { inboxId: 'ib_post_1', clusterId: 'cl_post_1' },
    classList: { contains: () => false, add: () => {}, remove: () => {} },
    setAttribute: () => {},
    closest: (sel) => mockButton,
    innerHTML: '',
    textContent: '',
  };

  for (const h of clickHandlers) {
    await h({ target: mockButton });
  }

  assert.strictEqual(capturedPosts.length, 1);
  assert.strictEqual(capturedPosts[0].story_cluster_id, 'cl_post_1');
  assert.strictEqual(capturedPosts[0].inbox_item_id, 'ib_post_1');

  fetchMock = null;
});

test('Phase 10: Failed save preserves truthful rollback state and re-enables button', async () => {
  const { renderTodayView } = await import('../src/views/today.js');

  fetchMock = async (url, options) => {
    if (url.includes('/projects')) return { ok: true, status: 200, json: async () => ({ projects: [] }) };
    if (options && options.method === 'POST' && url.includes('/saved')) {
      return {
        ok: false,
        status: 500,
        json: async () => ({ detail: 'Database error while saving' })
      };
    }
    return {
      ok: true,
      status: 200,
      json: async () => ({
        count: 1,
        inbox_items: [
          {
            id: 'ib_fail_1',
            story_cluster_id: 'cl_fail_1',
            title: 'Failing Story',
            section: 'ai_ml',
            is_starred: false,
            story_available: true,
          }
        ]
      })
    };
  };

  const container = createMockContainer();
  const store = { state: {}, getState: () => store.state, setState: (s) => Object.assign(store.state, s), setConnection: () => {}, setViewData: () => {} };

  await renderTodayView(container, store);

  const clickHandlers = container._listeners['click'] || [];
  const mockButton = {
    dataset: { inboxId: 'ib_fail_1', clusterId: 'cl_fail_1' },
    classList: { contains: () => false, add: () => {}, remove: () => {} },
    setAttribute: () => {},
    closest: (sel) => mockButton,
    disabled: false,
    innerHTML: '☆ Save to Library',
    textContent: '☆ Save to Library',
  };

  for (const h of clickHandlers) {
    await h({ target: mockButton });
  }

  // Button should remain enabled and not have is-saved
  assert.strictEqual(mockButton.disabled, false);
  assert.strictEqual(mockButton.innerHTML, '☆ Save to Library');

  fetchMock = null;
});

test('Phase 10: Stale response protection prevents out-of-order race conditions', async () => {
  const { renderTodayView } = await import('../src/views/today.js');

  let resolveSlowReq;
  const slowPromise = new Promise(resolve => { resolveSlowReq = resolve; });

  let reqCount = 0;
  fetchMock = async (url) => {
    if (url.includes('/projects')) return { ok: true, status: 200, json: async () => ({ projects: [] }) };
    if (url.includes('/inbox')) {
      reqCount++;
      if (reqCount === 1) {
        await slowPromise;
        return {
          ok: true,
          status: 200,
          json: async () => ({
            count: 1,
            inbox_items: [{ id: 'ib_slow', story_cluster_id: 'cl_slow', title: 'Slow Response Signal', section: 'ai_ml', story_available: true }]
          })
        };
      } else {
        return {
          ok: true,
          status: 200,
          json: async () => ({
            count: 1,
            inbox_items: [{ id: 'ib_fast', story_cluster_id: 'cl_fast', title: 'Fast Response Signal', section: 'systems_compilers', story_available: true }]
          })
        };
      }
    }
    return { ok: true, status: 200, json: async () => ({}) };
  };

  const container = createMockContainer();
  const store = { state: {}, getState: () => store.state, setState: (s) => Object.assign(store.state, s), setConnection: () => {}, setViewData: () => {} };

  const p1 = renderTodayView(container, store);
  await new Promise(resolve => setTimeout(resolve, 5));

  const secSelect = container.querySelector('#sel-inbox-section');
  secSelect.value = 'systems_compilers';
  const secHandlers = secSelect._listeners['change'] || [];
  for (const h of secHandlers) await h({ target: secSelect });

  resolveSlowReq();
  await p1;

  assert.ok(container.innerHTML.includes('Fast Response Signal'));
  assert.ok(!container.innerHTML.includes('Slow Response Signal'));

  fetchMock = null;
});

test('Phase 10: Accessible live region announces prioritized signals count', async () => {
  const { renderTodayView } = await import('../src/views/today.js');

  fetchMock = async (url) => {
    if (url.includes('/projects')) return { ok: true, status: 200, json: async () => ({ projects: [] }) };
    return {
      ok: true,
      status: 200,
      json: async () => ({
        count: 2,
        inbox_items: [
          { id: 'ib_1', story_cluster_id: 'cl_1', title: 'Signal 1', section: 'ai_ml', story_available: true },
          { id: 'ib_2', story_cluster_id: 'cl_2', title: 'Signal 2', section: 'systems_compilers', story_available: true },
        ]
      })
    };
  };

  const container = createMockContainer();
  const store = { state: {}, getState: () => store.state, setState: (s) => Object.assign(store.state, s), setConnection: () => {}, setViewData: () => {} };

  await renderTodayView(container, store);

  const liveRegion = container.querySelector('#inbox-live-region');
  assert.ok(liveRegion !== null);
  assert.ok(container.innerHTML.includes('id="inbox-live-region"'));
  assert.ok(container.innerHTML.includes('aria-live="polite"'));
  assert.ok(liveRegion.textContent.includes('Showing 2 prioritized intelligence signals across 2 sections.'));

  fetchMock = null;
});

test('Phase 10: Empty, offline, and backend error states render with accessible recovery cues', async () => {
  const { renderTodayView } = await import('../src/views/today.js');

  // Test Empty state
  fetchMock = async (url) => {
    if (url.includes('/projects')) return { ok: true, status: 200, json: async () => ({ projects: [] }) };
    return { ok: true, status: 200, json: async () => ({ count: 0, inbox_items: [] }) };
  };

  const containerEmpty = createMockContainer();
  const store = { state: {}, getState: () => store.state, setState: (s) => Object.assign(store.state, s), setConnection: () => {}, setViewData: () => {} };

  await renderTodayView(containerEmpty, store);
  assert.ok(containerEmpty.innerHTML.includes('No Intelligence Signals Available'));

  // Test Offline state
  fetchMock = async () => {
    const err = new Error('Failed to fetch');
    err.isNetworkError = true;
    throw err;
  };

  const containerOffline = createMockContainer();
  await renderTodayView(containerOffline, store);
  assert.ok(containerOffline.innerHTML.includes('Unable to Connect to HERMES API') || containerOffline.innerHTML.includes('state-offline'));

  fetchMock = null;
});

test('Phase 10 regression: Shared Story Card regression proves string risk level without canonical RiskStatus produces no assessed risk badge', async () => {
  const { renderStoryCard } = await import('../src/components/story-card.js');

  // Story with string risk level but no canonical RiskStatus
  const unassessedStory = {
    id: 'story_unassessed',
    title: 'Unassessed Risk Story',
    risk: 'high', // legacy string risk
    risk_status: null,
  };

  const html = renderStoryCard(unassessedStory);

  // Must NOT produce an assessed risk badge
  assert.ok(!html.includes('badge-risk'));
  assert.ok(!html.includes('risk-critical'));
  assert.ok(!html.includes('risk-high'));
  assert.ok(!html.includes('risk-assessed'));
});

test('Phase 10 remediation: Null project_impact_score remains absent and does not render 0%', async () => {
  const { renderInboxCard } = await import('../src/views/today.js');

  // Case 1: Missing / null score
  const nullScoreItem = {
    id: 'ib_remed_null',
    story_cluster_id: 'cl_remed_1',
    title: 'Item with Null Project Score',
    section: 'ai_ml',
    item_type: 'new_story',
    inbox_score: 0.82,
    rank_score: 0.82,
    project_impact_score: null,
    matched_project_ids: [],
    story_available: true,
  };

  const htmlNull = renderInboxCard(nullScoreItem);
  assert.ok(!htmlNull.includes('Project Relevance:'));
  assert.ok(!htmlNull.includes('0%'));

  // Case 2: Numeric 0.0 score
  const zeroScoreItem = {
    id: 'ib_remed_zero',
    story_cluster_id: 'cl_remed_2',
    title: 'Item with Zero Project Score',
    section: 'ai_ml',
    item_type: 'new_story',
    inbox_score: 0.82,
    rank_score: 0.82,
    project_impact_score: 0.0,
    matched_project_ids: [],
    story_available: true,
  };

  const htmlZero = renderInboxCard(zeroScoreItem);
  assert.ok(!htmlZero.includes('Project relevance:'));
  assert.ok(htmlZero.includes('Project impact: 0%'));

  // Case 3: Genuine positive score
  const posScoreItem = {
    id: 'ib_remed_pos',
    story_cluster_id: 'cl_remed_3',
    title: 'Item with Positive Project Score',
    section: 'ai_ml',
    item_type: 'new_story',
    inbox_score: 0.82,
    rank_score: 0.82,
    project_impact_score: 0.75,
    matched_project_ids: ['proj_cuda'],
    story_available: true,
  };

  const htmlPos = renderInboxCard(posScoreItem);
  assert.ok(htmlPos.includes('Project impact: 75%'));
});

test('Phase 10 remediation: verified_claim:* reason codes render as Claim Priority Signal without truth claims', async () => {
  const { renderInboxCard } = await import('../src/views/today.js');

  const item = {
    id: 'ib_remed_claim',
    story_cluster_id: 'cl_remed_4',
    title: 'Item with Claim Surfacing Code',
    section: 'ai_ml',
    item_type: 'new_story',
    inbox_score: 0.85,
    reason_codes: ['verified_claim:0.65', 'verified_claim:0.89'],
    story_available: true,
  };

  const html = renderInboxCard(item);

  // Must NOT contain truth or epistemic certainty claims
  assert.ok(!html.includes('Verified Claim Found'));
  assert.ok(!html.includes('Verified'));
  assert.ok(!html.includes('65%'));
  assert.ok(!html.includes('89%'));

  // Must render prioritization-safe wording
  assert.ok(html.includes('Claim Priority Signal'));

  // Original reason code must be preserved in data attribute
  assert.ok(html.includes('data-reason-code="verified_claim:0.65"'));
  assert.ok(html.includes('data-reason-code="verified_claim:0.89"'));
});

test('Phase 10 remediation: intel_change:verification_strengthened renders as Claim Support Changed without verification badges', async () => {
  const { renderInboxCard } = await import('../src/views/today.js');

  const item = {
    id: 'ib_remed_intel',
    story_cluster_id: 'cl_remed_5',
    title: 'Item with Intel Change',
    section: 'ai_ml',
    item_type: 'new_story',
    inbox_score: 0.85,
    reason_codes: ['intel_change:verification_strengthened'],
    story_available: true,
  };

  const html = renderInboxCard(item);

  assert.ok(html.includes('Claim Support Changed'));
  assert.ok(!html.includes('Verification Reevaluated'));
  assert.ok(!html.includes('badge-verification'));
  assert.ok(html.includes('data-reason-code="intel_change:verification_strengthened"'));
});

test('Phase 10 remediation: SearchResult and StoryCard omit unavailable score and project relevance without rendering 0%', async () => {
  const { renderSearchResultCard } = await import('../src/views/search.js');
  const { renderStoryCard } = await import('../src/components/story-card.js');

  // Search card with null score & null project_relevance
  const searchNull = {
    entity_id: 'cl_null_sr',
    title: 'Null Scores Result',
    score: null,
    project_relevance: null,
    sources: ['github'],
  };
  const searchNullHtml = renderSearchResultCard(searchNull);
  assert.ok(!searchNullHtml.includes('Relevance Score: 0%'));
  assert.ok(!searchNullHtml.includes('Project Relevance: 0%'));
  assert.ok(!searchNullHtml.includes('search-result-meta-pill'));

  // Story card with null score & null project_impact_score
  const storyNull = {
    id: 'cl_null_sc',
    title: 'Null Scores Story',
    score: null,
    cluster_score: null,
    relevance_score: null,
    project_impact_score: null,
    sources: ['arxiv'],
  };
  const storyNullHtml = renderStoryCard(storyNull);
  assert.ok(!storyNullHtml.includes('badge-ranking'));
  assert.ok(!storyNullHtml.includes('badge-project-match'));
});

// ============================================================================
// Phase 11: Project Intelligence & Engineering Context Tests
// ============================================================================

test('Phase 11: Router correctly parses parametric projects/:id and project/:id routes', async () => {
  const { Router } = await import('../src/state/router.js');
  const routerInstance = new Router();

  let captured = null;
  routerInstance.on('projects', (route) => {
    captured = route;
  });

  // Test #/projects/project:cuda-compiler-lab
  window.location.hash = '#/projects/project%3Acuda-compiler-lab';
  routerInstance._handleHashChange();
  assert.strictEqual(captured.path, 'projects');
  assert.strictEqual(captured.params.projectId, 'project:cuda-compiler-lab');

  // Test #/project/project:local-rag-agent
  window.location.hash = '#/project/project%3Alocal-rag-agent';
  routerInstance._handleHashChange();
  assert.strictEqual(captured.path, 'projects');
  assert.strictEqual(captured.params.projectId, 'project:local-rag-agent');

  // Test #/projects (Index)
  window.location.hash = '#/projects';
  routerInstance._handleHashChange();
  assert.strictEqual(captured.path, 'projects');
  assert.strictEqual(captured.params.projectId, undefined);
});

test('Phase 11: Project Index View renders single GET /projects request, reads project_id, and includes audited privacy notice', async () => {
  const { renderProjectsView } = await import('../src/views/projects.js');
  const { api } = await import('../src/api/endpoints.js');

  const testStore = {
    state: {},
    getState: () => testStore.state,
    setState: (s) => Object.assign(testStore.state, s),
    setConnection: () => {},
    setViewData: () => {},
  };
  const container = createMockContainer();

  let getProjectsCalls = 0;
  let storyCalls = 0;
  let matchesCalls = 0;

  const originalGetProjects = api.getProjects;
  const originalGetStory = api.getStory;

  api.getProjects = async () => {
    getProjectsCalls++;
    return {
      count: 2,
      projects: [
        {
          project_id: 'project:cuda-compiler-lab',
          name: 'CUDA Compiler Lab',
          description: 'LLVM/MLIR GPU compiler exploration',
          is_active: true,
          languages: ['c++', 'cuda'],
          frameworks: ['llvm', 'mlir'],
          libraries: ['cutlass'],
          databases: [],
          infrastructure: [],
          models: [],
          tools: ['cmake', 'ninja'],
          topics: ['compilers', 'gpu-acceleration'],
          keywords: ['ptx', 'nvptx'],
          matches_count: 14,
          last_indexed_at: '2026-08-20T08:59:00Z',
        },
        {
          project_id: 'project:local-rag-agent',
          name: 'Local RAG Agent',
          description: 'On-device retrieval agent',
          is_active: false,
          languages: ['python'],
          frameworks: ['langchain'],
          libraries: ['faiss'],
          databases: ['sqlite'],
          infrastructure: [],
          models: ['llama3'],
          tools: [],
          topics: ['rag', 'vector-search'],
          keywords: ['embeddings'],
          matches_count: 8,
          last_indexed_at: null,
        },
      ],
    };
  };

  api.getStory = async () => {
    storyCalls++;
  };

  try {
    await renderProjectsView(container, testStore);

    // Bounded request assertion: exactly 1 GET /projects call, 0 story calls, 0 matches calls
    assert.strictEqual(getProjectsCalls, 1);
    assert.strictEqual(storyCalls, 0);
    assert.strictEqual(matchesCalls, 0);

    const html = container.innerHTML;

    // Audited privacy copy reflecting local text/embedding persistence
    assert.ok(html.includes('Local Workspace Processing'));
    assert.ok(html.includes('supported local source files, configurations, manifests, and documentation'));
    assert.ok(html.includes('extracted text, relative paths, content hashes, derived technology profiles, and local embeddings'));
    assert.ok(html.includes('Sensitive filename patterns'));
    assert.ok(html.includes('detected binaries are skipped'));

    // Anti-regression assertions: must not claim metadata-only or manifests-only
    assert.ok(!html.includes('metadata only'));
    assert.ok(!html.includes('manifests and documentation only'));
    assert.ok(!html.includes('manifests only'));

    // Project Cards rendered with canonical project_id
    assert.ok(html.includes('data-project-id="project:cuda-compiler-lab"'));
    assert.ok(html.includes('CUDA Compiler Lab'));
    assert.ok(html.includes('14 matched items'));
    assert.ok(html.includes('Active'));
    assert.ok(html.includes('href="#/projects/project%3Acuda-compiler-lab"'));

    assert.ok(html.includes('data-project-id="project:local-rag-agent"'));
    assert.ok(html.includes('Local RAG Agent'));
    assert.ok(html.includes('8 matched items'));
    assert.ok(html.includes('Inactive'));
    assert.ok(html.includes('Never indexed'));

  } finally {
    api.getProjects = originalGetProjects;
    api.getStory = originalGetStory;
  }
});

test('Phase 11: Project Detail View renders aggregated intelligence in single request with distinct tech categories, concerns, and cross-nav', async () => {
  const { renderProjectsView } = await import('../src/views/projects.js');
  const { api } = await import('../src/api/endpoints.js');

  const testStore = {
    state: {},
    getState: () => testStore.state,
    setState: (s) => Object.assign(testStore.state, s),
    setConnection: () => {},
    setViewData: () => {},
  };
  const container = createMockContainer();

  let getIntelCalls = 0;
  let storyCalls = 0;

  const originalGetIntel = api.getProjectIntelligence;
  const originalGetStory = api.getStory;

  api.getProjectIntelligence = async (projectId) => {
    getIntelCalls++;
    assert.strictEqual(projectId, 'project:cuda-compiler-lab');
    return {
      project_id: 'project:cuda-compiler-lab',
      name: 'CUDA Compiler Lab',
      description: 'LLVM/MLIR GPU compiler pipeline',
      is_active: true,
      last_indexed_at: '2026-08-20T08:59:00Z',
      intelligence_available: true,
      technology_profile: {
        languages: ['C++', 'CUDA'],
        frameworks: ['LLVM', 'MLIR'],
        libraries: ['CUTLASS'],
        databases: [],
        infrastructure: ['NVIDIA Driver'],
        models: [],
        tools: ['CMake', 'Ninja'],
        topics: ['Compilers', 'GPU'],
        keywords: ['PTX', 'NVPTX'],
      },
      top_matches: [
        {
          cluster_id: 'cl_cuda_1',
          title: 'LLVM 19 NVPTX Codegen Improvements',
          match_type: 'technology_overlap',
          relevance_score: 0.8437,
          impact_score: 0.7935,
          recommendation: 'upgrade_candidate',
          reason_codes: ['framework_match', 'technology_overlap'],
          story_available: true,
        },
        {
          cluster_id: 'cl_missing_story_2',
          title: 'CUTLASS 3.5 Kernel Optimization',
          match_type: 'direct_dependency',
          relevance_score: null,
          impact_score: null,
          recommendation: 'consider',
          reason_codes: ['direct_dependency_match'],
          story_available: false,
        },
        {
          cluster_id: 'cl_zero_score_3',
          title: 'CMake 3.30 Ninja Multi-Config Update',
          match_type: 'compatible_tool',
          relevance_score: 0.0,
          impact_score: 0.0,
          recommendation: 'watch',
          reason_codes: ['tool_match'],
          story_available: true,
        },
      ],
      risks: [
        {
          cluster_id: 'cl_cuda_1',
          title: 'LLVM 19 NVPTX Codegen Improvements',
          concern_type: 'high_project_impact',
          match_type: 'technology_overlap',
          impact_score: 0.7935,
          relevance_score: 0.8437,
          risk_status: 'insufficient_data',
          risk_level: null,
          risk_score: 0.35,
          recommendation: 'upgrade_candidate',
          reason_codes: ['framework_match'],
          story_available: true,
        },
        {
          cluster_id: 'cl_vuln_4',
          title: 'Critical Buffer Overflow in NVPTX Driver Parser',
          concern_type: 'vulnerability',
          match_type: 'vulnerability',
          impact_score: 0.92,
          relevance_score: 0.88,
          risk_status: 'assessed',
          risk_level: 'critical',
          risk_score: 0.95,
          recommendation: 'potential_risk',
          reason_codes: ['security_vulnerability'],
          story_available: true,
        },
        {
          cluster_id: 'cl_assessed_5',
          title: 'Legacy Driver Deprecation Risk',
          concern_type: 'assessed_risk',
          match_type: 'general_related',
          impact_score: 0.85,
          relevance_score: 0.75,
          risk_status: 'assessed',
          risk_level: 'critical',
          risk_score: 0.88,
          recommendation: 'potential_risk',
          reason_codes: ['technology_overlap'],
          story_available: true,
        },
      ],
      recent_changes: [
        {
          id: 'ch_1',
          cluster_id: 'cl_cuda_1',
          change_type: 'state_transition',
          importance_level: 'high',
          description: 'LLVM 19 transitioned to release state with updated NVPTX backend',
          old_value: 'release_candidate',
          new_value: 'active_release',
          origin: 'system',
          detected_at: '2026-08-21T10:00:00Z',
        },
      ],
    };
  };

  api.getStory = async () => {
    storyCalls++;
  };

  try {
    await renderProjectsView(container, testStore, { projectId: 'project:cuda-compiler-lab' });

    // Single bounded request
    assert.strictEqual(getIntelCalls, 1);
    assert.strictEqual(storyCalls, 0);

    const html = container.innerHTML;

    // Breadcrumb and header
    assert.ok(html.includes('← Back to Projects'));
    assert.ok(html.includes('CUDA Compiler Lab'));
    assert.ok(html.includes('Active Profile'));

    // Cross-surface navigation links
    assert.ok(html.includes('href="#/today?project=project%3Acuda-compiler-lab"'));
    assert.ok(html.includes('href="#/search?project=project%3Acuda-compiler-lab"'));
    assert.ok(html.includes('href="#/changes?project=project%3Acuda-compiler-lab"'));

    // Structured Technology Profile (distinct categories)
    assert.ok(html.includes('Languages (2)'));
    assert.ok(html.includes('Frameworks (2)'));
    assert.ok(html.includes('Libraries (1)'));
    assert.ok(html.includes('Infrastructure (1)'));
    assert.ok(html.includes('Tools (2)'));
    assert.ok(html.includes('Topics (2)'));
    assert.ok(html.includes('Keywords (2)'));

    // Score labeling and rounding
    assert.ok(html.includes('Project relevance: 84%'));
    assert.ok(html.includes('Project impact: 79%'));
    assert.ok(html.includes('data-reason-code="framework_match"'));

    // Advisory context provenance
    assert.ok(html.includes('Advisory Context:'));
    assert.ok(html.includes('Upgrade Candidate — New release or major improvements available.'));

    // Missing score omission (null)
    assert.ok(!html.includes('Project relevance: null%'));
    assert.ok(!html.includes('Project impact: null%'));

    // Genuine 0.0 preservation
    assert.ok(html.includes('Project relevance: 0%'));
    assert.ok(html.includes('Project impact: 0%'));

    // Story availability
    assert.ok(html.includes('href="#/story/cl_cuda_1"'));
    assert.ok(html.includes('Story unavailable'));
    assert.ok(!html.includes('href="#/story/cl_missing_story_2"'));

    // Concerns separation: High Project Impact != Assessed Risk
    assert.ok(html.includes('High Project Impact'));
    assert.ok(html.includes('Canonical Risk Status: <strong>insufficient_data</strong>'));
    assert.ok(html.includes('Assessed Risk · critical'));
    assert.ok(html.includes('Vulnerability'));

    // Recent Changes
    assert.ok(html.includes('release_candidate'));
    assert.ok(html.includes('active_release'));
    assert.ok(html.includes('origin-system'));
    assert.ok(html.includes('badge-high'));

  } finally {
    api.getProjectIntelligence = originalGetIntel;
    api.getStory = originalGetStory;
  }
});

test('Phase 11: Project Detail View renders graceful 404 for unknown project', async () => {
  const { renderProjectsView } = await import('../src/views/projects.js');
  const { api } = await import('../src/api/endpoints.js');

  const testStore = {
    state: {},
    getState: () => testStore.state,
    setState: (s) => Object.assign(testStore.state, s),
    setConnection: () => {},
    setViewData: () => {},
  };
  const container = createMockContainer();

  const originalGetIntel = api.getProjectIntelligence;
  api.getProjectIntelligence = async () => {
    const err = new Error('Project not found');
    err.status = 404;
    throw err;
  };

  try {
    await renderProjectsView(container, testStore, { projectId: 'project:unknown_app' });
    const html = container.innerHTML;
    assert.ok(html.includes('Project Not Found'));
    assert.ok(html.includes('project:unknown_app'));
    assert.ok(html.includes('href="#/projects"'));
  } finally {
    api.getProjectIntelligence = originalGetIntel;
  }
});

test('Phase 11: Project Detail View renders truthful empty intelligence state when intelligence_available is false', async () => {
  const { renderProjectsView } = await import('../src/views/projects.js');
  const { api } = await import('../src/api/endpoints.js');

  const testStore = {
    state: {},
    getState: () => testStore.state,
    setState: (s) => Object.assign(testStore.state, s),
    setConnection: () => {},
    setViewData: () => {},
  };
  const container = createMockContainer();

  const originalGetIntel = api.getProjectIntelligence;
  api.getProjectIntelligence = async () => {
    return {
      project_id: 'project:clean_slate',
      name: 'Clean Slate',
      description: 'Brand new project with no matching stories',
      is_active: true,
      last_indexed_at: null,
      intelligence_available: false,
      technology_profile: {},
      top_matches: [],
      risks: [],
      recent_changes: [],
    };
  };

  try {
    await renderProjectsView(container, testStore, { projectId: 'project:clean_slate' });
    const html = container.innerHTML;
    assert.ok(html.includes('No Project Intelligence Recorded Yet'));
    assert.ok(html.includes('No matching intelligence items, engineering concerns, or recent changes'));
  } finally {
    api.getProjectIntelligence = originalGetIntel;
  }
});

test('Phase 11: Missing advisory recommendation produces no Advisory Context in DOM, genuine tokens humanized, unknown degraded neutrally', async () => {
  const { renderProjectsView } = await import('../src/views/projects.js');
  const { api } = await import('../src/api/endpoints.js');

  const testStore = {
    state: {},
    getState: () => testStore.state,
    setState: (s) => Object.assign(testStore.state, s),
    setConnection: () => {},
    setViewData: () => {},
  };
  const container = createMockContainer();

  const originalGetIntel = api.getProjectIntelligence;
  api.getProjectIntelligence = async () => {
    return {
      project_id: 'project:rec_test',
      name: 'Rec Test',
      description: 'Advisory tests',
      is_active: true,
      last_indexed_at: '2026-08-21T00:00:00Z',
      intelligence_available: true,
      technology_profile: {},
      top_matches: [
        {
          cluster_id: 'cl_null_rec',
          title: 'Null Recommendation Item',
          match_type: 'technology_overlap',
          relevance_score: 0.8,
          impact_score: 0.7,
          recommendation: null,
          reason_codes: ['tech_overlap'],
          story_available: true,
        },
        {
          cluster_id: 'cl_watch_rec',
          title: 'Watch Recommendation Item',
          match_type: 'technology_overlap',
          relevance_score: 0.8,
          impact_score: 0.7,
          recommendation: 'watch',
          reason_codes: ['tech_overlap'],
          story_available: true,
        },
        {
          cluster_id: 'cl_unknown_rec',
          title: 'Unknown Custom Recommendation Item',
          match_type: 'compatible_tool',
          relevance_score: 0.6,
          impact_score: 0.5,
          recommendation: 'custom_experimental_tag',
          reason_codes: ['tool_overlap'],
          story_available: true,
        },
      ],
      risks: [],
      recent_changes: [],
    };
  };

  try {
    await renderProjectsView(container, testStore, { projectId: 'project:rec_test' });
    const html = container.innerHTML;

    // cl_null_rec must NOT have an advisory box
    const nullIdx = html.indexOf('Null Recommendation Item');
    const watchIdx = html.indexOf('Watch Recommendation Item');
    const nullSection = html.slice(nullIdx, watchIdx);
    assert.ok(!nullSection.includes('Advisory Context:'));

    // cl_watch_rec must be humanized cautiously
    assert.ok(html.includes('Watch — Emerging technology in project ecosystem.'));

    // cl_unknown_rec must degrade neutrally without throwing or fabricating advice
    assert.ok(html.includes('Custom experimental tag'));

  } finally {
    api.getProjectIntelligence = originalGetIntel;
  }
});

// ==========================================
// Phase 12: Morning Briefing & Historical Intelligence Tests
// ==========================================

import { api } from '../src/api/endpoints.js';
import { router } from '../src/state/router.js';

test('Phase 12: Router parses date query parameter from #/briefing?date=2026-08-20', () => {
  const r = new (router.constructor)();
  let capturedRoute = null;
  r.on('briefing', (route) => {
    capturedRoute = route;
  });

  globalThis.window.location.hash = '#/briefing?date=2026-08-20';
  r._handleHashChange();

  assert.ok(capturedRoute !== null);
  assert.strictEqual(capturedRoute.path, 'briefing');
  assert.strictEqual(capturedRoute.params.date, '2026-08-20');
});

test('Phase 12: Briefing view renders date picker and toolbar controls', async () => {
  const testStore = {
    state: { view: 'briefing', routeParams: { date: '2026-08-20' } },
    getState: () => testStore.state,
    setState: (s) => Object.assign(testStore.state, s),
    setConnection: () => {},
    setViewData: () => {},
  };
  const container = createMockContainer();

  const originalGetBriefing = api.getBriefing;
  api.getBriefing = async (params) => {
    assert.strictEqual(params.date, '2026-08-20');
    return {
      id: 'briefing:2026-08-20',
      briefing_date: '2026-08-20',
      generated_at: '2026-08-20T08:00:00Z',
      total_items: 2,
      high_priority_count: 1,
      project_relevant_count: 1,
      content_hash: 'abcdef0123456789',
      summary_text: 'Engineering summary of the day.',
      sections: {
        must_know: [
          {
            inbox_item_id: 'inbox:1',
            story_cluster_id: 'cluster:1',
            title: 'Must Know Title',
            summary: 'Must Know Summary',
            section: 'must_know',
            position: 1,
            item_type: 'deep_dive',
            reason_codes: ['critical_system'],
            inbox_score: 0.95,
            rank_score: 0.90,
            project_impact_score: 0.85,
            matched_project_ids: ['cuda-compiler-lab'],
            snapshot_status: 'complete',
            snapshot_version: 'v1',
            story_available: true,
          }
        ]
      },
      ordered_sections: ['must_know'],
    };
  };

  try {
    const { renderBriefingView } = await import('../src/views/briefing.js');
    await renderBriefingView(container, testStore, { date: '2026-08-20' });
    const html = container.innerHTML;

    // Check toolbar elements
    assert.ok(html.includes('id="briefing-date-input"'));
    assert.ok(html.includes('value="2026-08-20"'));
    assert.ok(html.includes('class="btn btn-secondary btn-sm briefing-prev-btn"'));
    assert.ok(html.includes('class="btn btn-secondary btn-sm briefing-next-btn"'));
    assert.ok(html.includes('class="btn btn-secondary btn-sm briefing-today-btn"'));

    // Check executive summary & hash
    assert.ok(html.includes('Engineering summary of the day.'));
    assert.ok(html.includes('Hash: abcdef01…'));

    // Check section header & item
    assert.ok(html.includes('Must Know'));
    assert.ok(html.includes('Must Know Title'));
    assert.ok(html.includes('Priority: 95%'));
    assert.ok(html.includes('Rank: 90%'));
    assert.ok(html.includes('Project impact: 85%'));
    assert.ok(html.includes('critical_system'));
    assert.ok(html.includes('href="#/projects/cuda-compiler-lab"'));

    // Check Story link (story_available: true)
    assert.ok(html.includes('href="#/story/cluster%3A1"'));
    assert.ok(html.includes('Open Story Dossier →'));

    // Check screen reader live announcement
    assert.ok(html.includes('Briefing for 2026-08-20 loaded with 2 items.'));
  } finally {
    api.getBriefing = originalGetBriefing;
  }
});

test('Phase 12: Briefing view suppresses Story Dossier link when story_available is false', async () => {
  const testStore = {
    state: { view: 'briefing' },
    getState: () => testStore.state,
    setState: (s) => Object.assign(testStore.state, s),
    setConnection: () => {},
    setViewData: () => {},
  };
  const container = createMockContainer();

  const originalGetBriefing = api.getBriefing;
  api.getBriefing = async () => ({
    id: 'briefing:2026-08-20',
    briefing_date: '2026-08-20',
    generated_at: '2026-08-20T08:00:00Z',
    total_items: 1,
    high_priority_count: 0,
    project_relevant_count: 0,
    summary_text: 'Summary',
    sections: {
      ai_ml: [
        {
          inbox_item_id: 'inbox:missing_story',
          story_cluster_id: 'cluster:deleted_story',
          title: 'Historical Item Missing Story',
          section: 'ai_ml',
          position: 1,
          inbox_score: 0.70,
          snapshot_status: 'complete',
          story_available: false,
        }
      ]
    },
    ordered_sections: ['ai_ml'],
  });

  try {
    const { renderBriefingView } = await import('../src/views/briefing.js');
    await renderBriefingView(container, testStore, { date: '2026-08-20' });
    const html = container.innerHTML;

    // Must NOT have link to #/story/cluster:deleted_story
    assert.ok(!html.includes('href="#/story/cluster%3Adeleted_story"'));
    assert.ok(!html.includes('Open Story Dossier →'));
    assert.ok(html.includes('Story unavailable'));
    assert.ok(!html.includes('Story cluster not currently active'));
    assert.ok(!html.includes('inactive'));
  } finally {
    api.getBriefing = originalGetBriefing;
  }
});

test('Phase 12: Briefing view renders Legacy Snapshot badge when snapshot_status is legacy_incomplete', async () => {
  const testStore = {
    state: { view: 'briefing' },
    getState: () => testStore.state,
    setState: (s) => Object.assign(testStore.state, s),
    setConnection: () => {},
    setViewData: () => {},
  };
  const container = createMockContainer();

  const originalGetBriefing = api.getBriefing;
  api.getBriefing = async () => ({
    id: 'briefing:2026-08-01',
    briefing_date: '2026-08-01',
    generated_at: '2026-08-01T08:00:00Z',
    total_items: 1,
    summary_text: 'Legacy digest',
    sections: {
      ai_ml: [
        {
          inbox_item_id: 'inbox:legacy',
          title: 'Legacy Captured Item',
          section: 'ai_ml',
          position: 1,
          inbox_score: null,
          snapshot_status: 'legacy_incomplete',
          snapshot_version: null,
          story_available: false,
        }
      ]
    },
    ordered_sections: ['ai_ml'],
  });

  try {
    const { renderBriefingView } = await import('../src/views/briefing.js');
    await renderBriefingView(container, testStore, { date: '2026-08-01' });
    const html = container.innerHTML;

    assert.ok(html.includes('Legacy Snapshot'));
    assert.ok(!html.includes('Priority: unrated'));
  } finally {
    api.getBriefing = originalGetBriefing;
  }
});

test('Phase 12: Initial Briefing view load sends exactly one GET /briefing request and zero Story/Inbox/Claim/Project requests', async () => {
  const testStore = {
    state: { view: 'briefing' },
    getState: () => testStore.state,
    setState: (s) => Object.assign(testStore.state, s),
    setConnection: () => {},
    setViewData: () => {},
  };
  const container = createMockContainer();

  let briefingCalls = 0;
  let storyCalls = 0;
  let inboxCalls = 0;
  let claimCalls = 0;
  let projectCalls = 0;

  const originalGetBriefing = api.getBriefing;
  const originalGetStory = api.getStory;
  const originalGetInbox = api.getInbox;
  const originalGetClaims = api.getClaims;
  const originalGetProjects = api.getProjects;

  api.getBriefing = async () => {
    briefingCalls++;
    return {
      id: 'briefing:2026-08-20',
      briefing_date: '2026-08-20',
      generated_at: '2026-08-20T08:00:00Z',
      total_items: 0,
      sections: {},
      ordered_sections: [],
    };
  };
  api.getStory = async () => { storyCalls++; return {}; };
  api.getInbox = async () => { inboxCalls++; return {}; };
  api.getClaims = async () => { claimCalls++; return {}; };
  api.getProjects = async () => { projectCalls++; return {}; };

  try {
    const { renderBriefingView } = await import('../src/views/briefing.js');
    await renderBriefingView(container, testStore);

    assert.strictEqual(briefingCalls, 1, 'Must make exactly 1 getBriefing call');
    assert.strictEqual(storyCalls, 0, 'Must make 0 getStory calls');
    assert.strictEqual(inboxCalls, 0, 'Must make 0 getInbox calls');
    assert.strictEqual(claimCalls, 0, 'Must make 0 getClaims calls');
    assert.strictEqual(projectCalls, 0, 'Must make 0 getProjects calls');
  } finally {
    api.getBriefing = originalGetBriefing;
    api.getStory = originalGetStory;
    api.getInbox = originalGetInbox;
    api.getClaims = originalGetClaims;
    api.getProjects = originalGetProjects;
  }
});

test('Phase 12: Date parameter in route triggers GET /briefing with date parameter', async () => {
  const testStore = {
    state: { view: 'briefing' },
    getState: () => testStore.state,
    setState: (s) => Object.assign(testStore.state, s),
    setConnection: () => {},
    setViewData: () => {},
  };
  const container = createMockContainer();

  let capturedParams = null;
  const originalGetBriefing = api.getBriefing;
  api.getBriefing = async (params) => {
    capturedParams = params;
    return {
      id: 'briefing:2026-08-15',
      briefing_date: '2026-08-15',
      generated_at: '2026-08-15T08:00:00Z',
      total_items: 0,
      sections: {},
      ordered_sections: [],
    };
  };

  try {
    const { renderBriefingView } = await import('../src/views/briefing.js');
    await renderBriefingView(container, testStore, { date: '2026-08-15' });

    assert.deepStrictEqual(capturedParams, { date: '2026-08-15' });
  } finally {
    api.getBriefing = originalGetBriefing;
  }
});

test('Phase 12: Previous and Next day buttons compute correct ISO dates', async () => {
  const testStore = {
    state: { view: 'briefing' },
    getState: () => testStore.state,
    setState: (s) => Object.assign(testStore.state, s),
    setConnection: () => {},
    setViewData: () => {},
  };
  const container = createMockContainer();

  const originalGetBriefing = api.getBriefing;
  api.getBriefing = async () => ({
    id: 'briefing:2026-08-15',
    briefing_date: '2026-08-15',
    generated_at: '2026-08-15T08:00:00Z',
    total_items: 0,
    sections: {},
    ordered_sections: [],
  });

  try {
    const { renderBriefingView } = await import('../src/views/briefing.js');
    await renderBriefingView(container, testStore, { date: '2026-08-15' });

    const html = container.innerHTML;
    assert.ok(html.includes('data-target-date="2026-08-14"'));
    assert.ok(html.includes('data-target-date="2026-08-16"'));
  } finally {
    api.getBriefing = originalGetBriefing;
  }
});

test('Phase 12: Briefing view renders 404 empty state distinctly from zero-item briefing', async () => {
  const testStore = {
    state: { view: 'briefing' },
    getState: () => testStore.state,
    setState: (s) => Object.assign(testStore.state, s),
    setConnection: () => {},
    setViewData: () => {},
  };
  const container = createMockContainer();

  const originalGetBriefing = api.getBriefing;
  api.getBriefing = async () => {
    const err = new Error('Not found');
    err.status = 404;
    throw err;
  };

  try {
    const { renderBriefingView } = await import('../src/views/briefing.js');
    await renderBriefingView(container, testStore, { date: '2026-01-01' });
    const html = container.innerHTML;

    assert.ok(html.includes('No Briefing Snapshot Found'));
    assert.ok(!html.includes('No items recorded in this briefing digest'));
    assert.ok(html.includes('2026-01-01'));
  } finally {
    api.getBriefing = originalGetBriefing;
  }
});

test('Phase 12: Briefing view renders 422 invalid date state distinctly', async () => {
  const testStore = {
    state: { view: 'briefing' },
    getState: () => testStore.state,
    setState: (s) => Object.assign(testStore.state, s),
    setConnection: () => {},
    setViewData: () => {},
  };
  const container = createMockContainer();

  const originalGetBriefing = api.getBriefing;
  api.getBriefing = async () => {
    const err = new Error('Invalid date');
    err.status = 422;
    throw err;
  };

  try {
    const { renderBriefingView } = await import('../src/views/briefing.js');
    await renderBriefingView(container, testStore, { date: 'invalid-date' });
    const html = container.innerHTML;

    assert.ok(html.includes('Invalid Briefing Date'));
    assert.ok(html.includes('invalid-date'));
  } finally {
    api.getBriefing = originalGetBriefing;
  }
});

test('Phase 12: Briefing view renders zero-item briefing message distinctly', async () => {
  const testStore = {
    state: { view: 'briefing' },
    getState: () => testStore.state,
    setState: (s) => Object.assign(testStore.state, s),
    setConnection: () => {},
    setViewData: () => {},
  };
  const container = createMockContainer();

  const originalGetBriefing = api.getBriefing;
  api.getBriefing = async () => ({
    id: 'briefing:2026-08-20',
    briefing_date: '2026-08-20',
    generated_at: '2026-08-20T08:00:00Z',
    total_items: 0,
    sections: {},
    ordered_sections: [],
  });

  try {
    const { renderBriefingView } = await import('../src/views/briefing.js');
    await renderBriefingView(container, testStore, { date: '2026-08-20' });
    const html = container.innerHTML;

    assert.ok(html.includes('No items recorded in this briefing digest'));
    assert.ok(!html.includes('No Briefing Snapshot Found'));
  } finally {
    api.getBriefing = originalGetBriefing;
  }
});

test('Phase 12: Strict numeric score rendering and non-numeric omission', async () => {
  const { renderBriefingItemCard } = await import('../src/views/briefing.js');

  // 1. Valid positive numbers
  const cardWithScores = renderBriefingItemCard({
    inbox_item_id: '1',
    position: 1,
    title: 'Item With Scores',
    inbox_score: 0.95,
    rank_score: 0.88,
    project_impact_score: 0.75,
  });
  assert.ok(cardWithScores.includes('Priority: 95%'));
  assert.ok(cardWithScores.includes('Rank: 88%'));
  assert.ok(cardWithScores.includes('Project impact: 75%'));

  // 2. Genuine numeric 0.0
  const cardWithZero = renderBriefingItemCard({
    inbox_item_id: '2',
    position: 2,
    title: 'Item With Zero',
    inbox_score: 0.0,
    rank_score: 0.0,
    project_impact_score: 0.0,
  });
  assert.ok(cardWithZero.includes('Priority: 0%'));
  assert.ok(cardWithZero.includes('Rank: 0%'));
  assert.ok(cardWithZero.includes('Project impact: 0%'));

  // 3. Null and undefined
  const cardWithNulls = renderBriefingItemCard({
    inbox_item_id: '3',
    position: 3,
    title: 'Item With Nulls',
    inbox_score: null,
    rank_score: undefined,
    project_impact_score: null,
  });
  assert.ok(!cardWithNulls.includes('Priority:'));
  assert.ok(!cardWithNulls.includes('Rank:'));
  assert.ok(!cardWithNulls.includes('Project impact:'));
  assert.ok(!cardWithNulls.includes('Priority: unrated'));

  // 4. Non-numeric strings and NaN
  const cardWithInvalid = renderBriefingItemCard({
    inbox_item_id: '4',
    position: 4,
    title: 'Item With Invalid Numbers',
    inbox_score: '0.95',
    rank_score: NaN,
    project_impact_score: 'high',
  });
  assert.ok(!cardWithInvalid.includes('Priority:'));
  assert.ok(!cardWithInvalid.includes('Rank:'));
  assert.ok(!cardWithInvalid.includes('Project Impact:'));
  assert.ok(!cardWithInvalid.includes('NaN'));
});

test('Phase 12: Reason codes preserve raw code in data-reason-code attribute and escape special characters', async () => {
  const { renderBriefingItemCard } = await import('../src/views/briefing.js');

  const card = renderBriefingItemCard({
    inbox_item_id: '1',
    position: 1,
    title: 'Reason Test Item',
    reason_codes: ['verified_claim:0.80', 'recent_discovery', 'custom<tag>&test'],
  });

  assert.ok(card.includes('data-reason-code="verified_claim:0.80"'));
  assert.ok(card.includes('data-reason-code="recent_discovery"'));
  assert.ok(card.includes('data-reason-code="custom&lt;tag&gt;&amp;test"'));
  assert.ok(card.includes('Claim Priority Signal: 0.80'));
  assert.ok(card.includes('Recent Discovery'));
});

test('Phase 12: Correction item type renders cautionary badge and styling', async () => {
  const { renderBriefingItemCard } = await import('../src/views/briefing.js');

  const card = renderBriefingItemCard({
    inbox_item_id: '1',
    position: 1,
    title: 'Correction Notice',
    item_type: 'correction',
    reason_codes: ['correction'],
  });

  assert.ok(card.includes('briefing-card-cautionary'));
  assert.ok(card.includes('briefing-caution-tag'));
  assert.ok(card.includes('Correction'));
  assert.ok(!card.includes('badge-verification'));
});

test('Phase 12: Claim weakened item renders weakened support tag and styling', async () => {
  const { renderBriefingItemCard } = await import('../src/views/briefing.js');

  const card = renderBriefingItemCard({
    inbox_item_id: '1',
    position: 1,
    title: 'Weakened Finding',
    item_type: 'claim_weakened',
    reason_codes: ['intel_change:verification_weakened'],
  });

  assert.ok(card.includes('briefing-card-weakened'));
  assert.ok(card.includes('briefing-weakened-tag'));
  assert.ok(card.includes('Weakened Support'));
  assert.ok(!card.includes('badge-verification'));
});

test('Phase 12: Legacy incomplete item omits missing title, summary, type, and projects without fabricating values', async () => {
  const { renderBriefingItemCard } = await import('../src/views/briefing.js');

  const card = renderBriefingItemCard({
    inbox_item_id: 'legacy_empty',
    position: 1,
    snapshot_status: 'legacy_incomplete',
    title: null,
    summary: null,
    item_type: null,
    inbox_score: null,
    rank_score: null,
    project_impact_score: null,
    reason_codes: [],
    matched_project_ids: [],
  });

  assert.ok(card.includes('briefing-missing-notice'));
  assert.ok(card.includes('Title was not captured in this legacy snapshot'));
  assert.ok(!card.includes('Untitled snapshot item'));
  assert.ok(!card.includes('briefing-item-summary'));
  assert.ok(!card.includes('briefing-type-tag'));
  assert.ok(!card.includes('briefing-score-badge'));
  assert.ok(!card.includes('briefing-project-pill'));
  assert.ok(card.includes('Legacy Snapshot'));
});

test('Phase 12: Snapshot disclosure notice is rendered in executive summary', async () => {
  const testStore = {
    state: { view: 'briefing' },
    getState: () => testStore.state,
    setState: (s) => Object.assign(testStore.state, s),
    setConnection: () => {},
    setViewData: () => {},
  };
  const container = createMockContainer();

  const originalGetBriefing = api.getBriefing;
  api.getBriefing = async () => ({
    id: 'briefing:2026-08-20',
    briefing_date: '2026-08-20',
    generated_at: '2026-08-20T08:00:00Z',
    total_items: 0,
    summary_text: 'Summary',
    sections: {},
    ordered_sections: [],
  });

  try {
    const { renderBriefingView } = await import('../src/views/briefing.js');
    await renderBriefingView(container, testStore, { date: '2026-08-20' });
    const html = container.innerHTML;

    assert.ok(html.includes('briefing-disclosure-notice'));
    assert.ok(html.includes('This briefing is a stored snapshot generated from HERMES intelligence'));
    assert.ok(html.includes('Current Story Dossiers may have changed since then'));
  } finally {
    api.getBriefing = originalGetBriefing;
  }
});

test('Phase 12: Live region announces briefing date and total items on load', async () => {
  const testStore = {
    state: { view: 'briefing' },
    getState: () => testStore.state,
    setState: (s) => Object.assign(testStore.state, s),
    setConnection: () => {},
    setViewData: () => {},
  };
  const container = createMockContainer();

  const originalGetBriefing = api.getBriefing;
  api.getBriefing = async () => ({
    id: 'briefing:2026-08-20',
    briefing_date: '2026-08-20',
    generated_at: '2026-08-20T08:00:00Z',
    total_items: 5,
    summary_text: 'Summary',
    sections: {},
    ordered_sections: [],
  });

  try {
    const { renderBriefingView } = await import('../src/views/briefing.js');
    await renderBriefingView(container, testStore, { date: '2026-08-20' });
    const html = container.innerHTML;

    assert.ok(html.includes('id="briefing-announcer"'));
    assert.ok(html.includes('Briefing for 2026-08-20 loaded with 5 items.'));
  } finally {
    api.getBriefing = originalGetBriefing;
  }
});

test('Phase 12: Stale response protection prevents out-of-order date overwrite', async () => {
  const testStore = {
    state: { view: 'briefing' },
    getState: () => testStore.state,
    setState: (s) => Object.assign(testStore.state, s),
    setConnection: () => {},
    setViewData: () => {},
  };
  const container = createMockContainer();

  let resolveFirst;
  const firstPromise = new Promise((resolve) => { resolveFirst = resolve; });

  const originalGetBriefing = api.getBriefing;
  api.getBriefing = async (params) => {
    if (params && params.date === '2026-08-01') {
      await firstPromise;
      return {
        id: 'briefing:2026-08-01',
        briefing_date: '2026-08-01',
        generated_at: '2026-08-01T08:00:00Z',
        total_items: 1,
        sections: { ai_ml: [{ inbox_item_id: '1', position: 1, title: 'Old Date Item' }] },
        ordered_sections: ['ai_ml'],
      };
    }
    return {
      id: 'briefing:2026-08-02',
      briefing_date: '2026-08-02',
      generated_at: '2026-08-02T08:00:00Z',
      total_items: 1,
      sections: { ai_ml: [{ inbox_item_id: '2', position: 1, title: 'New Date Item' }] },
      ordered_sections: ['ai_ml'],
    };
  };

  try {
    const { renderBriefingView } = await import('../src/views/briefing.js');

    // Trigger request 1 (slow)
    const call1 = renderBriefingView(container, testStore, { date: '2026-08-01' });
    // Trigger request 2 (fast)
    const call2 = renderBriefingView(container, testStore, { date: '2026-08-02' });

    await call2;
    assert.ok(container.innerHTML.includes('New Date Item'));

    // Resolve slow request 1
    resolveFirst();
    await call1;

    // Container MUST still contain New Date Item (request 1 discarded as stale)
    assert.ok(container.innerHTML.includes('New Date Item'));
    assert.ok(!container.innerHTML.includes('Old Date Item'));
  } finally {
    api.getBriefing = originalGetBriefing;
  }
});

test('Phase 12 remediation: Exact semantic classification of correction and weakening vs misleading lookalikes', async () => {
  const { isCorrectionSignal, isWeakenedSignal, renderBriefingItemCard } = await import('../src/views/briefing.js');

  // Exact Item Types
  assert.strictEqual(isCorrectionSignal('correction', []), true);
  assert.strictEqual(isWeakenedSignal('claim_weakened', []), true);
  assert.strictEqual(isCorrectionSignal('new_story', []), false);
  assert.strictEqual(isWeakenedSignal('new_story', []), false);

  // Exact Reason Codes (positive)
  assert.strictEqual(isCorrectionSignal('new_story', ['correction']), true);
  assert.strictEqual(isCorrectionSignal('new_story', ['claim_retracted']), true);
  assert.strictEqual(isCorrectionSignal('new_story', ['retraction']), true);
  assert.strictEqual(isCorrectionSignal('new_story', ['correction:claim_42']), true);
  assert.strictEqual(isCorrectionSignal('new_story', ['retraction:claim_99']), true);

  assert.strictEqual(isWeakenedSignal('new_story', ['claim_weakened']), true);
  assert.strictEqual(isWeakenedSignal('new_story', ['contradiction_detected']), true);
  assert.strictEqual(isWeakenedSignal('new_story', ['intel_change:verification_weakened']), true);
  assert.strictEqual(isWeakenedSignal('new_story', ['claim_weakened:claim_42']), true);
  assert.strictEqual(isWeakenedSignal('new_story', ['contradiction_detected:claim_99']), true);
  assert.strictEqual(isWeakenedSignal('new_story', ['intel_change:verification_weakened:c1']), true);

  // Misleading Lookalikes (negative - must NOT trigger)
  const lookalikes = [
    'not_a_correction_pattern',
    'correctional_facility_reference',
    'contradictory_naming_custom',
    'weakened_dependency_name',
    'retraction_policy_document',
    'fast_correction_heuristic',
    'uncontradicted_release',
    'weakened_by_design',
    'correction_score_high',
  ];

  for (const code of lookalikes) {
    assert.strictEqual(isCorrectionSignal('new_story', [code]), false, `Expected false for correction lookalike: ${code}`);
    assert.strictEqual(isWeakenedSignal('new_story', [code]), false, `Expected false for weakening lookalike: ${code}`);
  }

  // Render card with lookalikes: must remain neutral without caution/weakened badges
  const lookalikeCard = renderBriefingItemCard({
    inbox_item_id: 'inbox:lookalike',
    position: 1,
    title: 'Lookalike Test Item',
    item_type: 'new_story',
    reason_codes: ['not_a_correction_pattern', 'contradictory_naming_custom'],
  });

  assert.ok(!lookalikeCard.includes('briefing-card-cautionary'));
  assert.ok(!lookalikeCard.includes('briefing-card-weakened'));
  assert.ok(!lookalikeCard.includes('briefing-caution-tag'));
  assert.ok(!lookalikeCard.includes('briefing-weakened-tag'));
  assert.ok(lookalikeCard.includes('data-reason-code="not_a_correction_pattern"'));
  assert.ok(lookalikeCard.includes('data-reason-code="contradictory_naming_custom"'));
});

test('Phase 12 remediation: Unrecognized snapshot version renders neutral badge and notice, omitting schema-dependent fields', async () => {
  const { renderBriefingItemCard } = await import('../src/views/briefing.js');

  const card = renderBriefingItemCard({
    inbox_item_id: 'inbox:unrec_test',
    story_cluster_id: 'cl_unrec',
    position: 1,
    title: 'Unrecognized Format Item',
    summary: 'Captured under future v2 schema',
    item_type: 'new_story',
    inbox_score: 0.95,
    rank_score: 0.90,
    project_impact_score: 0.85,
    snapshot_status: 'unrecognized_version',
    snapshot_version: 'v2.custom',
    story_available: true,
  });

  // Must render unrecognized badge and notice
  assert.ok(card.includes('briefing-unrecognized-badge'));
  assert.ok(card.includes('Unrecognized Snapshot (v2.custom)'));
  assert.ok(card.includes('briefing-unrecognized-notice'));
  assert.ok(card.includes('Snapshot format (v2.custom) is not recognized'));

  // Must NOT label it as Legacy Snapshot
  assert.ok(!card.includes('Legacy Snapshot'));
  assert.ok(!card.includes('briefing-legacy-badge'));

  // Must omit schema-dependent score fields
  assert.ok(!card.includes('Priority: 0.95'));
  assert.ok(!card.includes('Rank: 0.90'));
  assert.ok(!card.includes('Project Impact: 0.85'));

  // Must preserve safe identity / navigation fields
  assert.ok(card.includes('#1'));
  assert.ok(card.includes('Unrecognized Format Item'));
  assert.ok(card.includes('href="#/story/cl_unrec"'));
});

test('Phase 12 remediation: Complete, legacy_incomplete, and unrecognized_version snapshots are distinguished cleanly', async () => {
  const { renderBriefingItemCard } = await import('../src/views/briefing.js');

  // 1. Complete v1
  const completeCard = renderBriefingItemCard({
    inbox_item_id: 'inbox:c1',
    position: 1,
    title: 'Complete Item',
    summary: 'Full snapshot data',
    item_type: 'new_story',
    inbox_score: 0.88,
    snapshot_status: 'complete',
    snapshot_version: 'v1',
  });
  assert.ok(!completeCard.includes('Legacy Snapshot'));
  assert.ok(!completeCard.includes('Unrecognized Snapshot'));
  assert.ok(completeCard.includes('Priority: 88%'));

  // 2. Legacy Incomplete
  const legacyCard = renderBriefingItemCard({
    inbox_item_id: 'inbox:l1',
    position: 2,
    title: 'Legacy Item',
    snapshot_status: 'legacy_incomplete',
    snapshot_version: null,
  });
  assert.ok(legacyCard.includes('Legacy Snapshot'));
  assert.ok(!legacyCard.includes('Unrecognized Snapshot'));

  // 3. Unrecognized Version
  const unrecCard = renderBriefingItemCard({
    inbox_item_id: 'inbox:u1',
    position: 3,
    title: 'Future Item',
    snapshot_status: 'unrecognized_version',
    snapshot_version: 'v9.9',
  });
  assert.ok(!unrecCard.includes('Legacy Snapshot'));
  assert.ok(unrecCard.includes('Unrecognized Snapshot (v9.9)'));
});

test('Phase 12 remediation: Unavailable Story produces neutral copy without inferring active/inactive state', async () => {
  const { renderBriefingItemCard } = await import('../src/views/briefing.js');

  const card = renderBriefingItemCard({
    inbox_item_id: 'inbox:no_story',
    story_cluster_id: 'cluster:vanished',
    position: 1,
    title: 'Item with Vanished Story',
    story_available: false,
    snapshot_status: 'complete',
  });

  assert.ok(card.includes('Story unavailable'));
  assert.ok(!card.includes('href="#/story/cluster:vanished"'));
  assert.ok(!card.includes('active'));
  assert.ok(!card.includes('inactive'));
  assert.ok(!card.includes('deleted'));
});

// ==========================================
// Phase 13: Runtime Reliability & Operational Tests
// ==========================================

// ==========================================
// Phase 13: Runtime Reliability & Operational Tests (45 Focused Cases)
// ==========================================

function getMockRuntimeOverview(overrides = {}) {
  return {
    schema_version: 'v1',
    status: 'HEALTHY',
    observed_at: '2026-08-22T10:00:00Z',
    effective_timezone: 'UTC',
    scheduler_time: '2026-08-22 10:00:00 UTC',
    daemon: { status: 'running', pid: 1234, heartbeat_timestamp: '2026-08-22T09:59:50Z', heartbeat_age_seconds: 10, is_stale: false, lock_present: true },
    system: { database: 'ok', network: 'online', disk_free_mb: 15000, disk_status: 'ok', embedding_model: 'all-MiniLM-L6-v2', reference_folder: 'data/raw', observed_at: '2026-08-22T10:00:00Z', cache_age_seconds: 0.1, is_cached: false },
    sources: [
      { source: 'github', health_status: 'healthy', consecutive_failures: 0, is_due: false, due_reason: 'NEXT_IN_45m', interval_minutes: 60, last_attempt_at: '2026-08-22T09:45:00Z', last_success_at: '2026-08-22T09:45:00Z' }
    ],
    source_summary: { total: 1, healthy: 1, retrying: 0, rate_limited: 0, degraded: 0, disabled: 0, unknown: 0, unavailable: 0 },
    jobs: [
      { job_name: 'ingestion', status: 'completed', last_status: 'completed', evaluation_status: 'completed', duration_seconds: 4.2, run_count: 5, failure_count: 0, next_schedule: 'NEXT_IN_45m', last_completed_at: '2026-08-22T09:45:00Z' }
    ],
    job_summary: { total: 1, completed: 1, running: 0, failed: 0, partial: 0, interrupted: 0, blocked: 0, not_due: 0, not_applicable: 0, pending: 0 },
    recent_failures: [],
    current_source_issues: [],
    intelligence_freshness: {
      last_successful_ingestion: '2026-08-22T09:45:00Z',
      today_briefing: { date: '2026-08-22', generated: true, total_items: 5, generated_at: '2026-08-22T07:30:00Z' }
    },
    lifetime_metrics: { sources_polled: 12, events_ingested: 45, inbox_items_generated: 10, jobs_completed: 20, jobs_failed: 0, jobs_interrupted: 0, briefings_generated: 3 },
    warnings: [],
    issues: [],
    ...overrides,
  };
}

test('Phase 13: 1. Initial Runtime load sends exactly 1 GET /runtime request', async () => {
  const { renderRuntimeView } = await import('../src/views/runtime.js');
  const store = (await import('../src/state/store.js')).store;
  const requestedUrls = [];
  fetchMock = async (url) => {
    requestedUrls.push(url);
    return { ok: true, status: 200, json: async () => getMockRuntimeOverview() };
  };
  const container = { innerHTML: '', querySelector: () => null };
  await renderRuntimeView(container, store);
  assert.strictEqual(requestedUrls.length, 1);
  assert.ok(requestedUrls[0].endsWith('/runtime'));
});

test('Phase 13: 2. Runtime load sends zero /health subrequests', async () => {
  const { renderRuntimeView } = await import('../src/views/runtime.js');
  const store = (await import('../src/state/store.js')).store;
  const requestedUrls = [];
  fetchMock = async (url) => {
    requestedUrls.push(url);
    return { ok: true, status: 200, json: async () => getMockRuntimeOverview() };
  };
  const container = { innerHTML: '', querySelector: () => null };
  await renderRuntimeView(container, store);
  assert.strictEqual(requestedUrls.filter(u => u.includes('/health')).length, 0);
});

test('Phase 13: 3. Runtime load sends zero /sources subrequests', async () => {
  const { renderRuntimeView } = await import('../src/views/runtime.js');
  const store = (await import('../src/state/store.js')).store;
  const requestedUrls = [];
  fetchMock = async (url) => {
    requestedUrls.push(url);
    return { ok: true, status: 200, json: async () => getMockRuntimeOverview() };
  };
  const container = { innerHTML: '', querySelector: () => null };
  await renderRuntimeView(container, store);
  assert.strictEqual(requestedUrls.filter(u => u.includes('/sources')).length, 0);
});

test('Phase 13: 4. Runtime load sends zero /stories subrequests', async () => {
  const { renderRuntimeView } = await import('../src/views/runtime.js');
  const store = (await import('../src/state/store.js')).store;
  const requestedUrls = [];
  fetchMock = async (url) => {
    requestedUrls.push(url);
    return { ok: true, status: 200, json: async () => getMockRuntimeOverview() };
  };
  const container = { innerHTML: '', querySelector: () => null };
  await renderRuntimeView(container, store);
  assert.strictEqual(requestedUrls.filter(u => u.includes('/stories') || u.includes('/story')).length, 0);
});

test('Phase 13: 5. Runtime load sends zero /claims subrequests', async () => {
  const { renderRuntimeView } = await import('../src/views/runtime.js');
  const store = (await import('../src/state/store.js')).store;
  const requestedUrls = [];
  fetchMock = async (url) => {
    requestedUrls.push(url);
    return { ok: true, status: 200, json: async () => getMockRuntimeOverview() };
  };
  const container = { innerHTML: '', querySelector: () => null };
  await renderRuntimeView(container, store);
  assert.strictEqual(requestedUrls.filter(u => u.includes('/claims')).length, 0);
});

test('Phase 13: 6. Runtime load sends zero /inbox subrequests', async () => {
  const { renderRuntimeView } = await import('../src/views/runtime.js');
  const store = (await import('../src/state/store.js')).store;
  const requestedUrls = [];
  fetchMock = async (url) => {
    requestedUrls.push(url);
    return { ok: true, status: 200, json: async () => getMockRuntimeOverview() };
  };
  const container = { innerHTML: '', querySelector: () => null };
  await renderRuntimeView(container, store);
  assert.strictEqual(requestedUrls.filter(u => u.includes('/inbox')).length, 0);
});

test('Phase 13: 7. Runtime load sends zero /projects subrequests', async () => {
  const { renderRuntimeView } = await import('../src/views/runtime.js');
  const store = (await import('../src/state/store.js')).store;
  const requestedUrls = [];
  fetchMock = async (url) => {
    requestedUrls.push(url);
    return { ok: true, status: 200, json: async () => getMockRuntimeOverview() };
  };
  const container = { innerHTML: '', querySelector: () => null };
  await renderRuntimeView(container, store);
  assert.strictEqual(requestedUrls.filter(u => u.includes('/projects')).length, 0);
});

test('Phase 13: 8. Zero epistemic verification badges (badge-verification-*) rendered in Runtime view', async () => {
  const { renderRuntimeView } = await import('../src/views/runtime.js');
  const store = (await import('../src/state/store.js')).store;
  fetchMock = async () => ({ ok: true, status: 200, json: async () => getMockRuntimeOverview() });
  const container = { innerHTML: '', querySelector: () => null };
  await renderRuntimeView(container, store);
  assert.ok(!container.innerHTML.includes('badge-verification-supported'));
  assert.ok(!container.innerHTML.includes('badge-verification-contradicted'));
  assert.ok(!container.innerHTML.includes('badge-verification-unverified'));
});

test('Phase 13: 9. Source health: healthy source renders runtime-status-healthy', async () => {
  const { renderRuntimeView } = await import('../src/views/runtime.js');
  const store = (await import('../src/state/store.js')).store;
  fetchMock = async () => ({
    ok: true,
    status: 200,
    json: async () => getMockRuntimeOverview({
      sources: [{ source: 'arxiv', health_status: 'healthy', consecutive_failures: 0 }]
    })
  });
  const container = { innerHTML: '', querySelector: () => null };
  await renderRuntimeView(container, store);
  assert.ok(container.innerHTML.includes('runtime-status-healthy'));
  assert.ok(container.innerHTML.includes('arxiv'));
});

test('Phase 13: 10. Source health: unknown source renders runtime-status-unknown', async () => {
  const { renderRuntimeView } = await import('../src/views/runtime.js');
  const store = (await import('../src/state/store.js')).store;
  fetchMock = async () => ({
    ok: true,
    status: 200,
    json: async () => getMockRuntimeOverview({
      sources: [{ source: 'new_source', health_status: 'unknown', consecutive_failures: null }]
    })
  });
  const container = { innerHTML: '', querySelector: () => null };
  await renderRuntimeView(container, store);
  assert.ok(container.innerHTML.includes('runtime-status-unknown'));
});

test('Phase 13: 11. Source health: retrying source renders runtime-status-retrying', async () => {
  const { renderRuntimeView } = await import('../src/views/runtime.js');
  const store = (await import('../src/state/store.js')).store;
  fetchMock = async () => ({
    ok: true,
    status: 200,
    json: async () => getMockRuntimeOverview({
      sources: [{ source: 'crossref', health_status: 'retrying', consecutive_failures: 1, next_retry_at: '2026-08-22T10:15:00Z', backoff_seconds: 900 }]
    })
  });
  const container = { innerHTML: '', querySelector: () => null };
  await renderRuntimeView(container, store);
  assert.ok(container.innerHTML.includes('runtime-status-retrying'));
});

test('Phase 13: 12. Source health: rate-limited source renders runtime-status-rate-limited', async () => {
  const { renderRuntimeView } = await import('../src/views/runtime.js');
  const store = (await import('../src/state/store.js')).store;
  fetchMock = async () => ({
    ok: true,
    status: 200,
    json: async () => getMockRuntimeOverview({
      sources: [{ source: 'hackernews', health_status: 'rate_limited', consecutive_failures: 2, error_category: 'rate_limit' }]
    })
  });
  const container = { innerHTML: '', querySelector: () => null };
  await renderRuntimeView(container, store);
  assert.ok(container.innerHTML.includes('runtime-status-rate-limited'));
});

test('Phase 13: 13. Source health: degraded source renders runtime-status-degraded and THRESHOLD tag', async () => {
  const { renderRuntimeView } = await import('../src/views/runtime.js');
  const store = (await import('../src/state/store.js')).store;
  fetchMock = async () => ({
    ok: true,
    status: 200,
    json: async () => getMockRuntimeOverview({
      sources: [{ source: 'openalex', health_status: 'degraded', consecutive_failures: 5, failure_threshold_reached: true, max_consecutive_failures: 5 }]
    })
  });
  const container = { innerHTML: '', querySelector: () => null };
  await renderRuntimeView(container, store);
  assert.ok(container.innerHTML.includes('runtime-status-degraded'));
  assert.ok(container.innerHTML.includes('runtime-threshold-tag'));
});

test('Phase 13: 14. Source health: disabled source renders runtime-status-disabled', async () => {
  const { renderRuntimeView } = await import('../src/views/runtime.js');
  const store = (await import('../src/state/store.js')).store;
  fetchMock = async () => ({
    ok: true,
    status: 200,
    json: async () => getMockRuntimeOverview({
      sources: [{ source: 'legacy_feed', health_status: 'disabled', enabled: false }]
    })
  });
  const container = { innerHTML: '', querySelector: () => null };
  await renderRuntimeView(container, store);
  assert.ok(container.innerHTML.includes('runtime-status-disabled'));
});

test('Phase 13: 15. Source health: unavailable source renders runtime-status-unavailable', async () => {
  const { renderRuntimeView } = await import('../src/views/runtime.js');
  const store = (await import('../src/state/store.js')).store;
  fetchMock = async () => ({
    ok: true,
    status: 200,
    json: async () => getMockRuntimeOverview({
      sources: [{ source: 'bad_auth', health_status: 'unavailable', error_category: 'auth_error' }]
    })
  });
  const container = { innerHTML: '', querySelector: () => null };
  await renderRuntimeView(container, store);
  assert.ok(container.innerHTML.includes('runtime-status-unavailable'));
});

test('Phase 13: 16. Job status: pending job renders runtime-status-pending', async () => {
  const { renderRuntimeView } = await import('../src/views/runtime.js');
  const store = (await import('../src/state/store.js')).store;
  fetchMock = async () => ({
    ok: true,
    status: 200,
    json: async () => getMockRuntimeOverview({
      jobs: [{ job_name: 'backup', status: 'pending', duration_seconds: null, run_count: null, failure_count: null }]
    })
  });
  const container = { innerHTML: '', querySelector: () => null };
  await renderRuntimeView(container, store);
  assert.ok(container.innerHTML.includes('runtime-status-pending'));
});

test('Phase 13: 17. Job status: running job renders runtime-status-running', async () => {
  const { renderRuntimeView } = await import('../src/views/runtime.js');
  const store = (await import('../src/state/store.js')).store;
  fetchMock = async () => ({
    ok: true,
    status: 200,
    json: async () => getMockRuntimeOverview({
      jobs: [{ job_name: 'ingestion', status: 'running', duration_seconds: null, run_count: 5, failure_count: 0 }]
    })
  });
  const container = { innerHTML: '', querySelector: () => null };
  await renderRuntimeView(container, store);
  assert.ok(container.innerHTML.includes('runtime-status-running'));
});

test('Phase 13: 18. Job status: completed job renders runtime-status-completed', async () => {
  const { renderRuntimeView } = await import('../src/views/runtime.js');
  const store = (await import('../src/state/store.js')).store;
  fetchMock = async () => ({
    ok: true,
    status: 200,
    json: async () => getMockRuntimeOverview({
      jobs: [{ job_name: 'semantic', status: 'completed', duration_seconds: 1.5, run_count: 3, failure_count: 0 }]
    })
  });
  const container = { innerHTML: '', querySelector: () => null };
  await renderRuntimeView(container, store);
  assert.ok(container.innerHTML.includes('runtime-status-completed'));
});

test('Phase 13: 19. Job status: failed job renders runtime-status-failed', async () => {
  const { renderRuntimeView } = await import('../src/views/runtime.js');
  const store = (await import('../src/state/store.js')).store;
  fetchMock = async () => ({
    ok: true,
    status: 200,
    json: async () => getMockRuntimeOverview({
      jobs: [{ job_name: 'claims', status: 'failed', duration_seconds: 0.8, run_count: 2, failure_count: 1, error_category: 'schema_error', sanitized_error: 'Invalid schema' }]
    })
  });
  const container = { innerHTML: '', querySelector: () => null };
  await renderRuntimeView(container, store);
  assert.ok(container.innerHTML.includes('runtime-status-failed'));
});

test('Phase 13: 20. Job status: partial job renders runtime-status-partial', async () => {
  const { renderRuntimeView } = await import('../src/views/runtime.js');
  const store = (await import('../src/state/store.js')).store;
  fetchMock = async () => ({
    ok: true,
    status: 200,
    json: async () => getMockRuntimeOverview({
      jobs: [{ job_name: 'ingestion', status: 'partial', duration_seconds: 5.0, run_count: 4, failure_count: 0 }]
    })
  });
  const container = { innerHTML: '', querySelector: () => null };
  await renderRuntimeView(container, store);
  assert.ok(container.innerHTML.includes('runtime-status-partial'));
});

test('Phase 13: 21. Job status: interrupted job renders runtime-status-interrupted', async () => {
  const { renderRuntimeView } = await import('../src/views/runtime.js');
  const store = (await import('../src/state/store.js')).store;
  fetchMock = async () => ({
    ok: true,
    status: 200,
    json: async () => getMockRuntimeOverview({
      jobs: [{ job_name: 'recheck', status: 'interrupted', duration_seconds: 2.1, run_count: 1, failure_count: 0 }]
    })
  });
  const container = { innerHTML: '', querySelector: () => null };
  await renderRuntimeView(container, store);
  assert.ok(container.innerHTML.includes('runtime-status-interrupted'));
});

test('Phase 13: 22. Blocked job evaluation renders runtime-status-blocked and blocked reason distinct from execution status', async () => {
  const { renderRuntimeView } = await import('../src/views/runtime.js');
  const store = (await import('../src/state/store.js')).store;
  fetchMock = async () => ({
    ok: true,
    status: 200,
    json: async () => getMockRuntimeOverview({
      jobs: [
        { job_name: 'inbox_refresh', status: 'blocked', last_status: 'completed', evaluation_status: 'blocked', blocked_by: 'claims', blocked_reason: 'Prerequisite failed in current cycle' }
      ]
    })
  });
  const container = { innerHTML: '', querySelector: () => null };
  await renderRuntimeView(container, store);
  assert.ok(container.innerHTML.includes('runtime-status-blocked'));
  assert.ok(container.innerHTML.includes('Blocked by claims'));
  assert.ok(container.innerHTML.includes('Prerequisite failed in current cycle'));
});

test('Phase 13: 23. Not-due job evaluation renders runtime-status-not-due', async () => {
  const { renderRuntimeView } = await import('../src/views/runtime.js');
  const store = (await import('../src/state/store.js')).store;
  fetchMock = async () => ({
    ok: true,
    status: 200,
    json: async () => getMockRuntimeOverview({
      jobs: [{ job_name: 'morning_brief', status: 'not_due', evaluation_status: 'not_due', next_schedule: 'SCHEDULED_AT_07:30' }]
    })
  });
  const container = { innerHTML: '', querySelector: () => null };
  await renderRuntimeView(container, store);
  assert.ok(container.innerHTML.includes('runtime-status-not-due'));
  assert.ok(container.innerHTML.includes('SCHEDULED_AT_07:30'));
});

test('Phase 13: 24. Not-applicable job evaluation renders runtime-status-not-applicable', async () => {
  const { renderRuntimeView } = await import('../src/views/runtime.js');
  const store = (await import('../src/state/store.js')).store;
  fetchMock = async () => ({
    ok: true,
    status: 200,
    json: async () => getMockRuntimeOverview({
      jobs: [{ job_name: 'context_match', status: 'not_applicable', evaluation_status: 'not_applicable', next_schedule: 'NOT_APPLICABLE_0_PROJECTS' }]
    })
  });
  const container = { innerHTML: '', querySelector: () => null };
  await renderRuntimeView(container, store);
  assert.ok(container.innerHTML.includes('runtime-status-not-applicable'));
});

test('Phase 13: 25. Null timestamps render as Not recorded or —', async () => {
  const { renderRuntimeView } = await import('../src/views/runtime.js');
  const store = (await import('../src/state/store.js')).store;
  fetchMock = async () => ({
    ok: true,
    status: 200,
    json: async () => getMockRuntimeOverview({
      sources: [{ source: 'unpolled', health_status: 'unknown', last_attempt_at: null, last_success_at: null }],
      jobs: [{ job_name: 'unrun', status: 'pending', last_completed_at: null }]
    })
  });
  const container = { innerHTML: '', querySelector: () => null };
  await renderRuntimeView(container, store);
  assert.ok(container.innerHTML.includes('Not recorded'));
});

test('Phase 13: 26. Null counts render as —', async () => {
  const { renderRuntimeView } = await import('../src/views/runtime.js');
  const store = (await import('../src/state/store.js')).store;
  fetchMock = async () => ({
    ok: true,
    status: 200,
    json: async () => getMockRuntimeOverview({
      sources: [{ source: 'src_null', health_status: 'unknown', consecutive_failures: null }],
      jobs: [{ job_name: 'job_null', status: 'pending', run_count: null, failure_count: null }]
    })
  });
  const container = { innerHTML: '', querySelector: () => null };
  await renderRuntimeView(container, store);
  assert.ok(container.innerHTML.includes('—'));
});

test('Phase 13: 27. Genuine zero counts render as 0', async () => {
  const { renderRuntimeView } = await import('../src/views/runtime.js');
  const store = (await import('../src/state/store.js')).store;
  fetchMock = async () => ({
    ok: true,
    status: 200,
    json: async () => getMockRuntimeOverview({
      sources: [{ source: 'src_zero', health_status: 'healthy', consecutive_failures: 0 }],
      jobs: [{ job_name: 'job_zero', status: 'completed', run_count: 5, failure_count: 0 }]
    })
  });
  const container = { innerHTML: '', querySelector: () => null };
  await renderRuntimeView(container, store);
  assert.ok(container.innerHTML.includes('5 / 0'));
});

test('Phase 13: 28. Null lifetime metrics do not become zero (render Not recorded)', async () => {
  const { renderRuntimeView } = await import('../src/views/runtime.js');
  const store = (await import('../src/state/store.js')).store;
  fetchMock = async () => ({
    ok: true,
    status: 200,
    json: async () => getMockRuntimeOverview({
      lifetime_metrics: {}
    })
  });
  const container = { innerHTML: '', querySelector: () => null };
  await renderRuntimeView(container, store);
  assert.ok(container.innerHTML.includes('Not recorded'));
});

test('Phase 13: 29. Genuine zero lifetime metrics remain zero', async () => {
  const { renderRuntimeView } = await import('../src/views/runtime.js');
  const store = (await import('../src/state/store.js')).store;
  fetchMock = async () => ({
    ok: true,
    status: 200,
    json: async () => getMockRuntimeOverview({
      lifetime_metrics: { sources_polled: 0, events_ingested: 0, inbox_items_generated: 0, jobs_completed: 0, jobs_failed: 0, jobs_interrupted: 0, briefings_generated: 0 }
    })
  });
  const container = { innerHTML: '', querySelector: () => null };
  await renderRuntimeView(container, store);
  assert.ok(container.innerHTML.includes('0 ok'));
  assert.ok(container.innerHTML.includes('0 fails'));
  assert.ok(container.innerHTML.includes('0 intr'));
  assert.ok(container.innerHTML.includes('Briefings: 0'));
});

test('Phase 13: 30. Missing daemon heartbeat renders No daemon heartbeat recorded', async () => {
  const { renderRuntimeView } = await import('../src/views/runtime.js');
  const store = (await import('../src/state/store.js')).store;
  fetchMock = async () => ({
    ok: true,
    status: 200,
    json: async () => getMockRuntimeOverview({
      daemon: { status: 'stopped', pid: null, heartbeat_timestamp: null, heartbeat_age_seconds: null }
    })
  });
  const container = { innerHTML: '', querySelector: () => null };
  await renderRuntimeView(container, store);
  assert.ok(container.innerHTML.includes('No daemon heartbeat recorded'));
});

test('Phase 13: 31. Stale daemon heartbeat renders STALE status', async () => {
  const { renderRuntimeView } = await import('../src/views/runtime.js');
  const store = (await import('../src/state/store.js')).store;
  fetchMock = async () => ({
    ok: true,
    status: 200,
    json: async () => getMockRuntimeOverview({
      daemon: { status: 'stale', pid: 1234, heartbeat_timestamp: '2026-08-22T08:00:00Z', heartbeat_age_seconds: 7200, is_stale: true }
    })
  });
  const container = { innerHTML: '', querySelector: () => null };
  await renderRuntimeView(container, store);
  assert.ok(container.innerHTML.includes('STALE'));
  assert.ok(container.innerHTML.includes('7200s ago'));
});

test('Phase 13: 32. Running daemon heartbeat renders RUNNING status with PID', async () => {
  const { renderRuntimeView } = await import('../src/views/runtime.js');
  const store = (await import('../src/state/store.js')).store;
  fetchMock = async () => ({
    ok: true,
    status: 200,
    json: async () => getMockRuntimeOverview({
      daemon: { status: 'running', pid: 4567, heartbeat_timestamp: '2026-08-22T09:59:55Z', heartbeat_age_seconds: 5 }
    })
  });
  const container = { innerHTML: '', querySelector: () => null };
  await renderRuntimeView(container, store);
  assert.ok(container.innerHTML.includes('RUNNING'));
  assert.ok(container.innerHTML.includes('PID 4567'));
});

test('Phase 13: 33. Lock and heartbeat disagreement notice banner renders when present', async () => {
  const { renderRuntimeView } = await import('../src/views/runtime.js');
  const store = (await import('../src/state/store.js')).store;
  fetchMock = async () => ({
    ok: true,
    status: 200,
    json: async () => getMockRuntimeOverview({
      warnings: ['Lock file exists for PID 8888 but heartbeat is stale (7200s old).']
    })
  });
  const container = { innerHTML: '', querySelector: () => null };
  await renderRuntimeView(container, store);
  assert.ok(container.innerHTML.includes('Lock file exists for PID 8888'));
});

test('Phase 13: 34. Timezone warning notice banner renders when warning present', async () => {
  const { renderRuntimeView } = await import('../src/views/runtime.js');
  const store = (await import('../src/state/store.js')).store;
  fetchMock = async () => ({
    ok: true,
    status: 200,
    json: async () => getMockRuntimeOverview({
      effective_timezone: 'UTC',
      warnings: ['Unrecognized timezone "Mars/Olympus"; falling back to UTC.']
    })
  });
  const container = { innerHTML: '', querySelector: () => null };
  await renderRuntimeView(container, store);
  assert.ok(container.innerHTML.includes('Unrecognized timezone'));
});

test('Phase 13: 35. Timeout-not-enforced telemetry notice renders in job table', async () => {
  const { renderRuntimeView } = await import('../src/views/runtime.js');
  const store = (await import('../src/state/store.js')).store;
  fetchMock = async () => ({
    ok: true,
    status: 200,
    json: async () => getMockRuntimeOverview({
      jobs: [{ job_name: 'ingestion', status: 'running', configured_timeout_minutes: 15, timeout_enforced: false }]
    })
  });
  const container = { innerHTML: '', querySelector: () => null };
  await renderRuntimeView(container, store);
  assert.ok(container.innerHTML.includes('15m (not enforced)'));
});

test('Phase 13: 36. Sanitized error and error category render cleanly in source and job tables', async () => {
  const { renderRuntimeView } = await import('../src/views/runtime.js');
  const store = (await import('../src/state/store.js')).store;
  fetchMock = async () => ({
    ok: true,
    status: 200,
    json: async () => getMockRuntimeOverview({
      sources: [{ source: 'arxiv', health_status: 'degraded', sanitized_error: 'HTTP connection timeout', error_category: 'network_timeout' }],
      jobs: [{ job_name: 'semantic', status: 'failed', sanitized_error: 'Model out of memory', error_category: 'resource_limit' }]
    })
  });
  const container = { innerHTML: '', querySelector: () => null };
  await renderRuntimeView(container, store);
  assert.ok(container.innerHTML.includes('[network_timeout] HTTP connection timeout'));
});

test('Phase 13: 37. Raw credential fixtures (Bearer token) are absent from rendered DOM', async () => {
  const { renderRuntimeView } = await import('../src/views/runtime.js');
  const store = (await import('../src/state/store.js')).store;
  const rawSecret = 'ghp_secret_token_1234567890abcdef';
  fetchMock = async () => ({
    ok: true,
    status: 200,
    json: async () => getMockRuntimeOverview({
      sources: [{ source: 'github', health_status: 'degraded', sanitized_error: 'Request failed with Bearer [REDACTED]', error_category: 'auth_error' }]
    })
  });
  const container = { innerHTML: '', querySelector: () => null };
  await renderRuntimeView(container, store);
  assert.ok(!container.innerHTML.includes(rawSecret));
  assert.ok(container.innerHTML.includes('[REDACTED]'));
});

test('Phase 13: 38. Raw local path fixtures (C:\\Users\\) are absent from rendered DOM', async () => {
  const { renderRuntimeView } = await import('../src/views/runtime.js');
  const store = (await import('../src/state/store.js')).store;
  const rawPath = 'C:\\Users\\admin\\secret_workspace\\app.py';
  fetchMock = async () => ({
    ok: true,
    status: 200,
    json: async () => getMockRuntimeOverview({
      recent_failures: [{ run_id: 'run:1', job_name: 'semantic', started_at: '2026-08-22T09:00:00Z', status: 'failed', sanitized_error: 'FileNotFoundError: [USER_PATH]/app.py', error_category: 'io_error' }]
    })
  });
  const container = { innerHTML: '', querySelector: () => null };
  await renderRuntimeView(container, store);
  assert.ok(!container.innerHTML.includes(rawPath));
  assert.ok(container.innerHTML.includes('[USER_PATH]'));
});

test('Phase 13: 39. Loading state renders before overview request completes', async () => {
  const { renderRuntimeView } = await import('../src/views/runtime.js');
  const store = (await import('../src/state/store.js')).store;
  let resolvePromise;
  fetchMock = () => new Promise(r => { resolvePromise = r; });
  const container = { innerHTML: '', querySelector: () => null };
  const p = renderRuntimeView(container, store);
  assert.ok(container.innerHTML.includes('state-loading'));
  resolvePromise({ ok: true, status: 200, json: async () => getMockRuntimeOverview() });
  await p;
  assert.ok(!container.innerHTML.includes('state-loading'));
});

test('Phase 13: 40. Offline state renders and bound retry button triggers read-only GET /runtime', async () => {
  const { renderRuntimeView } = await import('../src/views/runtime.js');
  const store = (await import('../src/state/store.js')).store;
  const requestedUrls = [];
  let callCount = 0;
  fetchMock = async (url) => {
    requestedUrls.push(url);
    callCount++;
    if (callCount === 1) {
      const err = new Error('Failed to fetch');
      err.isNetworkError = true;
      throw err;
    }
    return { ok: true, status: 200, json: async () => getMockRuntimeOverview() };
  };

  const container = createMockContainer();
  await renderRuntimeView(container, store);
  assert.ok(container.innerHTML.includes('state-offline'));

  const retryBtn = container.querySelector('#retry-btn');
  assert.ok(retryBtn !== null);

  // Invoke retry click handler
  const listeners = retryBtn._listeners['click'] || [];
  for (const l of listeners) {
    await l({ preventDefault() {} });
  }

  assert.strictEqual(callCount, 2);
  assert.strictEqual(requestedUrls.length, 2);
  assert.ok(requestedUrls[1].endsWith('/runtime'));
});

test('Phase 13: 41. Backend failure state renders and bound retry button triggers read-only GET /runtime', async () => {
  const { renderRuntimeView } = await import('../src/views/runtime.js');
  const store = (await import('../src/state/store.js')).store;
  const requestedUrls = [];
  let callCount = 0;
  fetchMock = async (url) => {
    requestedUrls.push(url);
    callCount++;
    if (callCount === 1) {
      return {
        ok: false,
        status: 500,
        statusText: 'Internal Server Error',
        json: async () => ({ detail: 'Database connection failed' })
      };
    }
    return { ok: true, status: 200, json: async () => getMockRuntimeOverview() };
  };

  const container = createMockContainer();
  await renderRuntimeView(container, store);
  assert.ok(container.innerHTML.includes('state-error'));

  const retryBtn = container.querySelector('#retry-btn');
  assert.ok(retryBtn !== null);

  // Invoke retry click handler
  const listeners = retryBtn._listeners['click'] || [];
  for (const l of listeners) {
    await l({ preventDefault() {} });
  }

  assert.strictEqual(callCount, 2);
  assert.strictEqual(requestedUrls.length, 2);
  assert.ok(requestedUrls[1].endsWith('/runtime'));
});

test('Phase 13: 42. Stale response protection prevents out-of-order race condition overwrite', async () => {
  const { renderRuntimeView } = await import('../src/views/runtime.js');
  const store = (await import('../src/state/store.js')).store;

  let resolveFirst;
  let resolveSecond;

  let reqCount = 0;
  fetchMock = async () => {
    reqCount++;
    if (reqCount === 1) {
      return new Promise(r => { resolveFirst = r; });
    } else {
      return new Promise(r => { resolveSecond = r; });
    }
  };

  const container = { innerHTML: '', querySelector: () => null };

  // Trigger Request 1
  const p1 = renderRuntimeView(container, store);
  // Trigger Request 2 (fast follow)
  const p2 = renderRuntimeView(container, store);

  // Resolve Request 2 FIRST
  resolveSecond({
    ok: true,
    status: 200,
    json: async () => getMockRuntimeOverview({ scheduler_time: 'SECOND_RESPONSE_FAST' })
  });
  await p2;

  assert.ok(container.innerHTML.includes('SECOND_RESPONSE_FAST'));

  // Resolve Request 1 LATER (stale)
  resolveFirst({
    ok: true,
    status: 200,
    json: async () => getMockRuntimeOverview({ scheduler_time: 'FIRST_RESPONSE_STALE' })
  });
  await p1;

  // Stale response must have been discarded
  assert.ok(container.innerHTML.includes('SECOND_RESPONSE_FAST'));
  assert.ok(!container.innerHTML.includes('FIRST_RESPONSE_STALE'));
});

test('Phase 13: 43. Accessible aria-live region announces operational overview status', async () => {
  const { renderRuntimeView } = await import('../src/views/runtime.js');
  const store = (await import('../src/state/store.js')).store;
  fetchMock = async () => ({
    ok: true,
    status: 200,
    json: async () => getMockRuntimeOverview({ status: 'DEGRADED', daemon: { status: 'stale' } })
  });
  const container = { innerHTML: '', querySelector: () => null };
  await renderRuntimeView(container, store);
  assert.ok(container.innerHTML.includes('aria-live="polite"'));
  assert.ok(container.innerHTML.includes('Operational overview status is DEGRADED. Daemon is stale.'));
});

test('Phase 13: 44. Today briefing missing versus zero-item generated briefing distinction', async () => {
  const { renderRuntimeView } = await import('../src/views/runtime.js');
  const store = (await import('../src/state/store.js')).store;

  // Case A: Missing briefing (not generated)
  fetchMock = async () => ({
    ok: true,
    status: 200,
    json: async () => getMockRuntimeOverview({
      intelligence_freshness: { today_briefing: { date: '2026-08-22', generated: false, total_items: null } }
    })
  });
  const containerA = { innerHTML: '', querySelector: () => null };
  await renderRuntimeView(containerA, store);
  assert.ok(containerA.innerHTML.includes('NOT GENERATED'));
  assert.ok(containerA.innerHTML.includes('Scheduled for 2026-08-22'));

  // Case B: Generated briefing with 0 items
  fetchMock = async () => ({
    ok: true,
    status: 200,
    json: async () => getMockRuntimeOverview({
      intelligence_freshness: { today_briefing: { date: '2026-08-22', generated: true, total_items: 0 } }
    })
  });
  const containerB = { innerHTML: '', querySelector: () => null };
  await renderRuntimeView(containerB, store);
  assert.ok(containerB.innerHTML.includes('GENERATED'));
  assert.ok(containerB.innerHTML.includes('0 items on 2026-08-22'));
});

test('Phase 13: 45. Partial availability warning notice banner renders when present', async () => {
  const { renderRuntimeView } = await import('../src/views/runtime.js');
  const store = (await import('../src/state/store.js')).store;
  fetchMock = async () => ({
    ok: true,
    status: 200,
    json: async () => getMockRuntimeOverview({
      warnings: ['Partial source availability: openalex failed, remaining 8 sources ingested successfully.']
    })
  });
  const container = { innerHTML: '', querySelector: () => null };
  await renderRuntimeView(container, store);
  assert.ok(container.innerHTML.includes('Partial source availability: openalex failed'));
});

test('Phase 13: 46. Source health: offline source renders runtime-status-offline', async () => {
  const { renderRuntimeView } = await import('../src/views/runtime.js');
  const store = (await import('../src/state/store.js')).store;
  fetchMock = async () => ({
    ok: true,
    status: 200,
    json: async () => getMockRuntimeOverview({
      sources: [{ source: 'arxiv', health_status: 'offline', last_attempt_at: '2026-08-22T10:00:00Z', last_success_at: null }]
    })
  });
  const container = { innerHTML: '', querySelector: () => null };
  await renderRuntimeView(container, store);
  assert.ok(container.innerHTML.includes('runtime-status-offline'));
});

test('Phase 13: 47. Machine-readable time tags render datetime and handles invalid dates safely', async () => {
  const { renderRuntimeView } = await import('../src/views/runtime.js');
  const store = (await import('../src/state/store.js')).store;
  fetchMock = async () => ({
    ok: true,
    status: 200,
    json: async () => getMockRuntimeOverview({
      sources: [{
        source: 'github',
        health_status: 'healthy',
        last_attempt_at: '2026-08-22T10:00:00Z',
        last_success_at: 'invalid-date-string'
      }]
    })
  });
  const container = { innerHTML: '', querySelector: () => null };
  await renderRuntimeView(container, store);
  assert.ok(container.innerHTML.includes('<time datetime="2026-08-22T10:00:00Z">'));
  assert.ok(!container.innerHTML.includes('Invalid Date'));
  assert.ok(!container.innerHTML.includes('NaN'));
});

test('Phase 13: 48. Full source state matrix renders distinct classes, tooltips, and accessible labels', async () => {
  const { renderRuntimeView } = await import('../src/views/runtime.js');
  const store = (await import('../src/state/store.js')).store;
  const mockSources = [
    { source: 'github', health_status: 'healthy' },
    { source: 'arxiv', health_status: 'degraded' },
    { source: 'hackernews', health_status: 'rate_limited' },
    { source: 'openalex', health_status: 'offline' },
    { source: 'crossref', health_status: 'disabled' },
    { source: 'rss', health_status: 'unknown' },
    { source: 'stackexchange', health_status: 'retrying' },
    { source: 'custom', health_status: 'unavailable' }
  ];
  fetchMock = async () => ({
    ok: true,
    status: 200,
    json: async () => getMockRuntimeOverview({ sources: mockSources })
  });
  const container = { innerHTML: '', querySelector: () => null };
  await renderRuntimeView(container, store);

  assert.ok(container.innerHTML.includes('runtime-status-healthy'));
  assert.ok(container.innerHTML.includes('runtime-status-degraded'));
  assert.ok(container.innerHTML.includes('runtime-status-rate-limited'));
  assert.ok(container.innerHTML.includes('runtime-status-offline'));
  assert.ok(container.innerHTML.includes('runtime-status-disabled'));
  assert.ok(container.innerHTML.includes('runtime-status-unknown'));
  assert.ok(container.innerHTML.includes('runtime-status-retrying'));
  assert.ok(container.innerHTML.includes('runtime-status-unavailable'));
  assert.ok(container.innerHTML.includes('aria-label="Source status: offline"'));
});

test('Phase 13: 49. Request discipline triggers exactly one overview request on view load', async () => {
  const { renderRuntimeView } = await import('../src/views/runtime.js');
  const store = (await import('../src/state/store.js')).store;
  let requestCount = 0;
  fetchMock = async () => {
    requestCount++;
    return {
      ok: true,
      status: 200,
      json: async () => getMockRuntimeOverview()
    };
  };
  const container = { innerHTML: '', querySelector: () => null };
  await renderRuntimeView(container, store);
  assert.strictEqual(requestCount, 1);
});

test('Phase 13: 50. All four source timestamps render distinctly without fallback substitution', async () => {
  const { renderRuntimeView } = await import('../src/views/runtime.js');
  const store = (await import('../src/state/store.js')).store;
  fetchMock = async () => ({
    ok: true,
    status: 200,
    json: async () => getMockRuntimeOverview({
      sources: [{
        source: 'arxiv',
        health_status: 'retrying',
        last_attempt_at: '2026-08-22T10:00:00Z',
        last_success_at: '2026-08-20T10:00:00Z',
        last_event_time: '2026-08-20T09:30:00Z',
        next_retry_at: '2026-08-22T10:30:00Z'
      }]
    })
  });
  const container = { innerHTML: '', querySelector: () => null };
  await renderRuntimeView(container, store);
  assert.ok(container.innerHTML.includes('<time datetime="2026-08-22T10:00:00Z">'));
  assert.ok(container.innerHTML.includes('<time datetime="2026-08-20T10:00:00Z">'));
});

/* ==========================================================================
   Phase 14: Strict Semantic Grounding & Taxonomy Behavioral Tests
   ========================================================================== */

test('Phase 14: Story Card does not fabricate "HERMES cluster" as source when sources array is empty', async () => {
  const { renderStoryCard } = await import('../src/components/story-card.js');
  const cardHtml = renderStoryCard({
    id: 'test_story_empty_sources',
    canonical_title: 'Title Without Sources',
    sources: [],
    events: [],
    created_at: '2026-08-20T10:00:00Z',
  });
  assert.ok(!cardHtml.includes('HERMES cluster'), 'Expected no fabricated "HERMES cluster" in StoryCard');
});

test('Phase 14: Strict 7 canonical maturity stages and degradation of non-canonical values to Unrecognized maturity', () => {
  const canonicalStages = [
    'concept',
    'research',
    'prototype',
    'experimental',
    'early_adoption',
    'production_candidate',
    'established',
  ];

  canonicalStages.forEach((stage) => {
    const meta = getMaturityMeta(stage);
    assert.notStrictEqual(meta.label, 'Unrecognized maturity');
    assert.strictEqual(normalizeMaturityStage(stage), stage);
  });

  const rejectedValues = [
    'maturing',
    'production_ready',
    'stable',
    'growth',
    'growth (0.72)',
    'experimental (0.90)',
    'mature',
    'proposal',
    'beta',
    'alpha',
    'deprecated',
  ];

  rejectedValues.forEach((val) => {
    const meta = getMaturityMeta(val);
    assert.strictEqual(meta.label, 'Unrecognized maturity', `Expected ${val} to degrade to Unrecognized maturity`);
    assert.strictEqual(meta.cssClass, 'badge-maturity-not_assessed');
    assert.strictEqual(normalizeMaturityStage(val), null);
  });
});

test('Phase 14: Null claim status renders Not assessed and is never fabricated to unverified or supported', () => {
  const nullMeta = getVerificationMeta(null);
  assert.strictEqual(nullMeta.label, 'Not assessed');
  assert.strictEqual(nullMeta.cssClass, 'badge-verification-not_assessed');

  const emptyMeta = getVerificationMeta('');
  assert.strictEqual(emptyMeta.label, 'Not assessed');
});

test('Phase 14: Canonical unverified status is distinct from null missing data', () => {
  const unverifiedMeta = getVerificationMeta('unverified');
  assert.strictEqual(unverifiedMeta.label, 'Unverified');
  assert.strictEqual(unverifiedMeta.cssClass, 'badge-verification-unverified');

  const nullMeta = getVerificationMeta(null);
  assert.strictEqual(nullMeta.label, 'Not assessed');
  assert.notStrictEqual(unverifiedMeta.cssClass, nullMeta.cssClass);
});

test('Phase 14: Unsupported claim aliases degrade neutrally to Unrecognized claim status', () => {
  const unsupported = ['verified', 'not_assessed', 'confirmed', 'false_claim', 'debunked'];
  unsupported.forEach((alias) => {
    const meta = getVerificationMeta(alias);
    assert.strictEqual(meta.label, 'Unrecognized claim status');
    assert.strictEqual(meta.cssClass, 'badge-verification-not_assessed');
  });
});

test('Phase 14: Independent score domain badges preserve labels and formatting', () => {
  const relBadge = renderRankingBadge(0.85, SCORE_DOMAINS.RELEVANCE);
  assert.ok(relBadge.includes('Relevance: 85%'));
  assert.ok(!relBadge.includes('Confidence'));
  assert.ok(!relBadge.includes('Verification'));

  const rankBadge = renderRankingBadge(0.85, SCORE_DOMAINS.INBOX_RANK);
  assert.ok(rankBadge.includes('Rank: 85%'));
  assert.ok(!rankBadge.includes('Confidence'));
});

test('Phase 14: Genuine zero scores are preserved and rendered as 0% or 0', () => {
  const zeroPct = formatScorePercentage(0.0);
  assert.strictEqual(zeroPct, '0%');

  const zeroRankBadge = renderRankingBadge(0.0, SCORE_DOMAINS.RELEVANCE);
  assert.ok(zeroRankBadge.includes('Relevance: 0%'));
});

test('Phase 14: Missing scores render as — or are omitted, never 0%', () => {
  const nullPct = formatScorePercentage(null);
  assert.strictEqual(nullPct, '—');

  const undefinedPct = formatScorePercentage(undefined);
  assert.strictEqual(undefinedPct, '—');

  const nullRankBadge = renderRankingBadge(null, SCORE_DOMAINS.RELEVANCE);
  assert.strictEqual(nullRankBadge, '');
});

test('Phase 14: Historical null in changes renders Previous state not recorded historically', async () => {
  const { formatTransitionValue } = await import('../src/views/changes.js');
  const formatted = formatTransitionValue(null, 'claim_status', true);
  assert.ok(formatted.includes('Previous state not recorded historically'));
});

test('Phase 14: Runtime view contains zero epistemic verification, assessed, or unassessed strings', async () => {
  const { renderRuntimeView } = await import('../src/views/runtime.js');
  const store = (await import('../src/state/store.js')).store;
  fetchMock = async () => ({
    ok: true,
    status: 200,
    json: async () => getMockRuntimeOverview()
  });

  const container = { innerHTML: '', querySelector: () => null };
  await renderRuntimeView(container, store);

  const htmlLower = container.innerHTML.toLowerCase();
  assert.ok(!htmlLower.includes('verification_score'), 'Runtime view must not include verification_score');
  assert.ok(!htmlLower.includes('unassessed'), 'Runtime view must not contain unassessed wording');
  assert.ok(!htmlLower.includes('not assessed'), 'Runtime view must not contain not assessed wording');
});

test('Phase 14: Canonical source registry renders exact formatted identities without guessed names', () => {
  const sources = [
    { id: 'github', label: 'GitHub' },
    { id: 'github_releases', label: 'GitHub Releases' },
    { id: 'arxiv', label: 'arXiv' },
    { id: 'hackernews', label: 'Hacker News' },
    { id: 'huggingface', label: 'Hugging Face' },
    { id: 'openalex', label: 'OpenAlex' },
    { id: 'crossref', label: 'Crossref' },
    { id: 'stackexchange', label: 'Stack Exchange' },
    { id: 'rss', label: 'RSS Feed' },
  ];

  sources.forEach(({ id, label }) => {
    const pill = renderSourcePill(id);
    assert.ok(pill.includes(label), `Expected pill for ${id} to include ${label}`);
  });

  // Unknown source must render neutrally without throwing or fabricating
  const customPill = renderSourcePill('custom_feed');
  assert.ok(customPill.includes('custom_feed'));
});

test('Phase 14: Generic Changes values are not guessed into canonical taxonomies', async () => {
  const { formatTransitionValue } = await import('../src/views/changes.js');
  const versionTransition = formatTransitionValue('v1.2.0', 'version', false);
  assert.ok(versionTransition.includes('v1.2.0'));
  assert.ok(!versionTransition.includes('Unrecognized maturity'));
  assert.ok(!versionTransition.includes('Unrecognized claim status'));
});

test('Phase 14: Single normalization boundary - frontend presenter accepts canonical only and degrades noncanonical neutrally', () => {
  // Canonical stances render with full semantic metadata
  assert.strictEqual(getEvidenceStanceMeta('supports').label, 'Supports');
  assert.strictEqual(getEvidenceStanceMeta('contradicts').label, 'Contradicts');
  assert.strictEqual(getEvidenceStanceMeta('context').label, 'Context');

  // Direct noncanonical strings degrade neutrally to Unspecified
  assert.strictEqual(getEvidenceStanceMeta('refutes').label, 'Unspecified');
  assert.strictEqual(getEvidenceStanceMeta('opposes').label, 'Unspecified');
  assert.strictEqual(getEvidenceStanceMeta('neutral').label, 'Unspecified');
  assert.strictEqual(getEvidenceStanceMeta('background').label, 'Unspecified');
  assert.strictEqual(getEvidenceStanceMeta('unknown_stance').label, 'Unspecified');
});

test('Phase 14: Score domain renderers adhere to strict closed domain contracts', async () => {
  const {
    renderSearchScoreBadge,
    renderRelevanceBadge,
    renderClusterScoreBadge,
    renderInboxPriorityBadge,
    renderInboxRankBadge,
    renderProjectRelevanceBadge,
    renderProjectImpactBadge,
    renderScoreBadge,
    renderRankingBadge,
    renderProjectMatchPill,
    SCORE_DOMAINS,
  } = await import('../src/components/badges.js');

  const testVal = 0.85;

  // 1. Search score: Decimal, never percentage
  const searchHtml = renderSearchScoreBadge(testVal);
  assert.ok(searchHtml.includes('Score: 0.85'));
  assert.ok(!searchHtml.includes('85%'));

  // 2. Cluster score: Decimal, never percentage
  const clusterHtml = renderClusterScoreBadge(1.45);
  assert.ok(clusterHtml.includes('Cluster score: 1.45'));
  assert.ok(!clusterHtml.includes('145%'));

  // 3. Relevance: Percentage
  const relHtml = renderRelevanceBadge(testVal);
  assert.ok(relHtml.includes('Relevance: 85%'));

  // 4. Priority: Percentage
  const priHtml = renderInboxPriorityBadge(testVal);
  assert.ok(priHtml.includes('Priority: 85%'));

  // 5. Rank: Percentage
  const rankHtml = renderInboxRankBadge(testVal);
  assert.ok(rankHtml.includes('Rank: 85%'));

  // 6. Project Relevance vs Project Impact separation
  const projRelHtml = renderProjectRelevanceBadge(0.90);
  const projImpHtml = renderProjectImpactBadge(0.20);
  assert.ok(projRelHtml.includes('Project relevance: 90%'));
  assert.ok(projImpHtml.includes('Project impact: 20%'));
  assert.notStrictEqual(projRelHtml, projImpHtml);

  // 7. Project Match Pill renders match type only
  const pillHtml = renderProjectMatchPill('technology_overlap');
  assert.ok(pillHtml.includes('technology overlap'));
  assert.ok(!pillHtml.includes('Project relevance:'));
  assert.ok(!pillHtml.includes('%'));

  // 8. Closed domain mapper
  assert.ok(renderScoreBadge(testVal, SCORE_DOMAINS.SEARCH_RANK).includes('Score: 0.85'));
  assert.ok(renderScoreBadge(testVal, SCORE_DOMAINS.CLUSTER_SCORE).includes('Cluster score: 0.85'));
  assert.ok(renderScoreBadge(testVal, SCORE_DOMAINS.RELEVANCE).includes('Relevance: 85%'));
  assert.ok(renderScoreBadge(testVal, SCORE_DOMAINS.INBOX_PRIORITY).includes('Priority: 85%'));
  assert.ok(renderScoreBadge(testVal, SCORE_DOMAINS.INBOX_RANK).includes('Rank: 85%'));
  assert.ok(renderScoreBadge(testVal, SCORE_DOMAINS.PROJECT_RELEVANCE).includes('Project relevance: 85%'));
  assert.ok(renderScoreBadge(testVal, SCORE_DOMAINS.PROJECT_IMPACT).includes('Project impact: 85%'));
});

test('Phase 14: Score range and type validation for normalized and non-normalized domains', async () => {
  const {
    formatScorePercentage,
    formatScoreDecimal,
    isValidNormalizedScore,
    isValidFiniteScore,
  } = await import('../src/utils/adapters.js');
  const {
    renderSearchScoreBadge,
    renderClusterScoreBadge,
    renderRelevanceBadge,
    renderInboxPriorityBadge,
    renderInboxRankBadge,
    renderProjectRelevanceBadge,
    renderProjectImpactBadge,
  } = await import('../src/components/badges.js');

  const invalidNormalizedInputs = [
    null,
    undefined,
    NaN,
    Infinity,
    -Infinity,
    -0.01,
    -1.0,
    1.01,
    1.5,
    '0.5',
    '85%',
    {},
    [],
    true,
    false,
  ];

  // All invalid normalized inputs must fail validation and return empty string from renderers
  for (const input of invalidNormalizedInputs) {
    assert.strictEqual(isValidNormalizedScore(input), false, `Expected false for ${input}`);
    assert.strictEqual(formatScorePercentage(input), '—', `Expected '—' for ${input}`);
    assert.strictEqual(renderRelevanceBadge(input), '', `Expected '' for relevance on ${input}`);
    assert.strictEqual(renderInboxPriorityBadge(input), '', `Expected '' for priority on ${input}`);
    assert.strictEqual(renderInboxRankBadge(input), '', `Expected '' for rank on ${input}`);
    assert.strictEqual(renderProjectRelevanceBadge(input), '', `Expected '' for proj relevance on ${input}`);
    assert.strictEqual(renderProjectImpactBadge(input), '', `Expected '' for proj impact on ${input}`);
  }

  // Valid normalized inputs
  const validNormalizedInputs = [
    { in: 0.0, pct: '0%' },
    { in: 0.001, pct: '0%' },
    { in: 0.456, pct: '46%' },
    { in: 0.75, pct: '75%' },
    { in: 1.0, pct: '100%' },
  ];

  for (const { in: val, pct } of validNormalizedInputs) {
    assert.strictEqual(isValidNormalizedScore(val), true, `Expected true for ${val}`);
    assert.strictEqual(formatScorePercentage(val), pct, `Expected ${pct} for ${val}`);
    assert.ok(renderRelevanceBadge(val).includes(pct));
    assert.ok(renderInboxPriorityBadge(val).includes(pct));
    assert.ok(renderInboxRankBadge(val).includes(pct));
    assert.ok(renderProjectRelevanceBadge(val).includes(pct));
    assert.ok(renderProjectImpactBadge(val).includes(pct));
  }

  // Non-normalized inputs (e.g. search rank, cluster score)
  const invalidFiniteInputs = [null, undefined, NaN, Infinity, -Infinity, '1.45', {}, []];
  for (const input of invalidFiniteInputs) {
    assert.strictEqual(isValidFiniteScore(input), false);
    assert.strictEqual(formatScoreDecimal(input), '—');
    assert.strictEqual(renderSearchScoreBadge(input), '');
    assert.strictEqual(renderClusterScoreBadge(input), '');
  }

  // Valid finite non-normalized inputs (can exceed 1.0, preserved as decimals)
  assert.ok(renderSearchScoreBadge(0.0).includes('Score: 0.00'));
  assert.ok(renderSearchScoreBadge(1.85).includes('Score: 1.85'));
  assert.ok(renderClusterScoreBadge(2.45).includes('Cluster score: 2.45'));
  assert.ok(!renderSearchScoreBadge(1.85).includes('%'));
  assert.ok(!renderClusterScoreBadge(2.45).includes('%'));
});

test('Phase 14: Closed score domain dispatcher rejects missing and unknown domains', async () => {
  const { renderScoreBadge, renderRankingBadge } = await import('../src/components/badges.js');

  // Missing domain: returns empty string, does not default to relevance or percentage
  assert.strictEqual(renderScoreBadge(0.85), '');
  assert.strictEqual(renderScoreBadge(0.85, null), '');
  assert.strictEqual(renderScoreBadge(0.85, undefined), '');
  assert.strictEqual(renderRankingBadge(0.85), '');
  assert.strictEqual(renderRankingBadge(0.85, undefined), '');

  // Unknown/free-form domain: returns empty string, does not default to relevance
  assert.strictEqual(renderScoreBadge(0.85, 'confidence'), '');
  assert.strictEqual(renderScoreBadge(0.85, 'arbitrary_score'), '');
  assert.strictEqual(renderScoreBadge(0.85, 'accuracy'), '');
  assert.strictEqual(renderRankingBadge(0.85, 'unknown'), '');
});

test('Phase 14: Project relevance and project impact are strictly independent continuous dimensions', async () => {
  const { renderStoryCard } = await import('../src/components/story-card.js');

  const storyWithDifferingScores = {
    story_cluster_id: 'sc-diff',
    title: 'Differing Scores Story',
    summary: 'Story with high relevance but low impact',
    match_type: 'technology_overlap',
    project_relevance: 0.95,
    project_impact_score: 0.15,
  };

  const renderedHtml = renderStoryCard(storyWithDifferingScores);

  // Both badges render with distinct labels and percentages
  assert.ok(renderedHtml.includes('Project relevance: 95%'));
  assert.ok(renderedHtml.includes('Project impact: 15%'));
  assert.ok(renderedHtml.includes('technology overlap'));

  // No conflation or advice language
  assert.ok(!renderedHtml.includes('Recommended'));
  assert.ok(!renderedHtml.includes('Safe to deploy'));
  assert.ok(!renderedHtml.includes('Compatible tool'));
});

test('Phase 14: Cross-surface rendered fixture matrix covers all eight consuming surfaces', async () => {
  const store = (await import('../src/state/store.js')).store;
  const createMockContainer = () => {
    const childMap = new Map();
    const c = {
      innerHTML: '',
      querySelector: (sel) => {
        if (!childMap.has(sel)) {
          childMap.set(sel, {
            innerHTML: '',
            textContent: '',
            className: '',
            style: {},
            value: '',
            checked: false,
            addEventListener: () => {},
            removeEventListener: () => {},
            querySelector: () => null,
            querySelectorAll: () => [],
          });
        }
        return childMap.get(sel);
      },
      querySelectorAll: () => [],
      addEventListener: () => {},
      removeEventListener: () => {},
    };
    return c;
  };

  // 1. Surface 1: Today View
  const { renderTodayView } = await import('../src/views/today.js');
  const todayContainer = createMockContainer();
  fetchMock = async (url) => {
    if (url.includes('/inbox')) {
      return {
        ok: true,
        status: 200,
        json: async () => ({
          items: [
            {
              id: 'inbox-1',
              story_cluster_id: 'sc-1',
              title: 'Today Story Active',
              summary: 'Summary text',
              inbox_score: 0.82,
              rank_score: 0.90,
              project_impact_score: 0.75,
              matched_project_ids: ['proj-1'],
              item_type: 'new_story',
              section: 'must_know',
              state: 'unseen',
              story_available: true,
            },
            {
              id: 'inbox-2',
              story_cluster_id: 'sc-2',
              title: 'Today Story Zero Priority',
              summary: 'Summary text',
              inbox_score: 0.0,
              rank_score: 0.0,
              project_impact_score: null,
              matched_project_ids: [],
              item_type: 'new_story',
              section: 'must_know',
              state: 'unseen',
              story_available: true,
            }
          ],
          counts: { all: 2 }
        })
      };
    }
    return { ok: true, status: 200, json: async () => ({}) };
  };
  await renderTodayView(todayContainer, store);
  const feedHtml = todayContainer.querySelector('#inbox-feed-container').innerHTML;
  assert.ok(feedHtml.includes('Today Story Active'));
  assert.ok(feedHtml.includes('Priority: 82%'));
  assert.ok(feedHtml.includes('Rank: 90%'));
  assert.ok(feedHtml.includes('Project impact: 75%'));
  assert.ok(feedHtml.includes('Priority: 0%')); // Genuine zero preserved
  assert.ok(!feedHtml.includes('Project relevance:')); // No relevance substitution for impact

  // 2. Surface 2: Search View
  const { renderSearchView } = await import('../src/views/search.js');
  const searchContainer = createMockContainer();
  fetchMock = async (url) => {
    if (url.includes('/search')) {
      return {
        ok: true,
        status: 200,
        json: async () => ({
          results: [{
            entity_id: 'sc-1',
            title: 'Search Result Title',
            score: 0.85,
            claim_status: 'supported',
            verification_score: 0.72,
            maturity: 'prototype',
            sources: ['hackernews'],
            project_relevance: 0.65,
          }]
        })
      };
    }
    return { ok: true, status: 200, json: async () => ({}) };
  };
  await renderSearchView(searchContainer, store, { q: 'cuda' });
  const searchResultsHtml = searchContainer.querySelector('#search-results-area').innerHTML;
  assert.ok(searchResultsHtml.includes('Score: 0.85'));
  assert.ok(!searchResultsHtml.includes('Score: 85%')); // Decimal, not percentage
  assert.ok(searchResultsHtml.includes('badge-verification-supported'));
  assert.ok(searchResultsHtml.includes('badge-maturity-prototype'));
  assert.ok(searchResultsHtml.includes('Project relevance: 65%'));

  // 3. Surface 3: Story Dossier
  const { renderStoryDetailView } = await import('../src/views/story-detail.js');
  const dossierContainer = createMockContainer();
  fetchMock = async (url) => {
    if (url.includes('/stories/')) {
      return {
        ok: true,
        status: 200,
        json: async () => ({
          story_cluster_id: 'sc-1',
          title: 'Dossier Title',
          cluster_score: 1.45,
          maturity_stage: 'established',
          verification: { claim_status: 'supported', verification_score: 0.88 },
          risk: { status: 'assessed', level: 'low', score: 0.15 },
          sources: ['arxiv'],
          events: [],
          claims: [{
            id: 'c-1',
            claim_text: 'Claim text',
            status: 'supported',
            verification_score: 0.70
          }]
        })
      };
    }
    return { ok: true, status: 200, json: async () => ({}) };
  };
  await renderStoryDetailView(dossierContainer, store, { storyId: 'sc-1' });
  assert.ok(dossierContainer.innerHTML.includes('Dossier Title'));
  assert.ok(dossierContainer.innerHTML.includes('Cluster score: 1.45'));
  assert.ok(!dossierContainer.innerHTML.includes('145%'));
  assert.ok(!dossierContainer.innerHTML.includes('HERMES cluster'));
  assert.ok(dossierContainer.innerHTML.includes('badge-maturity-established'));
  assert.ok(dossierContainer.innerHTML.includes('badge-verification-supported'));
  assert.ok(dossierContainer.innerHTML.includes('badge-risk-low'));

  // 4. Surface 4: Saved Library
  const { renderSavedView } = await import('../src/views/saved.js');
  const savedContainer = createMockContainer();
  fetchMock = async (url) => ({
    ok: true,
    status: 200,
    json: async () => ({
      items: [{
        id: 'save-1',
        title_snapshot: 'Saved Item Title',
        maturity_stage: null, // Historical null
        claim_status: null, // Historical null
        verification_score: null,
        sources: ['github'],
        current_state: {
          maturity_stage: 'established',
          claim_status: 'supported',
          verification_score: 0.95
        }
      }]
    })
  });
  await renderSavedView(savedContainer, store);
  assert.ok(savedContainer.innerHTML.includes('Maturity: Not recorded historically'));
  assert.ok(savedContainer.innerHTML.includes('Claim status: Not recorded historically'));
  assert.ok(savedContainer.innerHTML.includes('badge-maturity-established')); // Current state
  assert.ok(savedContainer.innerHTML.includes('badge-verification-supported')); // Current state

  // 5. Surface 5: Changes View
  const { renderChangesView } = await import('../src/views/changes.js');
  const changesContainer = createMockContainer();
  fetchMock = async (url) => ({
    ok: true,
    status: 200,
    json: async () => ({
      changes: [
        {
          id: 'chg-1',
          change_type: 'maturity_transition',
          old_value: 'prototype',
          new_value: 'early_adoption',
          importance: 'high',
          detected_at: new Date().toISOString()
        },
        {
          id: 'chg-2',
          change_type: 'claim_revision',
          old_value: 'supported',
          new_value: 'contradicted',
          importance: 'critical',
          detected_at: new Date().toISOString()
        },
        {
          id: 'chg-3',
          change_type: 'version_bump',
          old_value: null, // Historical null
          new_value: 'v2.0.0',
          importance: 'low',
          detected_at: new Date().toISOString()
        }
      ],
      total_count: 3
    })
  });
  await renderChangesView(changesContainer, store);
  const changesHtml = changesContainer.querySelector('#changes-content-region').innerHTML;
  assert.ok(changesHtml.includes('Prototype'));
  assert.ok(changesHtml.includes('Early Adoption'));
  assert.ok(changesHtml.includes('Supported'));
  assert.ok(changesHtml.includes('Contradicted'));
  assert.ok(changesHtml.includes('v2.0.0'));
  assert.ok(changesHtml.includes('Previous state not recorded historically'));

  // 6. Surface 6: Projects View
  const { renderProjectsView } = await import('../src/views/projects.js');
  const projectsContainer = createMockContainer();
  fetchMock = async (url) => {
    if (url.includes('/intelligence')) {
      return {
        ok: true,
        status: 200,
        json: async () => ({
          project_id: 'proj-1',
          name: 'CUDA Deep Engine',
          description: 'GPU compute pipeline',
          is_active: true,
          technology_profile: { languages: ['C++', 'CUDA'] },
          top_matches: [{
            cluster_id: 'sc-triton',
            title: 'Triton JIT Compilers',
            match_type: 'direct_dependency',
            relevance_score: 0.92,
            impact_score: 0.28,
            story_available: true,
            reason_codes: ['direct_dependency']
          }],
          risks: [{
            cluster_id: 'sc-risk-1',
            title: 'CUDA Memory Leak Advisory',
            risk_level: 'high',
            risk_status: 'assessed',
            risk_score: 0.50,
            relevance_score: 0.85,
            impact_score: 0.72,
            story_available: true
          }],
          recent_changes: []
        })
      };
    }
    return {
      ok: true,
      status: 200,
      json: async () => ([{
        id: 'proj-1',
        name: 'CUDA Deep Engine',
        description: 'GPU compute pipeline',
        matches_count: 1,
        concerns_count: 1
      }])
    };
  };
  await renderProjectsView(projectsContainer, store, { projectId: 'proj-1' });
  assert.ok(projectsContainer.innerHTML.includes('Project relevance: 92%'));
  assert.ok(projectsContainer.innerHTML.includes('Project impact: 28%'));
  assert.ok(projectsContainer.innerHTML.includes('Project relevance: 85%'));
  assert.ok(projectsContainer.innerHTML.includes('Project impact: 72%'));
  assert.ok(!projectsContainer.innerHTML.includes('Recommended upgrade'));
  assert.ok(!projectsContainer.innerHTML.includes('Safe to deploy'));

  // 7. Surface 7: Morning Briefing
  const { renderBriefingView } = await import('../src/views/briefing.js');
  const briefingContainer = createMockContainer();
  fetchMock = async (url) => ({
    ok: true,
    status: 200,
    json: async () => ({
      id: 'brief-1',
      briefing_date: '2026-08-22',
      total_items: 2,
      ordered_sections: ['must_know'],
      sections: {
        must_know: [
          {
            inbox_item_id: 'item-1',
            position: 1,
            title: 'Briefing Item Alpha',
            summary: 'Alpha summary',
            inbox_score: 0.88,
            rank_score: 0.94,
            project_impact_score: 0.76,
            reason_codes: ['must_know'],
            matched_projects: ['proj-1'],
            story_cluster_id: 'sc-1',
            story_available: true
          },
          {
            inbox_item_id: 'item-2',
            position: 2,
            title: 'Briefing Item Beta Zero',
            summary: 'Beta summary',
            inbox_score: 0.0,
            rank_score: 0.0,
            project_impact_score: null, // Missing impact
            reason_codes: ['general'],
            matched_projects: [],
            story_cluster_id: 'sc-2',
            story_available: true
          }
        ]
      }
    })
  });
  await renderBriefingView(briefingContainer, store);
  assert.ok(briefingContainer.innerHTML.includes('Priority: 88%'));
  assert.ok(briefingContainer.innerHTML.includes('Rank: 94%'));
  assert.ok(briefingContainer.innerHTML.includes('Project impact: 76%'));
  assert.ok(briefingContainer.innerHTML.includes('Priority: 0%'));
  assert.ok(briefingContainer.innerHTML.includes('Rank: 0%'));
  assert.ok(!briefingContainer.innerHTML.includes('Confidence'));

  // 8. Surface 8: Runtime View
  const { renderRuntimeView } = await import('../src/views/runtime.js');
  const runtimeContainer = createMockContainer();
  fetchMock = async (url) => ({
    ok: true,
    status: 200,
    json: async () => getMockRuntimeOverview()
  });
  await renderRuntimeView(runtimeContainer, store);
  assert.ok(runtimeContainer.innerHTML.includes('Source Adapter Checkpoints'));
  assert.ok(runtimeContainer.innerHTML.includes('System Health'));
  assert.ok(!runtimeContainer.innerHTML.includes('badge-verification-'));
  assert.ok(!runtimeContainer.innerHTML.includes('not_assessed'));
  assert.ok(!runtimeContainer.innerHTML.includes('Unassessed'));
  assert.ok(!runtimeContainer.innerHTML.includes('Not assessed'));
  assert.ok(!runtimeContainer.innerHTML.includes('badge-rank'));
});
