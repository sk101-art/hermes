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
    description: 'HERMES classifies this claim as strongly supported',
  },
  supported: {
    label: 'Supported',
    cssClass: 'badge-verification-supported',
    icon: 'checkCircle',
    description: 'HERMES classifies this claim as supported',
  },
  weakly_supported: {
    label: 'Weakly Supported',
    cssClass: 'badge-verification-weakly_supported',
    icon: 'alertCircle',
    description: 'HERMES classifies this claim as weakly supported',
  },
  mixed: {
    label: 'Mixed Evidence',
    cssClass: 'badge-verification-mixed',
    icon: 'alertCircle',
    description: 'Supporting and contradicting evidence are both present',
  },
  contradicted: {
    label: 'Contradicted',
    cssClass: 'badge-verification-contradicted',
    icon: 'alertTriangle',
    description: 'Contradicting evidence outweighs support under HERMES policy',
  },
  unverified: {
    label: 'Unverified',
    cssClass: 'badge-verification-unverified',
    icon: 'helpCircle',
    description: 'HERMES classifies this claim as unverified',
  },
  superseded: {
    label: 'Superseded',
    cssClass: 'badge-verification-superseded',
    icon: 'clock',
    description: 'Superseded by subsequent findings or updates',
  },
  retracted: {
    label: 'Retracted',
    cssClass: 'badge-verification-retracted',
    icon: 'alertTriangle',
    description: 'Formally retracted or withdrawn',
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
  if (VERIFICATION_MAP[key] && key !== 'not_assessed') {
    return VERIFICATION_MAP[key];
  }
  return {
    label: 'Unrecognized claim status',
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
    description: 'Concept-stage technology',
  },
  research: {
    label: 'Research',
    cssClass: 'badge-maturity-research',
    description: 'Research-stage technology',
  },
  prototype: {
    label: 'Prototype',
    cssClass: 'badge-maturity-prototype',
    description: 'Prototype implementation',
  },
  experimental: {
    label: 'Experimental',
    cssClass: 'badge-maturity-experimental',
    description: 'Experimental implementation',
  },
  early_adoption: {
    label: 'Early Adoption',
    cssClass: 'badge-maturity-early_adoption',
    description: 'Early adoption stage',
  },
  production_candidate: {
    label: 'Production Candidate',
    cssClass: 'badge-maturity-production_candidate',
    description: 'Production-candidate maturity',
  },
  established: {
    label: 'Established',
    cssClass: 'badge-maturity-established',
    description: 'Established maturity',
  },
  not_assessed: {
    label: 'Not assessed',
    cssClass: 'badge-maturity-not_assessed',
    description: 'Maturity stage has not been assessed',
  },
};

export function normalizeMaturityStage(val) {
  if (!val || typeof val !== 'string') return null;
  const v = val.toLowerCase().trim();
  if (MATURITY_MAP[v] && v !== 'not_assessed') return v;
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
  if (MATURITY_MAP[key] && key !== 'not_assessed') {
    return MATURITY_MAP[key];
  }
  return {
    label: 'Unrecognized maturity',
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
      description: 'Critical severity risk profile',
    };
  }

  if (normLevel === 'high') {
    return {
      label: `High risk${scoreSuffix}`,
      cssClass: 'badge-risk-high',
      icon: 'alertTriangle',
      description: 'High risk profile',
    };
  }

  if (normLevel === 'medium') {
    return {
      label: `Medium risk${scoreSuffix}`,
      cssClass: 'badge-risk-medium',
      icon: 'alertCircle',
      description: 'Moderate risk profile',
    };
  }

  if (normLevel === 'low') {
    return {
      label: `Low risk${scoreSuffix}`,
      cssClass: 'badge-risk-low',
      icon: 'shield',
      description: 'Low risk profile',
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
  unknown: {
    label: 'Unspecified',
    cssClass: 'badge-stance-unknown',
    description: 'Evidence stance is unspecified',
  },
};

/**
 * Returns semantic display model for Evidence stance.
 * Unknown stance renders neutrally with .badge-stance-unknown and label 'Unspecified'.
 * @param {string|null} stance 
 * @returns {typeof EVIDENCE_STANCE_MAP.supports}
 */
export function getEvidenceStanceMeta(stance) {
  if (!stance || typeof stance !== 'string') {
    return EVIDENCE_STANCE_MAP.unknown;
  }
  const key = stance.toLowerCase().trim();
  if (EVIDENCE_STANCE_MAP[key] && key !== 'unknown') {
    return EVIDENCE_STANCE_MAP[key];
  }
  return {
    label: 'Unspecified',
    cssClass: 'badge-stance-unknown',
    description: 'Unrecognized evidence stance',
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
