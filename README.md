# HERMES

A local-first autonomous technology intelligence engine.

---

## Architecture

```text
        GitHub
          │
        arXiv
          │
    Hacker News
          │
          ▼
    SourceAdapter
          │
          ▼
        Event
          │
          ▼
     Normalize
          │
          ▼
       Dedup
          │
          ▼
       Filter
          │
          ▼
        Rank
          │
          ▼
   Accepted Events
          │
          ▼
Cheap Candidate Selection ───→ Direct Identifier Linking
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

## What It Does

1. **Multi-Source Ingestion:** Ingests recent technical developments across **GitHub**, **arXiv**, and **Hacker News**.
2. **Unified Event Normalization:** Normalizes all sources into a single consistent `Event` model.
3. **Deterministic Deduplication:** Deduplicates by canonical ID and normalized URL.
4. **Interest Filtering:** Evaluates content against `config/interests.yaml` tiers (high, medium, low) with deterministic synonym expansion.
5. **Cross-Source Ranking:** Multi-factor scoring combining relevance, novelty, popularity, and source priors (`arXiv`: 0.90, `GitHub`: 0.75, `Hacker News`: 0.65).
6. **Local Semantic Clustering (Session 3):**
   - Direct deterministic identifier resolution (cross-linking discussions directly to referenced GitHub repos and arXiv papers).
   - Local CPU embeddings using `sentence-transformers/all-MiniLM-L6-v2`.
   - Embeddings stored as float32 binary BLOBs in SQLite with caching to prevent redundant computation.
   - Bounded candidate generation avoiding $O(N^2)$ comparisons.
   - Cross-source story clustering and cluster ranking.
   > **Note:** Story clustering groups events that discuss the same underlying development. It is an attention and synthesis layer; claim and truth verification will be implemented in future sessions.
7. **SQLite Storage:** Persists events, embeddings, clusters, and relationships in `data/tech_intel.db` with SQLite FTS5 support.
8. **Terminal Intelligence Radar:** Displays source summaries, semantic clustering statistics, and top ranked cross-source intelligence stories with supporting events.

---

## Configuration

- **`config/sources.yaml`**: Enable/disable sources, query terms, max results.
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

### 3. Run Pipeline

```bash
python -m app.main
```

### 4. Run Unit Tests

```bash
pytest
```
