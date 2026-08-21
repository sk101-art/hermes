/**
 * HERMES Canonical Semantic Display Rules & Enums
 * Authoritative mapping for backend domain models to presentation states.
 * 
 * Strict Canonical Schemas:
 * - Maturity (7): concept, research, prototype, experimental, early_adoption, production_candidate, established
 * - ClaimStatus (8): strongly_supported, supported, weakly_supported, mixed, contradicted, unverified, superseded, retracted
 * - EvidenceStance (3): supports, contradicts, context
 * - RiskLevel (4): critical, high, medium, low
 * - RiskStatus (3): assessed, not_assessed, insufficient_data
 * 
 * Invariant: Null or missing inputs are ALWAYS mapped to "Not assessed" / neutral unassessed states.
 * Never defaults to positive or invented values.
 */

// 1. Canonical Claim Statuses (All 8 exact backend values)
export const CLAIM_STATUS = {
  STRONGLY_SUPPORTED: 'strongly_supported',
  SUPPORTED: 'supported',
  WEAKLY_SUPPORTED: 'weakly_supported',
  MIXED: 'mixed',
  CONTRADICTED: 'contradicted',
  UNVERIFIED: 'unverified',
  SUPERSEDED: 'superseded',
  RETRACTED: 'retracted',
};

export const VERIFICATION_MAP = {
  strongly_supported: {
    label: 'Strongly Supported',
    cssClass: 'badge-verification-strongly_supported',
    icon: 'checkCircle',
    description: 'Corroborated by multiple independent primary sources and reproductions',
  },
  supported: {
    label: 'Supported',
    cssClass: 'badge-verification-supported',
    icon: 'checkCircle',
    description: 'Corroborated by primary evidence or independent reproduction',
  },
  weakly_supported: {
    label: 'Weakly Supported',
    cssClass: 'badge-verification-weakly_supported',
    icon: 'alertCircle',
    description: 'Preliminary support without independent replication',
  },
  mixed: {
    label: 'Mixed Evidence',
    cssClass: 'badge-verification-mixed',
    icon: 'alertCircle',
    description: 'Conflicting or qualified evidence reported across sources',
  },
  contradicted: {
    label: 'Contradicted',
    cssClass: 'badge-verification-contradicted',
    icon: 'alertTriangle',
    description: 'Contradictory findings or failed replication reported',
  },
  unverified: {
    label: 'Unverified',
    cssClass: 'badge-verification-unverified',
    icon: 'helpCircle',
    description: 'Self-reported or lacking independent verification',
  },
  superseded: {
    label: 'Superseded',
    cssClass: 'badge-verification-superseded',
    icon: 'clock',
    description: 'Superseded by newer findings, releases, or architectural paradigms',
  },
  retracted: {
    label: 'Retracted',
    cssClass: 'badge-verification-retracted',
    icon: 'alertTriangle',
    description: 'Formally retracted, withdrawn, or invalidated claim',
  },
  not_assessed: {
    label: 'Not assessed',
    cssClass: 'badge-verification-not_assessed',
    icon: 'helpCircle',
    description: 'Verification status has not been computed',
  },
};

/**
 * Returns semantic display model for a verification / claim status.
 * @param {string|null} status 
 * @returns {typeof VERIFICATION_MAP.supported}
 */
export function getVerificationMeta(status) {
  if (!status || typeof status !== 'string') {
    return VERIFICATION_MAP.not_assessed;
  }
  const key = status.toLowerCase().trim();
  if (VERIFICATION_MAP[key]) {
    return VERIFICATION_MAP[key];
  }
  return {
    label: toTitleCase(key) || 'Unknown',
    cssClass: 'badge-verification-not_assessed',
    icon: 'helpCircle',
    description: 'Unrecognized verification state',
  };
}

// 2. Canonical Maturity Stages (All 7 exact backend values)
export const MATURITY_STAGES = {
  CONCEPT: 'concept',
  RESEARCH: 'research',
  PROTOTYPE: 'prototype',
  EXPERIMENTAL: 'experimental',
  EARLY_ADOPTION: 'early_adoption',
  PRODUCTION_CANDIDATE: 'production_candidate',
  ESTABLISHED: 'established',
};

export const MATURITY_MAP = {
  concept: {
    label: 'Concept',
    cssClass: 'badge-maturity-concept',
    description: 'Conceptual design, preprint proposal, or architectural RFC',
  },
  research: {
    label: 'Research',
    cssClass: 'badge-maturity-research',
    description: 'Academic or industrial research paper and algorithmic formulation',
  },
  prototype: {
    label: 'Prototype',
    cssClass: 'badge-maturity-prototype',
    description: 'Proof-of-concept repository or preliminary reference implementation',
  },
  experimental: {
    label: 'Experimental',
    cssClass: 'badge-maturity-experimental',
    description: 'Active experimentation, unstable API, or early sandbox evaluation',
  },
  early_adoption: {
    label: 'Early Adoption',
    cssClass: 'badge-maturity-early_adoption',
    description: 'Adopted by early teams, stabilizing interfaces and developer tooling',
  },
  production_candidate: {
    label: 'Production Candidate',
    cssClass: 'badge-maturity-production_candidate',
    description: 'Feature-complete, undergoing staging tests and production readiness audits',
  },
  established: {
    label: 'Established',
    cssClass: 'badge-maturity-established',
    description: 'Production-proven with stable guarantees, wide adoption, and LTS support',
  },
  not_assessed: {
    label: 'Not assessed',
    cssClass: 'badge-maturity-not_assessed',
    description: 'Maturity stage has not been assessed',
  },
};

/**
 * Normalizes legacy/alternative aliases to canonical maturity values if encountered.
 * @param {string|null} val 
 * @returns {string|null}
 */
export function normalizeMaturityStage(val) {
  if (!val || typeof val !== 'string') return null;
  const v = val.toLowerCase().trim();
  const legacyAliases = {
    maturing: 'early_adoption',
    production_ready: 'established',
    stable: 'established',
    proposal: 'concept',
    mature: 'established',
  };
  if (legacyAliases[v]) return legacyAliases[v];
  if (MATURITY_MAP[v]) return v;
  return null;
}

/**
 * Returns semantic display model for a maturity stage.
 * @param {string|null} stage 
 * @returns {typeof MATURITY_MAP.established}
 */
export function getMaturityMeta(stage) {
  if (!stage || typeof stage !== 'string') {
    return MATURITY_MAP.not_assessed;
  }
  const key = stage.toLowerCase().trim();
  if (MATURITY_MAP[key]) {
    return MATURITY_MAP[key];
  }
  // Check isolated normalization alias
  const normalized = normalizeMaturityStage(key);
  if (normalized && MATURITY_MAP[normalized]) {
    return MATURITY_MAP[normalized];
  }
  return {
    label: toTitleCase(key) || 'Unknown',
    cssClass: 'badge-maturity-not_assessed',
    description: 'Unrecognized maturity stage',
  };
}

// 3. Canonical Risk Status & Levels (critical, high, medium, low)
export const RISK_STATUS = {
  ASSESSED: 'assessed',
  NOT_ASSESSED: 'not_assessed',
  INSUFFICIENT_DATA: 'insufficient_data',
};

export const RISK_LEVELS = {
  CRITICAL: 'critical',
  HIGH: 'high',
  MEDIUM: 'medium',
  LOW: 'low',
};

/**
 * Returns semantic display model for Risk state.
 * Strictly respects RiskStatus and never invents a low/medium risk default.
 * @param {string|null} status - 'assessed' | 'not_assessed' | 'insufficient_data' | null
 * @param {string|null} level - 'critical' | 'high' | 'medium' | 'low' | null
 * @param {number|null} [score] - numeric score (0.0 - 1.0)
 * @returns {{ label: string, cssClass: string, icon: string, description: string }}
 */
export function getRiskMeta(status, level, score = null) {
  // If status is explicitly unassessed or missing
  if (!status || status === 'not_assessed' || (status === 'assessed' && !level)) {
    if (status === 'insufficient_data') {
      return {
        label: 'Risk: Insufficient data',
        cssClass: 'badge-risk-insufficient_data',
        icon: 'helpCircle',
        description: 'Insufficient signals to compute reliable risk score',
      };
    }
    return {
      label: 'Risk: Not assessed',
      cssClass: 'badge-risk-not_assessed',
      icon: 'helpCircle',
      description: 'Risk profile has not been evaluated',
    };
  }

  if (status === 'insufficient_data') {
    return {
      label: 'Risk: Insufficient data',
      cssClass: 'badge-risk-insufficient_data',
      icon: 'helpCircle',
      description: 'Insufficient signals to compute reliable risk score',
    };
  }

  // Assessed with valid level
  const normLevel = String(level).toLowerCase().trim();
  const scoreSuffix = (score !== null && score !== undefined && typeof score === 'number' && !isNaN(score))
    ? ` (${Math.round(score * 100)}%)`
    : '';

  if (normLevel === 'critical') {
    return {
      label: `Critical risk${scoreSuffix}`,
      cssClass: 'badge-risk-critical',
      icon: 'alertTriangle',
      description: 'Critical severity risk: immediate security vulnerability, major breaking flaw, or project blocker',
    };
  }

  if (normLevel === 'high') {
    return {
      label: `High risk${scoreSuffix}`,
      cssClass: 'badge-risk-high',
      icon: 'alertTriangle',
      description: 'Elevated risk requiring active mitigation or architectural review',
    };
  }

  if (normLevel === 'medium') {
    return {
      label: `Medium risk${scoreSuffix}`,
      cssClass: 'badge-risk-medium',
      icon: 'alertCircle',
      description: 'Moderate risk requiring architectural evaluation',
    };
  }

  if (normLevel === 'low') {
    return {
      label: `Low risk${scoreSuffix}`,
      cssClass: 'badge-risk-low',
      icon: 'shield',
      description: 'Low architectural, security, or stability risk',
    };
  }

  return {
    label: 'Risk: Not assessed',
    cssClass: 'badge-risk-not_assessed',
    icon: 'helpCircle',
    description: 'Risk profile is unspecified',
  };
}

// 4. Canonical Evidence Stances (All 3 exact backend values)
export const EVIDENCE_STANCES = {
  SUPPORTS: 'supports',
  CONTRADICTS: 'contradicts',
  CONTEXT: 'context',
};

export const EVIDENCE_STANCE_MAP = {
  supports: {
    label: 'Supports',
    cssClass: 'badge-stance-supports',
    description: 'Evidence provides corroboration for the claim',
  },
  contradicts: {
    label: 'Contradicts',
    cssClass: 'badge-stance-contradicts',
    description: 'Evidence refutes or challenges the claim',
  },
  context: {
    label: 'Context',
    cssClass: 'badge-stance-context',
    description: 'Background or related contextual reference',
  },
};

/**
 * Returns semantic display model for Evidence stance.
 * @param {string|null} stance 
 * @returns {typeof EVIDENCE_STANCE_MAP.supports}
 */
export function getEvidenceStanceMeta(stance) {
  if (!stance || typeof stance !== 'string') {
    return {
      label: 'Unspecified',
      cssClass: 'badge-stance-context',
      description: 'Evidence stance is unspecified',
    };
  }
  const key = stance.toLowerCase().trim();
  if (EVIDENCE_STANCE_MAP[key]) {
    return EVIDENCE_STANCE_MAP[key];
  }
  // Isolated compatibility normalization aliases
  const aliases = {
    support: 'supports',
    contradiction: 'contradicts',
    refutes: 'contradicts',
    opposes: 'contradicts',
    contextual: 'context',
    neutral: 'context',
    background: 'context',
  };
  if (aliases[key] && EVIDENCE_STANCE_MAP[aliases[key]]) {
    return EVIDENCE_STANCE_MAP[aliases[key]];
  }
  return {
    label: toTitleCase(key) || 'Unspecified',
    cssClass: 'badge-stance-context',
    description: 'Evidence reference',
  };
}

export function toTitleCase(str) {
  if (!str) return '';
  return str.replace(/[_-]/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
}

export default {
  CLAIM_STATUS,
  VERIFICATION_MAP,
  getVerificationMeta,
  MATURITY_STAGES,
  MATURITY_MAP,
  getMaturityMeta,
  RISK_STATUS,
  RISK_LEVELS,
  getRiskMeta,
  EVIDENCE_STANCES,
  EVIDENCE_STANCE_MAP,
  getEvidenceStanceMeta,
};
