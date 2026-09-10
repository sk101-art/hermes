# HERMES

> A local-first technology intelligence and verification engine for discovering, clustering, and assessing developments across the software and research ecosystem.

HERMES turns fragmented public signals into ranked technology stories. It ingests repositories, releases, papers, model registries, technical discussions, scholarly metadata, and RSS feeds; then normalizes, deduplicates, clusters, and evaluates them through an evidence-backed pipeline.

## What it provides

- Configuration-driven monitoring across nine technical source ecosystems.
- Event normalization, filtering, deduplication, and ranking.
- Semantic story clustering using local sentence-transformer embeddings.
- Structured claim extraction and evidence provenance.
- Independence scoring and echo-penalty handling.
- Transparent verification statuses.
- Multidimensional technology maturity assessment.
- Local SQLite and FTS5 persistence.

## Pipeline

```text
Source adapters
      │
      ▼
Normalize → Deduplicate → Filter → Rank
      │                              │
      └──────────────► SQLite + FTS5 ◄┘
                             │
                             ▼
                 Local embeddings + clustering
                             │
                             ▼
             Claims → Evidence → Verification
                             │
                             ▼
                 Technology maturity assessment
```

## Supported sources

| Source | Signal |
| --- | --- |
| GitHub | Repositories and engineering activity |
| GitHub Releases | Versioned releases from watched projects |
| arXiv | Research papers and preprints |
| Hacker News | Technical community discussion |
| Hugging Face | Models and datasets |
| OpenAlex | Scholarly metadata |
| Crossref | DOI and publication metadata |
| Stack Exchange | Developer questions and answers |
| RSS / Atom | Configured technical publications |

Configure sources in `config/sources.yaml`.

## Verification model

HERMES distinguishes artifact facts from self-reported assertions. Claims are retained with supporting evidence and traced back to source events and URLs.

Verification considers:

- Evidence quality
- Source independence
- Reproducibility
- Source diversity
- Evidence quantity
- Contradiction penalties

Claims receive statuses such as `unverified`, `weakly_supported`, `supported`, `strongly_supported`, `mixed`, or `contradicted`.

Technology maturity is assessed across implementation, adoption, research, reproducibility, and community signals.

## Repository layout

| Path | Responsibility |
| --- | --- |
| `app/main.py` | Main ingestion and intelligence workflow |
| `app/adapters/` | Source-specific adapters |
| `app/pipeline/` | Filtering, ranking, normalization, and deduplication |
| `app/semantic/` | Embeddings, clustering, and diagnostics |
| `app/evidence/` | Claims, evidence, verification, and maturity |
| `app/storage/` | SQLite persistence |
| `config/sources.yaml` | Source adapters, queries, feeds, and limits |
| `config/interests.yaml` | Technical interest priorities |
| `config/semantic.yaml` | Embedding and clustering settings |
| `tests/` | Automated tests |

## Requirements

- Python 3.10+
- Internet access for enabled adapters
- Dependencies from `requirements.txt`
- A GitHub token for GitHub-backed ingestion
- CPU-compatible local sentence-transformer inference

## Installation

```bash
git clone https://github.com/sk101-art/hermes.git
cd hermes

python -m venv .venv
source .venv/bin/activate       # Windows: .venv\\Scripts\\activate
pip install -r requirements.txt

cp .env.example .env
```

Set the GitHub token in `.env`:

```dotenv
GITHUB_TOKEN=your_github_token
```

Review the YAML configuration before running a full ingestion session.

## Run HERMES

```bash
python -m app.main
```

The local database is written to `data/tech_intel.db`. A run prints source statistics, semantic summaries, and top intelligence stories when clustering succeeds.

## Diagnostics

```bash
python -m app.claims_backfill [--rebuild]
python -m app.claims_audit
python -m app.explain_claim <claim_id>
python -m app.source_status
python -m app.semantic_backfill
python -m app.semantic.audit
```

## Testing

```bash
pytest
```

Use fixtures or mocks for network-dependent adapter tests to keep the suite deterministic.

## Design principles

- **Evidence before confidence:** repeated claims are not automatically verified.
- **Traceability:** intelligence remains linked to its original sources.
- **Graceful degradation:** one unavailable source should not stop the entire run.
- **Local-first analysis:** persistence, search, embeddings, and scoring run locally.
- **Configuration over code:** source coverage and interests are adjustable in YAML.

## Project status

HERMES is an evolving research and engineering prototype. Source schemas, scoring weights, and maturity heuristics may change as the verification model develops.

## License

No license file is currently included. Add a license before distributing HERMES publicly.
