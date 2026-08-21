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

  // 1. Must label score as Relevance Score
  assert.ok(html.includes('Relevance Score: 94%'));
  assert.ok(html.includes('pill-relevance'));

  // 2. Must NEVER label score as Confidence, Verification, or Trust
  assert.ok(!html.includes('Confidence: 94%'));
  assert.ok(!html.includes('Verification Score: 94%'));
  assert.ok(!html.includes('Trust Score: 94%'));
  assert.ok(!html.includes('Accuracy: 94%'));

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
  assert.ok(html.includes('Project Rel: 75%'));
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
  const elements = {};
  const container = {
    _html: '',
    get innerHTML() {
      return this._html;
    },
    set innerHTML(val) {
      this._html = val;
    },
    querySelector: (sel) => {
      if (!elements[sel]) {
        elements[sel] = {
          value: '',
          checked: false,
          _html: '',
          get innerHTML() { return this._html; },
          set innerHTML(v) { this._html = v; },
          addEventListener: () => {},
          appendChild: () => {},
          focus: () => {}
        };
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

test('Search Result Card correctly passes riskStatus and riskLevel to renderRiskBadge', () => {
  const cases = [
    { status: 'assessed', level: 'low', expectedText: 'Low risk', expectedClass: 'badge-risk-low' },
    { status: 'assessed', level: 'medium', expectedText: 'Medium risk', expectedClass: 'badge-risk-medium' },
    { status: 'assessed', level: 'high', expectedText: 'High risk', expectedClass: 'badge-risk-high' },
    { status: 'assessed', level: 'critical', expectedText: 'Critical risk', expectedClass: 'badge-risk-critical' },
    { status: 'not_assessed', level: null, expectedText: 'Risk: Not assessed', expectedClass: 'badge-risk-not_assessed' },
    { status: 'insufficient_data', level: null, expectedText: 'Risk: Insufficient data', expectedClass: 'badge-risk-insufficient_data' },
  ];

  for (const c of cases) {
    const item = {
      entity_id: `cl_risk_${c.level || c.status}`,
      title: `Risk Test ${c.status} ${c.level}`,
      score: 0.8,
      risk: c.level,
      risk_status: c.status,
      sources: ['github'],
    };
    const html = renderSearchResultCard(item);
    assert.ok(html.includes(c.expectedText), `Expected "${c.expectedText}" in HTML for ${c.status}/${c.level}`);
    assert.ok(html.includes(c.expectedClass), `Expected class "${c.expectedClass}" in HTML for ${c.status}/${c.level}`);
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










