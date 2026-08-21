/**
 * HERMES Canonical Semantic Display Rules & Enums
 * Authoritative mapping for backend domain models to presentation states.
 * 
 * Invariant: Null or missing inputs are ALWAYS mapped to "Not assessed" / unassessed states.
 * Never defaults to positive or invented values.
 */

// 1. Canonical Verification Statuses
export const VERIFICATION_STATUS = {
  SUPPORTED: 'supported',
  WEAKLY_SUPPORTED: 'weakly_supported',
  UNVERIFIED: 'unverified',
  CONTRADICTED: 'contradicted',
};

export const VERIFICATION_MAP = {
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
  unverified: {
    label: 'Unverified',
    cssClass: 'badge-verification-unverified',
    icon: 'helpCircle',
    description: 'Self-reported or lacking independent verification',
  },
  contradicted: {
    label: 'Contradicted',
    cssClass: 'badge-verification-contradicted',
    icon: 'alertTriangle',
    description: 'Contradictory findings or failed replication reported',
  },
  not_assessed: {
    label: 'Not assessed',
    cssClass: 'badge-verification-not_assessed',
    icon: 'helpCircle',
    description: 'Verification status has not been computed',
  },
};

/**
 * Returns semantic display model for a verification status.
 * @param {string|null} status 
 * @returns {typeof VERIFICATION_MAP.supported}
 */
export function getVerificationMeta(status) {
  if (!status || typeof status !== 'string') {
    return VERIFICATION_MAP.not_assessed;
  }
  const key = status.toLowerCase().trim();
  return VERIFICATION_MAP[key] || VERIFICATION_MAP.not_assessed;
}

// 2. Canonical Maturity Stages (All 7 stages)
export const MATURITY_STAGES = {
  PROPOSAL: 'proposal',
  PROTOTYPE: 'prototype',
  EXPERIMENTAL: 'experimental',
  EARLY_ADOPTION: 'early_adoption',
  MATURE: 'mature',
  LEGACY: 'legacy',
  DEPRECATED: 'deprecated',
};

export const MATURITY_MAP = {
  proposal: {
    label: 'Proposal',
    cssClass: 'badge-maturity-proposal',
    description: 'Conceptual design, RFC, or preprint',
  },
  prototype: {
    label: 'Prototype',
    cssClass: 'badge-maturity-prototype',
    description: 'Initial implementation or proof-of-concept',
  },
  experimental: {
    label: 'Experimental',
    cssClass: 'badge-maturity-experimental',
    description: 'Active experimentation, unstable API or early testing',
  },
  early_adoption: {
    label: 'Early Adoption',
    cssClass: 'badge-maturity-early_adoption',
    description: 'Adopted by early teams, stabilizing interface',
  },
  mature: {
    label: 'Mature',
    cssClass: 'badge-maturity-mature',
    description: 'Production-proven with stable guarantees',
  },
  legacy: {
    label: 'Legacy',
    cssClass: 'badge-maturity-legacy',
    description: 'Superseded by newer approaches, maintained for compatibility',
  },
  deprecated: {
    label: 'Deprecated',
    cssClass: 'badge-maturity-deprecated',
    description: 'End-of-life or discouraged from new deployments',
  },
  not_assessed: {
    label: 'Not assessed',
    cssClass: 'badge-maturity-not_assessed',
    description: 'Maturity stage has not been assessed',
  },
};

/**
 * Returns semantic display model for a maturity stage.
 * @param {string|null} stage 
 * @returns {typeof MATURITY_MAP.mature}
 */
export function getMaturityMeta(stage) {
  if (!stage || typeof stage !== 'string') {
    return MATURITY_MAP.not_assessed;
  }
  const key = stage.toLowerCase().trim();
  return MATURITY_MAP[key] || MATURITY_MAP.not_assessed;
}

// 3. Canonical Risk Status & Levels
export const RISK_STATUS = {
  ASSESSED: 'assessed',
  NOT_ASSESSED: 'not_assessed',
  INSUFFICIENT_DATA: 'insufficient_data',
};

export const RISK_LEVELS = {
  LOW: 'low',
  MEDIUM: 'medium',
  HIGH: 'high',
};

/**
 * Returns semantic display model for Risk state.
 * Strictly respects RiskStatus and never invents a low/medium risk default.
 * @param {string|null} status - 'assessed' | 'not_assessed' | 'insufficient_data' | null
 * @param {string|null} level - 'low' | 'medium' | 'high' | null
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
  if (normLevel === 'low') {
    return {
      label: score !== null && score !== undefined ? `Low risk (${Math.round(score * 100)}%)` : 'Low risk',
      cssClass: 'badge-risk-low',
      icon: 'shield',
      description: 'Low architectural, security, or stability risk',
    };
  }

  if (normLevel === 'medium') {
    return {
      label: score !== null && score !== undefined ? `Medium risk (${Math.round(score * 100)}%)` : 'Medium risk',
      cssClass: 'badge-risk-medium',
      icon: 'alertCircle',
      description: 'Moderate risk requiring architectural evaluation',
    };
  }

  if (normLevel === 'high') {
    return {
      label: score !== null && score !== undefined ? `High risk (${Math.round(score * 100)}%)` : 'High risk',
      cssClass: 'badge-risk-high',
      icon: 'alertTriangle',
      description: 'Elevated risk requiring active mitigation or caution',
    };
  }

  return {
    label: 'Risk: Not assessed',
    cssClass: 'badge-risk-not_assessed',
    icon: 'helpCircle',
    description: 'Risk profile is unspecified',
  };
}

// 4. Canonical Evidence Stance
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
  mentions: {
    label: 'Mentions',
    cssClass: 'badge-stance-mentions',
    description: 'Brief or tangential mention',
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
      cssClass: 'badge-stance-mentions',
      description: 'Evidence stance is unspecified',
    };
  }
  const key = stance.toLowerCase().trim();
  return EVIDENCE_STANCE_MAP[key] || {
    label: toTitleCase(key),
    cssClass: 'badge-stance-mentions',
    description: 'Evidence reference',
  };
}

function toTitleCase(str) {
  return str.replace(/[_-]/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
}
