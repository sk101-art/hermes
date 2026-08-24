# HERMES

A local-first autonomous technology intelligence, verification, and epistemic tracking engine.

---

## 1. Architecture

```text
    GitHub Repos ──┐
  GitHub Releases ─┤
            arXiv ─┤
      Hacker News ─┤
     Hugging Face ─┼──→ SourceAdapter ──→ Event ──→ Normalize ──→ Dedup ──→ Filter ──→ Rank
         OpenAlex ─┤                                                                     │
         Crossref ─┤                                                                     ▼
   Stack Exchange ─┤                                                              Accepted Events
       RSS / Atom ─┘                                                                     │
                                                                                         ▼
               Cheap Candidate Selection ───→ Direct Identifier Linking (DOI / Repo / ArXiv / HF)
                             │                               │
                             ▼                               ▼
                      Local Embeddings (CPU) ────→ Semantic Similarity (Cosine)
                             │                               │
                             ▼                               ▼
                                     Story Clusters
                                            │
                                            ├──→ Claims Extraction & Fingerprinting
                                            │          │
                                            │          ▼
                                            │    Evidence Classification & Provenance
                                            │          │
                                            │          ▼
                                            │    Independence & Verification Scoring
                                            │          │
                                            │          ▼
                                            │    Technology Maturity Assessment
                                            │
                                            ▼
                                      SQLite + FTS5
                                            │
                                            ▼
                               Top Intelligence Stories & Epistemic Tracking
```

---

## 2. Ingested Source Ecosystems

| Source | Adapter | Source Type | Default Trust | Popularity Metric |
| :--- | :--- | :--- | :--- | :--- |
| **GitHub** | `GitHubAdapter` | `code_repository` | 0.75 (+ stars) | Star count (logarithmic) |
| **GitHub Releases**| `GitHubReleasesAdapter` | `code_repository` | 0.85 | Release tag, repo reference |
| **arXiv** | `ArxivAdapter` | `research_paper` | 0.90 | Recency, DOI cross-reference |
| **Hacker News** | `HackerNewsAdapter` | `discussion` | 0.65 | Score & comment count (log) |
| **Hugging Face** | `HuggingFaceAdapter` | `model_registry` / `dataset_registry` | 0.70 | Downloads (70%) + Likes (30%) |
| **OpenAlex** | `OpenAlexAdapter` | `scholarly_index` | 0.90 | Citation count (logarithmic) |
| **Crossref** | `CrossrefAdapter` | `doi_registry` | 0.95 | References count (logarithmic) |
| **Stack Exchange** | `StackExchangeAdapter` | `developer_community` | 0.65 | Score (60%) + Answers (40%) |
| **RSS / Atom** | `RssAdapter` | `technical_publication` | 0.70 | Recency & publication feed |

---

## 3. Epistemic Verification & Technology Maturity

1. **Deterministic Claim Model:**
   - Structured claims (`Claim`) with stable content fingerprint hashes.
   - Types: `release`, `architecture`, `availability`, `scholarly_identity`, `research_result`, `performance`.
   - Distinguishes artifact facts from self-reported assertions.
2. **Evidence Graph & Provenance:**
   - Deterministic classification (`peer_reviewed_research`, `preprint`, `official_release`, `source_code`, `registry_metadata`, `community_discussion`, `developer_experience`, `technical_blog`, etc.).
   - Full provenance: Claim -> Evidence -> Event -> Source URL.
3. **Independence Scoring & Anti-Echo Penalty:**
   - Detects correlated sources, shared authors, duplicate URLs, and syndicated announcements to prevent echo amplification.
4. **Transparent Verification Scoring:**
   - Quality (35%), Independence (25%), Reproducibility (20%), Diversity (10%), Quantity (10%) minus Contradiction Penalties.
   - Conservative statuses: `unverified`, `weakly_supported`, `supported`, `strongly_supported`, `mixed`, `contradicted`.
5. **Technology Maturity Model:**
   - Stages: `concept`, `research`, `prototype`, `experimental`, `early_adoption`, `production_candidate`, `established`.

---

## 4. CLI Tools & Operational Runtime

```bash
# 1. Main Ingestion & Intelligence Radar
python -m app.main

# 2. Autonomous Background Runtime
python -m app.runtime.runner [--once] [--dry-run] [--job <job_name>]

# 3. Local API Server (FastAPI + Uvicorn)
python -m app.api.server [--port 8765]

# 4. Claims & Evidence Graph Backfill / Audit
python -m app.claims_backfill [--rebuild]
python -m app.claims_audit
python -m app.explain_claim <claim_id>

# 5. Semantic Embedding & Audit
python -m app.semantic_backfill
python -m app.semantic.audit

# 6. Real Production Data Audit
python -m scripts.audit_phase17_real_data

# 7. Frontend Bundle Verification
python -m scripts.verify_bundle_size

# 8. Browser Performance Measurement
python -m scripts.measure_phase17_browser_performance
```

---

## 5. Test Suites & Quality Gates

```bash
# Backend pytest suite (333 tests)
pytest -v

# Frontend unit & integration test suite (235 tests)
node --test frontend/tests/*.test.js

# Playwright End-to-End Suite (16 tests)
pytest tests/test_e2e_playwright.py -vv

# Bundle size verification
python scripts/verify_bundle_size.py

# Real production data audit
python scripts/audit_phase17_real_data.py
```

---

## 6. Safety & Database Immutability Rules

- Never run mutating, migration, or daemon tests against `data/tech_intel.db`.
- Always set `HERMES_DB_PATH` to an isolated temporary database for mutating operations.
- The production database SHA-256 baseline is strictly verified:
  `f2966347f86f9ecd7343683f595f5d48b7fb940324eb5d936716f8899f5d5a77`
