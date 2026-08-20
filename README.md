# HERMES

A local-first autonomous technology intelligence engine.

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
                                            ▼
                                      SQLite + FTS5
                                            │
                                            ▼
                               Top Intelligence Stories
```

---

## Ingested Source Ecosystems (Session 4)

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

## What It Does

1. **Broad Multi-Source Ingestion:** Ingests research, repositories, official releases, models, datasets, scholarly citations, developer discussions, and technical blogs across 9 source streams.
2. **Unified Event Normalization:** Normalizes all sources into a single consistent `Event` model with normalized DOIs, citation counts, and rich provenance metadata.
3. **Deterministic Deduplication & Cross-Linking:**
   - Precedence given to deterministic artifact identities (DOI, arXiv ID, GitHub repo, HF repo, Stack Exchange question ID).
   - Cross-links preprints $\leftrightarrow$ peer-reviewed DOI publications $\leftrightarrow$ open-source code repositories $\leftrightarrow$ models $\leftrightarrow$ discussions.
4. **Interest Filtering:** Evaluates content against `config/interests.yaml` tiers (high, medium, low) with deterministic synonym expansion.
5. **Calibrated Ranking:** Source-specific trust priors and logarithmic popularity scoring.
6. **Local Semantic Clustering:**
   - Bounded candidate generation avoiding $O(N^2)$ comparisons.
   - Local CPU embeddings using `sentence-transformers/all-MiniLM-L6-v2`.
   - Embeddings stored as float32 binary BLOBs in SQLite with caching.
   - Cross-source story clustering and cluster ranking.
7. **SQLite Storage:** Persists events, embeddings, clusters, and relationships in `data/tech_intel.db` with SQLite FTS5 support.
8. **Terminal Intelligence Radar:** Displays source summaries, semantic clustering statistics, and top ranked cross-source intelligence stories with supporting events.

---

## CLI Tools & Diagnostics

```bash
# 1. Main Ingestion & Intelligence Radar
python -m app.main

# 2. Source Ingestion Status & Stored Event Matrix
python -m app.source_status

# 3. Semantic Embedding Backfill & Cluster Rebuilding
python -m app.semantic_backfill

# 4. Semantic Diagnostic & Similarity Recall Audit
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

### 2. Configure Environment (Optional)

Copy `.env.example` to `.env`:

```bash
cp .env.example .env
```

Add your optional GitHub token:

```ini
GITHUB_TOKEN=ghp_your_token_here
```

### 3. Run Test Suite

```bash
pytest
```
