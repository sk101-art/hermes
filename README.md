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
   SQLite + FTS5
          │
          ▼
Cross-Source Intelligence
```

---

## What It Does

1. **Multi-Source Ingestion:** Ingests recent developments from **GitHub**, **arXiv**, and **Hacker News**.
2. **Unified Event Normalization:** Normalizes all sources into a single consistent `Event` model.
3. **Deterministic Deduplication:** Deduplicates by canonical ID and normalized URL.
4. **Interest Filtering:** Evaluates content against `config/interests.yaml` tiers (high, medium, low) with deterministic synonym expansion.
5. **Cross-Source Ranking:** Multi-factor scoring combining relevance, novelty, popularity, and source priors (`arXiv`: 0.90, `GitHub`: 0.75, `Hacker News`: 0.65).
6. **SQLite Storage:** Persists events in `data/tech_intel.db` with SQLite FTS5 full-text indexing.
7. **Terminal Dashboard:** Displays per-source execution summaries and top ranked cross-source developments.

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
