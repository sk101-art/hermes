# HERMES — Production Readiness & Architecture Specification

## 1. System Overview
HERMES is a local-first autonomous intelligence platform designed to ingest, deduplicate, cluster, verify, and evaluate technical developments from 9 heterogeneous source ecosystems without cloud telemetry or external state dependencies.

## 2. Core Invariants & Architectural Rules

### 2.1 Database & Storage Layer
- **SQLite Engine**: SQLite 3 with FTS5 full-text indexing, WAL journal mode, and foreign keys enabled.
- **Migration Atomicity**: All schema upgrades execute within isolated transactional blocks with `PRAGMA foreign_keys=OFF` during structural rebuilds and restored in `finally`.
- **Zero Destructive Mutation**: Upgrades never drop historical user data (notes, tags, saved items, context hashes) and never backfill fake values into historical null fields.
- **Strict Read-Only Audit**: Production auditing is performed strictly through SQLite read-only mode (`mode=ro&immutable=1`).

### 2.2 API Server Discipline
- **Route Inventory**: Authoritative dynamic OpenAPI specification exposing endpoints for Health, Search, Today, Briefings, Stories, Claims, Projects, Saved Intelligence, Changes, and Runtime Health.
- **Error Boundaries**: Standardized JSON error response models with RFC-compliant status codes (400, 404, 422, 500) and sanitized error messages.
- **Request Discipline**: Client-side RequestManager enforces query key canonicalization, in-flight deduplication, cancellation on route navigation, and strict request budgets.

### 2.3 Epistemic Verification & Semantic Signal Separation
- **Strict Separation of Concerns**: Search relevance scores, priority rankings, project match impacts, and verification scores belong to distinct mathematical domains and are never conflated or transformed to raw percentages.
- **Closed Taxonomies**: Closed vocabulary for claim statuses (`supported`, `weakly_supported`, `unverified`, `disputed`, `refuted`) and maturity stages (`concept`, `research`, `prototype`, `production`, `deprecated`).
- **No Self-Reporting Hallucination**: Unassessed entities render transparent missing indicators and are never fabricated to "supported" or "verified".

### 2.4 Performance & Accessibility
- **Bundle Budgets**: JavaScript <= 185 KB, CSS <= 70 KB, HTML <= 1 KB, Total uncompressed <= 250 KB.
- **Latency Ceilings**: Route transitions p95 < 300 ms, Search API p95 < 125 ms, Runtime API p95 < 75 ms, Runtime cold start < 175 ms.
- **DOM Stability**: Maximum DOM elements < 1500 across 50 consecutive route switches. Zero uncollected memory leaks.
- **Accessibility**: WCAG 2.2 AA compliant with zero positive tabindex, skip links, logical landmark structure, heading hierarchy, and accessible ErrorBoundary alerts.
