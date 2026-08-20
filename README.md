# HERMES

A local-first autonomous technology intelligence and verification engine.

---

## Architecture

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
                               Top Intelligence Stories
```

---

## Ingested Source Ecosystems

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

## Verification & Technology Maturity Engine (Session 5)

1. **Deterministic Claim Model:**
   - Extracts structured claims (`Claim`) with stable fingerprint hashes.
   - Distinct claim types: `release`, `architecture`, `availability`, `scholarly_identity`, `research_result`, `performance`.
   - Distinguishes artifact facts from self-reported assertions (`self_reported=True/False`).
   - Strict rule: **Claims require $\ge 1$ supporting Evidence row to be saved**.
2. **Evidence Graph & Provenance:**
   - Classifies evidence into deterministic classes (`peer_reviewed_research`, `preprint`, `official_release`, `source_code`, `registry_metadata`, `community_discussion`, `developer_experience`, `technical_blog`, etc.).
   - Full provenance tracking (`Claim` $\to$ `Evidence` $\to$ `Event` $\to$ Source URL).
3. **Independence Scoring & Echo Penalty:**
   - Detects correlated sources, shared authors, duplicate URLs, and syndicated announcements to prevent echo amplification.
4. **Transparent Verification Scoring:**
   - Computes transparent multi-factor score: Evidence Quality (35%), Independence (25%), Reproducibility (20%), Source Diversity (10%), Saturating Quantity (10%) minus Contradiction Penalties.
   - Maps to conservative claim statuses: `unverified`, `weakly_supported`, `supported`, `strongly_supported`, `mixed`, `contradicted`.
5. **Technology Maturity Model:**
   - Multidimensional assessment across Implementation, Adoption, Research, Reproducibility, and Community signals.
   - Maturity Stages: `concept`, `research`, `prototype`, `experimental`, `early_adoption`, `production_candidate`, `established`.

---

## CLI Tools & Diagnostics

```bash
# 1. Main Ingestion & Intelligence Radar
python -m app.main

# 2. Claims & Evidence Graph Backfill
python -m app.claims_backfill [--rebuild]

# 3. Claims, Evidence & Verification Audit
python -m app.claims_audit

# 4. Explain Claim & Trace Evidence Provenance
python -m app.explain_claim <claim_id>

# 5. Source Ingestion Status & Stored Event Matrix
python -m app.source_status

# 6. Semantic Embedding Backfill & Cluster Rebuilding
python -m app.semantic_backfill

# 7. Semantic Diagnostic & Similarity Recall Audit
python -m app.semantic.audit
```

---

## Configuration

- **`config/sources.yaml`**: Enable/disable sources, query terms, watch repositories, feeds, max results.
- **`config/interests.yaml`**: Technical interest tiers (high, medium, low).
- **`config/semantic.yaml`**: Local embedding model, device (`cpu`), batch size, and clustering similarity threshold (`0.78`).

---

## Setup & Running

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Run Full Test Suite

```bash
pytest
```
