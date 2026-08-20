# Zero-Cost Autonomous AI & Engineering Intelligence Engine

## The architecture I would actually build

Your idea should **not** be implemented as a “news bot that searches the web every morning.” That would eventually become noisy, expensive, repetitive, and difficult to trust.

The system should instead be an **autonomous technical-intelligence engine** with persistent memory and evidence tracking.

Its purpose is:

> **Continuously discover potentially important technical developments, connect them to evidence and developer experience, decide how credible and relevant they are, relate them to your own projects, remember what it has already seen, and surface only the changes worth your attention.**

As of August 20, 2026, MCP is suitable as the agent-facing integration layer because Antigravity supports MCP natively, including custom MCP servers, remote servers, and workspace configuration. The official MCP project also maintains a Registry specifically for discovering published MCP servers. citeturn19view1turn19view0turn21search14

I would therefore use this architecture:

```text
                           THE INTERNET
                                │
       ┌────────────────────────┼─────────────────────────┐
       │                        │                         │
   RESEARCH                 ENGINEERING              COMMUNITY
       │                        │                         │
 arXiv/OpenAlex            GitHub/GitLab            Hacker News
 Crossref/PubMed           Hugging Face             Stack Overflow
 OpenReview                PyPI/npm                 Lobsters
 Zenodo                    Docs/releases            Fediverse
 Semantic Scholar          Cloud updates            YouTube
       │                        │                         │
       └────────────────────────┼─────────────────────────┘
                                │
                      SOURCE ADAPTER LAYER
                  API / RSS / MCP / OAI / Git
                                │
                                ▼
                     ┌─────────────────────┐
                     │    EVENT INBOX      │
                     │ Raw discoveries     │
                     └─────────┬───────────┘
                               │
                    normalize + deduplicate
                               │
                               ▼
                    ┌─────────────────────┐
                    │ RELEVANCE FILTER    │
                    │ cheap rules first   │
                    │ embeddings second   │
                    └─────────┬───────────┘
                               │
                               ▼
                    ┌─────────────────────┐
                    │ EVIDENCE EXPANDER   │
                    │ paper → repo →      │
                    │ benchmark → issues  │
                    │ discussion → docs   │
                    └─────────┬───────────┘
                               │
                               ▼
                    ┌─────────────────────┐
                    │ CLAIM VERIFICATION  │
                    │ Evidence graph      │
                    │ Contradictions      │
                    │ Replications        │
                    └─────────┬───────────┘
                               │
                               ▼
                  ┌──────────────────────────┐
                  │ LOCAL INTELLIGENCE MODEL │
                  │ Qwen3:4B / embeddings    │
                  └────────────┬─────────────┘
                               │
                ┌──────────────┴───────────────┐
                │                              │
                ▼                              ▼
       PROJECT RELEVANCE                DAILY RADAR
       /context/projects                Morning digest
                │                       alerts/followups
                └──────────────┬───────────────┘
                               │
                               ▼
                      ┌─────────────────┐
                      │  TECH-RADAR MCP │
                      └────────┬────────┘
                               │
                               ▼
                     ANTIGRAVITY / UI
```

The key architectural decision is this:

**Do not permanently attach twenty or thirty third-party MCP servers directly to Antigravity.**

Instead, build **one local MCP server of your own**, perhaps called:

```text
tech-radar-mcp
```

or:

```text
sentinel-mcp
```

That MCP is the controlled interface between Antigravity and your intelligence database.

Internally, Sentinel can use APIs, RSS, OAI-PMH, GitHub endpoints, package registries, and carefully selected MCP servers.

Externally, Antigravity sees only a small number of safe tools:

```text
daily_digest()
get_breaking_signals()
search_intelligence()
explain_evidence(item_id)
get_related_discussion(item_id)
star_item(item_id)
dismiss_item(item_id)
get_project_recommendations(project)
compare_technologies(a, b)
get_source_health()
```

This architecture is also substantially safer. The MCP project's own reference repository explicitly warns that its reference implementations are educational rather than automatically production-safe, while current MCP security guidance recommends isolation, least privilege, filesystem restrictions and sandboxing around potentially dangerous local MCP processes. citeturn19view0turn20view8

There is another important conceptual distinction:

> **Your notification history should expire. Your intelligence memory should not.**

Suppose you receive:

```text
August 20:
[HOT] New vLLM scheduling optimization
[NEW] NVIDIA inference kernel
[RESEARCH] KV-cache compression method
```

Those cards can disappear from the “Today” screen on August 21.

But their internal IDs remain in the database.

Otherwise the engine will discover the same thing next week and excitedly tell you it is “new” again.

A good lifecycle is:

```text
Raw discovery          retained 30–90+ days
Canonical metadata     retained indefinitely
Daily notification     24 hours
Starred item           indefinitely
Evidence relationships indefinitely
Full downloaded text   cache selectively
```

That gives you exactly the interface behavior you described without destroying the system's memory.

And a starred technology becomes something better than a bookmark.

For example:

```text
★ FlashInfer
   │
   ├── new release detected
   ├── paper referencing it detected
   ├── major benchmark detected
   ├── GitHub issue about RTX 30-series detected
   └── alternative implementation detected
```

The system can then notify you **weeks later when the evidence around something you starred changes**.

That is much more useful than a news feed.

## The MCP and source ecosystem worth integrating

I researched the current MCP ecosystem rather than assuming every useful source has an official MCP. The official MCP Registry is now the authoritative discovery location for published servers; importantly, being registered does **not** mean a server has been security-audited or that its upstream API is unlimited. citeturn19view0turn21search14

There is also a major distinction between:

**MCP package is free**  
and  
**underlying service can be queried without limits**.

For example, GitHub has an official MCP server, but authenticated REST requests generally have a 5,000-request-per-hour personal limit. Stack Exchange defaults to 10,000 requests/day. OpenAlex has a generous free budget, but it is still a budget. arXiv explicitly asks legacy API/RSS/OAI clients to stay at one request every three seconds. Hacker News is unusually attractive because its official API currently states that there is no rate limit. citeturn20view4turn20view5turn20view2turn20view6turn20view3

So “zero-cost unlimited” is best achieved through **incremental ingestion, caching and feed consumption**, rather than trying to brute-force unlimited searches.

### MCPs I would seriously consider

| MCP / connector | What you gain | Cost classification | Reliability role | My decision |
|---|---|---:|---|---|
| **arXiv MCP — `io.github.cyanheads/arxiv-mcp-server`** | Search, paper metadata, full-text access | Free/community; arXiv limits apply | Primary research | **CORE** |
| **OpenAlex MCP — `io.github.cyanheads/openalex-mcp-server`** | Huge scholarly graph, works/authors/citations | Free allowance | Evidence/citation graph | **CORE** |
| **Paper MCP — `io.github.MCPServings/paper-mcp`** | arXiv + Semantic Scholar + OpenAlex; versions also expose medical literature | Free OSS; upstream limits | Meta research connector | **CORE/backup** |
| **Scholar MCP — `io.github.pvliesdonk/scholar-mcp`** | Semantic Scholar literature/citations/PDF tooling | Free/community, API limits | Research expansion | Useful |
| **PubMed MCP — `io.github.pipeworx-io/pubmed`** | NCBI/PubMed | Free public API | Biomedical verification | **CORE for you** |
| **Crossref MCP — `io.github.pipeworx-io/crossref`** | DOI metadata and scholarly relationships | Free public API | Metadata verification | **CORE** |
| **ARIA MCP — `io.github.pkotecha-eng/aria-mcp-server`** | PubMed + clinical trials style discovery | Community | Healthcare intelligence | Useful |
| **openFDA MCP — `io.github.cyanheads/openfda-mcp-server`** | FDA drugs/devices/recalls | Public data | Healthcare evidence | Optional/core for medical projects |
| **OpenArx MCP** | Scientific/engineering information | Community | Additional discovery | Experimental |
| **scite MCP** | Citation-context based evidence | Service-dependent | Verification | Don't make it zero-cost core |
| **GitHub official MCP — `io.github.github/github-mcp-server`** | Repositories, issues, PRs, workflows | GitHub Free compatible; API quotas | Real-world implementation | **CORE** |
| **GitLab official MCP — `com.gitlab/mcp`** | GitLab project intelligence | Free where account/API permits | Implementation | **CORE secondary** |
| **Hugging Face official MCP — `co.huggingface/hf-mcp-server`** | Models, datasets, Spaces/Gradio ecosystem | Free account with rate limits | AI adoption | **CORE** |
| **Stack Overflow MCP — `com.stackoverflow.mcp/mcp`** | Technical Q&A | Free API quotas | Developer evidence | **CORE** |
| **Hacker News MCP — `io.github.cyanheads/hn-mcp-server`** | New/top feeds, threads/users/search | Free | Community signal | **CORE** |
| **HN Tech Signal MCP** | Hacker News + arXiv + Lobste.rs | Free/community | Cross-community discovery | Very useful |
| **Microsoft Learn MCP** | Current Microsoft technical documentation | Free access | Documentation truth | **CORE if relevant** |
| **Context7 MCP** | Version-aware library documentation | Free personal use subject to limits | Stack verification | **CORE** |
| **Azure Updates MCP** | Azure update feed intelligence | Community/free | Cloud changes | Useful |
| **ActivityPub MCP** | Fediverse / Mastodon-style community sources | OSS/community | Weak/community evidence | Optional |
| **YouTube Transcript MCP** | Technical talk/video transcripts | OSS/community | Expert commentary | Optional |
| **Multi-engine local WebSearch MCP** | Broad fallback discovery | Community/local | Discovery only | Sandbox |
| **MCP Registry MCP** | Search for newly available MCP servers themselves | Public discovery | Meta-discovery | **Very useful** |
| **Filesystem reference MCP** | Safely expose chosen context folders | Official reference | Project context | **CORE concept** |
| **Git reference MCP** | Local Git repository inspection | Official reference | Project analysis | Useful |
| **Fetch reference MCP** | Retrieve web resources | Official reference | Fallback acquisition | Useful |
| **Memory reference MCP** | Persistent knowledge graph example | Official reference | Architectural inspiration | Don't use as main DB |
| **Time reference MCP** | Time-zone tools | Official reference | Scheduling/context | Minor |

The arXiv, OpenAlex and Hacker News community servers above are currently present in the official MCP Registry; the HN Tech Signal server specifically describes itself as combining Hacker News, arXiv and Lobste.rs for technical/AI signals. citeturn21search1turn21search2turn21search15

Paper MCP is particularly interesting because its current Registry metadata describes search across arXiv, Semantic Scholar and OpenAlex, with variants incorporating PubMed/Europe PMC and citation-graph capabilities. citeturn21search3

The official GitHub, GitLab, Hugging Face and Stack Overflow MCP entries are also currently registered. citeturn22search1turn22search2turn22search7turn22search11

The official MCP project itself currently exposes reference Fetch, Filesystem, Git, Memory, Sequential Thinking and Time implementations. The project's older GitHub, GitLab, Google Drive, PostgreSQL, Redis, SQLite and Puppeteer reference servers have been moved to an archived area because the project now points users toward maintained Registry servers instead. citeturn19view0

### The important sources that should not require MCP

Here I would be deliberately clever.

**MCP is an interface, not a religion.**

It is wasteful to run an MCP process merely to parse an RSS feed.

Many of your strongest sources should therefore be **native adapters inside Sentinel**, while Sentinel itself is the MCP server.

That gives you:

```text
Internet source
      ↓
simple Python adapter
      ↓
Sentinel database
      ↓
your MCP
      ↓
Antigravity
```

For research, use:

| Source | Acquisition method | What Sentinel watches |
|---|---|---|
| arXiv | RSS + OAI-PMH + API | New papers, revisions, categories, authors |
| OpenReview | API | Submissions, reviews, author replies, decisions |
| OpenAlex | REST | Related works, references, citations, authors |
| Crossref | REST | DOI metadata, publication changes |
| PubMed / NCBI | E-utilities | Biomedical papers, updates |
| Europe PMC | REST | Biomedical papers/full-text metadata |
| Semantic Scholar | API through adapter/MCP | Citations and related papers |
| Zenodo | REST/OAI-PMH | Research artifacts, datasets, software |
| Hugging Face Papers | HF connector | Papers gaining ML ecosystem interest |

OpenReview exposes APIs for notes and conference data including submission/review-oriented content. citeturn18search0turn18search8 Zenodo exposes published-record search and OAI-PMH/metadata mechanisms alongside its REST API. citeturn18search3

arXiv actually encourages API-based discovery use cases, but asks clients of its API/RSS/OAI services to remain under one request every three seconds and one connection at a time. That makes **daily/incremental feed ingestion** a much better design than constantly querying dozens of keywords. citeturn20view6

PubMed's NCBI E-utilities allows up to three requests per second without an API key and ten requests per second with a free key by default. Again, this is easily sufficient for your personal incremental-monitoring engine. citeturn20view7

OpenAlex is particularly valuable here. It currently states that its data is free, basic API access can operate without a key, and a free key raises the available budget tenfold; it nevertheless remains quota-based, so use it for **evidence expansion after initial discovery**, not as your brute-force crawler. citeturn20view2

### Engineering ecosystem sources

For engineering developments, monitor the event stream surrounding the technology, not merely articles containing your keywords.

Your repository watchlist should eventually include ecosystems such as:

```text
AI / inference
├── PyTorch
├── TensorFlow
├── JAX
├── vLLM
├── SGLang
├── llama.cpp
├── Triton
├── ONNX
├── TensorRT / TensorRT-LLM
├── Transformers
├── PEFT
├── bitsandbytes
├── DeepSpeed
└── FlashAttention-related projects

Compiler / optimization
├── LLVM
├── MLIR
├── GCC
├── Triton
├── TVM
├── XLA
├── IREE
└── CUDA compiler/tooling

Data / storage
├── SQLite
├── DuckDB
├── PostgreSQL
├── ClickHouse
├── RocksDB
├── Redis
├── Apache Arrow
├── Parquet
├── Apache Iceberg
├── Ceph
└── MinIO

AI infrastructure
├── Kubernetes AI tooling
├── Ray
├── MLflow
├── BentoML
├── ONNX Runtime
├── Hugging Face ecosystems
└── serving runtimes
```

You don't need a unique MCP for every project. Use GitHub's MCP/API to monitor repositories, releases, issues, PRs and discussions centrally. GitHub's official MCP currently exposes repository/project functionality, while authenticated REST access for ordinary users is generally capped at 5,000 requests per hour—far beyond what a carefully incremental personal monitor should need. citeturn22search1turn20view4

PyPI is especially easy: it officially publishes a **new-packages RSS feed, latest-updates RSS feed and per-project release feeds**, making it almost ideal for your architecture. citeturn18search1

npm exposes its public registry for package metadata, though use remains subject to npm's service terms, so you should retrieve packages you're tracking rather than indiscriminately crawling the entire registry. citeturn18search2

### Primary industry intelligence

You should additionally maintain a source registry of primary technical publishers:

```text
AI labs
OpenAI
Google DeepMind / Google Research
Anthropic
Meta AI
Microsoft Research
Apple Machine Learning Research
NVIDIA Research

Infrastructure
NVIDIA Technical Blog
AMD / ROCm
Intel engineering
AWS engineering / ML
Google Cloud
Microsoft Azure
Cloudflare
Databricks

Open-source ecosystem
PyTorch
TensorFlow
JAX
Hugging Face
LLVM
MLIR
Apache projects
Linux/kernel ecosystem
database project blogs
```

These are **primary announcement sources**, but they are not automatically high-confidence evidence.

For example:

```text
Company says:
"Our new system is 4× faster."

Sentinel should NOT output:
"New system is 4× faster."

It should output:

CLAIM
Vendor reports up to 4× improvement.

STATUS
Promising / not independently replicated.

EVIDENCE
✓ technical report
✓ source code
? independent benchmark
? deployment evidence

COMMUNITY
19 relevant developer discussions detected.

YOUR PROJECT
Possibly relevant to project/inference-engine because ...
```

That subtle difference is where your engine becomes useful.

## The source-by-source filtering and verification intelligence

The most important requirement you added is:

> “not just search in the sources, but even if sources are providing something else it must consider.”

Correct.

A conventional search system works like this:

```text
query "LLM optimization"
        ↓
search everything
        ↓
results
```

I would instead design Sentinel around **events**.

Each source has a native behavior.

### Different sources should produce different signals

| Source | Don't merely search for | Continuously observe |
|---|---|---|
| **arXiv** | keywords | new category submissions, revisions, authors, citations |
| **OpenReview** | paper names | submissions, public reviews, author responses, decisions |
| **OpenAlex** | keywords | citation relationships, related works, author activity |
| **GitHub** | repository names | releases, tags, issue spikes, PRs, discussions, activity |
| **Hugging Face** | model names | newly updated models/datasets/Spaces, model cards |
| **PyPI** | packages | new packages, releases, project-specific changes |
| **npm** | packages | releases and dependency changes |
| **Stack Overflow** | search results | new questions, score/answer evolution |
| **Hacker News** | search results | new/top/show stories, comment growth and linked URLs |
| **Lobste.rs** | keywords | new technical discussions |
| **YouTube** | titles | transcripts from technical channels/talks |
| **Vendor blogs** | articles | release notes, docs, benchmark claims |
| **MCP Registry** | known MCP names | newly registered/updated MCP servers |
| **Your repositories** | files | dependency changes and new project requirements |

HN is particularly inexpensive as a raw event source because its official API currently states there is no rate limit. citeturn20view3

Stack Exchange is also practical for a personal monitor: its API defaults to a 10,000-request daily quota but explicitly asks applications to honor `backoff` values and avoid repeating equivalent requests more often than once per minute. citeturn20view5

### Everything becomes one canonical Signal

Every adapter should output the same internal structure:

```python
Signal {
    id
    source_id
    source_type

    canonical_url
    canonical_identifier

    title
    text
    authors
    organization

    event_type
    discovered_at
    published_at
    updated_at

    topics[]
    entities[]
    technologies[]

    primary_artifact
    related_repo
    related_paper

    engagement_metrics
    source_metadata

    project_matches[]
}
```

Then the rest of the application does not care whether the original input was:

```text
arXiv XML
GitHub JSON
HN JSON
RSS
Stack Exchange API
MCP result
HTML release notes
```

That is essential for scalability.

### Deduplication must happen before AI

Imagine this one announcement:

```text
New inference engine X
```

Within hours Sentinel might encounter:

```text
vendor blog
GitHub repository
arXiv paper
Hacker News submission
Reddit discussion
YouTube review
Stack Overflow question
news article
Hugging Face integration
```

Those should **not** become nine news cards.

They become:

```text
Technology Event #4827
│
├── Primary announcement
├── Paper
├── Repository
├── Package
├── HN discussion
├── Developer questions
├── Benchmark
└── Videos
```

Use multiple duplicate keys:

```text
DOI
arXiv ID
repository URL
package name
normalized canonical URL
exact title hash
fuzzy title similarity
embedding similarity
linked artifacts
```

Only after this clustering should an LLM see the event.

### Build an Evidence Graph, not a pile of summaries

For an interesting claim:

```text
"Technique X reduces KV-cache memory by 60%"
```

Sentinel expands outward:

```text
                    CLAIM
                      │
       ┌──────────────┼──────────────┐
       │              │              │
     PAPER          CODE         BENCHMARKS
       │              │              │
   citations       issues         independent?
       │              │              │
       └──────────────┼──────────────┘
                      │
                 COMMUNITY
          ┌───────────┼───────────┐
          │           │           │
         HN          GitHub      StackOverflow
```

Then it judges **the claim**, not merely the webpage.

### I would use this evidence hierarchy

Your original intuition—papers above developer chatter—is good, but one modification is critical:

> **A paper is evidence that researchers obtained a result. It is not automatically evidence that the result has been independently proven.**

I would classify evidence like this:

| Tier | Evidence | Interpretation |
|---|---|---|
| **A+** | Peer-reviewed evidence + independent replication / multiple independent evaluations | Highly substantiated |
| **A** | Strong paper + released methodology/code/data | Strong primary evidence |
| **A−** | High-quality preprint with reproducible artifacts | Promising research |
| **B+** | Independent benchmarks or production reproduction | Strong engineering evidence |
| **B** | Official technical docs + mature implementation | Strong implementation evidence |
| **C** | GitHub issues/discussions, Stack Overflow, expert engineering analysis | Developer reality check |
| **D** | Vendor blog / launch announcement | Primary claim, not independent evidence |
| **E** | News article, social media discussion, unsupported benchmark graphic | Discovery signal only |

Crossref, OpenAlex and PubMed are therefore **verification/infrastructure sources**, not necessarily discovery-only sources, while OpenReview adds particularly valuable review and decision context around participating venues. citeturn20view2turn18search0turn20view7

### Never produce a binary “true / false” for emerging research

Use statuses such as:

```text
VERIFIED / REPLICATED

STRONG PRIMARY EVIDENCE

PROMISING — NOT YET REPLICATED

EARLY IMPLEMENTATION EVIDENCE

MIXED RESULTS

COMMUNITY SIGNAL ONLY

VENDOR CLAIM ONLY

CONTRADICTED

RETRACTED / CORRECTED

INSUFFICIENT EVIDENCE
```

Then an item could look like:

```text
────────────────────────────────────────────
PagedAttention variant for low-VRAM inference
────────────────────────────────────────────

Relevance to you       94 / 100
Evidence maturity      77 / 100
Independent support    64 / 100
Community adoption     81 / 100
Novelty                72 / 100

STATUS:
Strong primary evidence; partial independent validation

Why it matters:
Could reduce VRAM pressure in inference workloads similar
to Project: local-medical-assistant.

Evidence:
✓ technical paper
✓ implementation
✓ independent benchmark
✓ 3 implementation projects
△ unresolved performance issue on Windows
? limited RTX 3050-specific evidence

Recommended action:
STAR / TEST / IGNORE

[★ Save] [Evidence] [Developer discussion]
```

### Separate relevance from truth

Do **not** combine everything into one “AI confidence” score.

Maintain:

```text
evidence_score
relevance_score
novelty_score
adoption_score
freshness_score
risk_score
```

Then digest ranking can use something such as:

```text
rank =
    0.38 * relevance
  + 0.25 * evidence
  + 0.15 * novelty
  + 0.12 * adoption
  + 0.10 * freshness
  - risk_penalty
```

But the UI continues showing evidence separately.

A Hacker News story could therefore be:

```text
Relevance: 95
Evidence: 28
```

while a peer-reviewed compiler paper could be:

```text
Relevance: 82
Evidence: 91
```

That's exactly the distinction you want.

### Source-specific scoring

Each source adapter should carry its own configuration.

For example:

```yaml
id: arxiv

kind: research
transport: api

discovery:
  mode:
    - category_feed
    - watch_entities
    - targeted_search

poll_interval: 6h

rate_policy:
  minimum_delay_ms: 3000

evidence:
  base_quality: high
  independence: primary

events:
  - new_submission
  - revision

dedupe:
  - arxiv_id
  - doi
  - title_hash
```

The 3,000 ms arXiv delay is consistent with arXiv's explicit one-request-per-three-seconds rule. citeturn20view6

GitHub instead gets:

```yaml
id: github

kind: implementation
transport: api

events:
  - release
  - tag
  - issue
  - pull_request
  - discussion
  - repository_activity

metrics:
  - stars
  - forks
  - contributors
  - issue_velocity
  - release_frequency

evidence:
  base_quality: medium_high
  interpretation: implementation_evidence
```

Stack Overflow:

```yaml
id: stackoverflow

kind: developer_community

events:
  - question
  - answer
  - accepted_answer
  - score_change

evidence:
  base_quality: medium
  interpretation: developer_experience

signals:
  accepted_answer_bonus: true
  highly_voted_bonus: true
```

Hacker News:

```yaml
id: hackernews

kind: community

feeds:
  - new
  - top
  - best
  - show

evidence:
  base_quality: low
  interpretation: community_signal_only

purpose:
  - discover emerging technology
  - discover expert discussion
  - locate linked primary evidence
```

This means **the content of Hacker News never beats a paper simply because it received 1,000 points**.

That is a key anti-hype feature.

## Project-context intelligence and the technology watch graph

This may ultimately become the most valuable part of the system.

Create:

```text
sentinel/
│
├── context/
│   └── projects/
│       ├── parkinsons-detection/
│       │   ├── README.md
│       │   ├── requirements.txt
│       │   ├── context.md
│       │   └── constraints.yaml
│       │
│       ├── compiler-optimization/
│       │   ├── README.md
│       │   ├── pyproject.toml
│       │   ├── context.md
│       │   └── constraints.yaml
│       │
│       └── platelet-detection/
│           ├── README.md
│           └── ...
│
├── data/
├── sources/
└── ...
```

The user-provided `context.md` can be very simple:

```markdown
# Project

Real-time medical-image segmentation.

## Problem

Segment platelets in microscopy images.

## Current stack

PyTorch
YOLO
OpenCV
CUDA

## Constraints

RTX 3050
16 GB RAM

## Goals

Improve small-object recall.
Reduce inference latency.
Reduce VRAM usage.
Find interpretable approaches.
```

But Sentinel should **also inspect machine-readable dependency files automatically**:

```text
requirements.txt
pyproject.toml
environment.yml
package.json
Cargo.toml
go.mod
Dockerfile
docker-compose.yml
CMakeLists.txt
*.csproj
```

Then construct a **Technology Watch Graph**.

Example:

```text
Project
"Platelet Detection"
       │
       ├── computer vision
       │     ├── segmentation
       │     ├── detection
       │     └── small objects
       │
       ├── PyTorch
       │     ├── torch.compile
       │     ├── CUDA
       │     ├── Triton
       │     └── ONNX
       │
       ├── hardware
       │     └── RTX 3050
       │
       └── constraints
             ├── low VRAM
             ├── inference speed
             └── explainability
```

Sentinel then creates **derived interests** that you never manually specified:

```text
TensorRT
mixed precision
quantization
kernel fusion
memory-efficient attention
structured pruning
ONNX Runtime
CUDA graph optimization
small-object augmentation
distillation
compiler-based graph optimization
```

Now imagine a paper arrives titled:

> “Low-Rank Feature Pyramid Compression for Efficient Small-Object Detection”

You never searched for those exact words.

But:

```text
small-object detection
      ↕
platelet detection
      +
efficiency
      ↕
RTX 3050 constraint
```

Therefore Sentinel gives it a high project relevance score.

That is a **recommendation engine**, not a search engine.

### Project recommendations should explain themselves

A recommendation should read:

```text
Technology:
TensorRT-LLM technique X

Relevant project:
local-medical-assistant

Why:
Your project uses:
  PyTorch + CUDA
and specifies:
  RTX 3050 / low-VRAM inference

New information:
Technique X reduces temporary activation memory.

Compatibility:
Potentially applicable.

Evidence:
Paper: strong
Repository: available
RTX 3050 testing: no evidence found

Community:
Several developers report setup complexity on consumer GPUs.

Recommendation:
READ, but do not migrate yet.

Confidence:
medium
```

### Your private context stays private

This is also a major reason to make the aggregator local.

The MCP Filesystem reference implementation supports restricting filesystem access to configured locations. That model is ideal for exposing only:

```text
sentinel/context/
```

rather than your entire home directory. citeturn19view0

A remote third-party MCP should **never** receive unrestricted access to that folder.

Instead:

```text
project files
    ↓
LOCAL project analyzer
    ↓
abstract project profile
    ↓
search queries / source matching
```

For example, an external source might receive:

```text
"memory-efficient inference pytorch CUDA"
```

It should not receive:

```text
C:\Users\Vinay\Research\confidential-project\...
```

## Designing around your RTX 3050 and 16 GB RAM

Your hardware is entirely sufficient **provided you do not make the mistake of running a large model continuously**.

Ollama's current NVIDIA support explicitly includes the RTX 3050/3050 Ti family. citeturn20view0

A particularly sensible starting local model is:

```text
Qwen3:4b
```

The current Ollama package for that model is a 4.02-billion-parameter Q4_K_M artifact of about **2.5 GB**. citeturn20view1

That is much more appropriate for your machine than deploying a 14B/32B model as an always-on classification engine.

The important optimization is:

> **The LLM should process perhaps 20–100 promising events, not 5,000 raw events.**

Use a cascade.

```text
                    10,000 incoming events
                            │
                  cheap source rules
                            │
                           3,000
                            │
                  keyword/entity filter
                            │
                           1,000
                            │
                  duplicate clustering
                            │
                            300
                            │
                    embedding match
                            │
                            100
                            │
                  evidence expansion
                            │
                             40
                            │
                      local Qwen3
                            │
                             15
                            │
                        digest
```

Numbers are illustrative, but the principle is crucial.

### Lightweight local stack

I recommend:

| Function | Implementation |
|---|---|
| Network ingestion | Python `httpx` / async |
| RSS/Atom | `feedparser` |
| Canonical validation | Pydantic |
| Main database | SQLite |
| Full-text search | SQLite FTS5 |
| Embeddings | `all-MiniLM-L6-v2` initially |
| Semantic similarity | cosine similarity / compact local vector index |
| LLM | Qwen3:4B via Ollama |
| MCP | official Python MCP SDK |
| HTTP backend | FastAPI |
| Scheduler | APScheduler + OS startup scheduler |
| Frontend | lightweight local web UI |
| Configuration | YAML |
| Logging | Python structured logs |
| Testing | pytest |

`all-MiniLM-L6-v2` produces 384-dimensional sentence embeddings and is lightweight enough to be a sensible local semantic-retrieval model rather than putting every matching decision through a generative LLM. citeturn5search3

### RAM strategy

Your 16 GB system should behave approximately like this conceptually:

```text
Windows / OS               several GB
Sentinel daemon            small
SQLite/cache               small
Embedding model            small
Qwen model                 loaded when needed
Antigravity                variable
Browser                    variable
```

Consequently I would enforce:

```yaml
inference:
  max_parallel_jobs: 1

retrieval:
  max_full_text_documents: 5

workers:
  source_fetchers: 4
  llm_workers: 1

database:
  use_sqlite: true

models:
  summarizer: qwen3:4b
  embedding: all-MiniLM-L6-v2
```

**Do not run:**

```text
Elasticsearch
+
PostgreSQL
+
Redis
+
Qdrant
+
Kafka
+
Docker Kubernetes stack
+
large LLM
```

on this machine simply because enterprise architectures commonly use them.

You do not need them.

For one researcher:

```text
SQLite
+
filesystem cache
+
one daemon
+
one MCP process
+
Ollama
```

is enough.

### The GPU should sleep most of the day

The service can remain alive continuously while the model remains unloaded/inactive most of the time:

```text
12:00  fetch data     CPU/network
12:30  fetch data     CPU/network
13:00  fetch data     CPU/network
...
18:00  interesting cluster appears
       → invoke local model briefly
       → save structured analysis
       → GPU idle again
```

Then:

```text
06:30
aggregate overnight changes

06:40
run evidence expansion

06:45
LLM generates concise synthesis

07:00
Today's Radar available
```

Your always-running component is therefore the **small event daemon**, not the generative model.

### Full PDFs should be lazy-loaded

Do not download every arXiv PDF.

Instead:

```text
metadata
    ↓
abstract relevance
    ↓
high relevance?
   / \
 no   yes
      ↓
 retrieve HTML/full text/PDF when necessary
```

Apart from dramatically reducing storage and compute, arXiv's own API terms impose responsible rate behavior, and rights attached to individual paper content can vary; metadata-first processing is therefore technically and operationally cleaner. citeturn19view9

## The Antigravity implementation I recommend

Antigravity is a good **development and interactive-control environment**, but it should not itself be the thing keeping your crawler alive.

As of August 2026, Antigravity's documentation shows native MCP support, a built-in MCP Store, custom `mcp_config.json` configuration, and IDE/CLI/SDK MCP integration. citeturn19view1

So think:

```text
ANTIGRAVITY
    │
    │ build/debug/query
    ▼
SENTINEL MCP
    │
    ▼
SENTINEL SERVICE  ← always running
```

not:

```text
ANTIGRAVITY IDE MUST STAY OPEN
    ↓
otherwise monitoring stops
```

### Repository structure

Build this in Antigravity:

```text
sentinel/
│
├── README.md
├── pyproject.toml
├── .env.example
├── .gitignore
│
├── .agents/
│   └── mcp_config.json
│
├── config/
│   ├── settings.yaml
│   ├── topics.yaml
│   ├── sources.yaml
│   └── scoring.yaml
│
├── context/
│   └── projects/
│
├── src/
│   └── sentinel/
│       │
│       ├── main.py
│       │
│       ├── scheduler.py
│       │
│       ├── config.py
│       │
│       ├── database.py
│       │
│       ├── models.py
│       │
│       ├── logging.py
│       │
│       ├── sources/
│       │   ├── base.py
│       │   ├── arxiv.py
│       │   ├── openalex.py
│       │   ├── crossref.py
│       │   ├── pubmed.py
│       │   ├── openreview.py
│       │   ├── github.py
│       │   ├── hackernews.py
│       │   ├── stackexchange.py
│       │   ├── huggingface.py
│       │   ├── pypi.py
│       │   ├── rss.py
│       │   └── mcp_registry.py
│       │
│       ├── pipeline/
│       │   ├── normalize.py
│       │   ├── deduplicate.py
│       │   ├── entities.py
│       │   ├── relevance.py
│       │   ├── evidence.py
│       │   ├── community.py
│       │   ├── verify.py
│       │   └── rank.py
│       │
│       ├── intelligence/
│       │   ├── embeddings.py
│       │   ├── llm.py
│       │   ├── claims.py
│       │   └── synthesis.py
│       │
│       ├── projects/
│       │   ├── scanner.py
│       │   ├── profiler.py
│       │   └── watch_graph.py
│       │
│       ├── digest/
│       │   ├── daily.py
│       │   ├── breaking.py
│       │   └── followups.py
│       │
│       ├── mcp/
│       │   └── server.py
│       │
│       └── api/
│           └── app.py
│
├── web/
│   ├── templates/
│   └── static/
│
├── data/
│   ├── sentinel.db
│   └── cache/
│
├── scripts/
│   ├── install.ps1
│   ├── run.ps1
│   └── register_task.ps1
│
└── tests/
```

### Database model

Do not use one enormous `news` table.

At minimum:

```text
sources
source_state
raw_events

items
item_sources
entities
item_entities

claims
claim_evidence
evidence_edges

projects
project_entities
project_matches

daily_feed
user_item_state

watchlists
fetch_runs
source_health
```

Important distinction:

```text
items
```

represents the canonical discovery.

```text
raw_events
```

represents individual observations.

```text
claims
```

represents things asserted about the discovery.

```text
evidence_edges
```

represents why Sentinel believes or questions those assertions.

### Daily-state design

Your star/expiry behavior becomes extremely clean:

```text
user_item_state
─────────────────────────────
item_id
first_seen
last_seen
starred
starred_at
dismissed
read_at
```

and:

```text
daily_feed
─────────────────────────────
item_id
feed_date
rank
reason
expires_at
```

When:

```text
current_time > expires_at
AND starred == false
```

remove it from **daily_feed**.

Do not remove it from `items`.

### Three kinds of notifications

Your morning screen should deliberately separate:

```text
TODAY'S DISCOVERIES
new things since last digest

FOLLOW-UPS
something you previously saw has changed

FOR YOUR PROJECTS
new technologies strongly connected
to something in /context/projects
```

This leads to a much better experience:

```text
Good morning.

17 potentially relevant developments were found.
5 passed your high-confidence threshold.

━━━━━━━━━━━━━━━━━━━━━━━━━━
TOP RESEARCH
━━━━━━━━━━━━━━━━━━━━━━━━━━

1. New memory-efficient transformer method
   Relevance 94 | Evidence 82
   [Paper] [Code] [Evidence]

━━━━━━━━━━━━━━━━━━━━━━━━━━
FOLLOW-UP
━━━━━━━━━━━━━━━━━━━━━━━━━━

2. ★ Library X
   You starred this 13 days ago.

   NEW:
   Independent benchmark published.
   Claimed performance advantage appears smaller
   than originally reported.

━━━━━━━━━━━━━━━━━━━━━━━━━━
PROJECT MATCH
━━━━━━━━━━━━━━━━━━━━━━━━━━

3. Compiler optimization technique Y

   Matches:
   /projects/compiler-optimization

   Why:
   LLVM + loop optimization + vectorization

   [Analyse for project]
```

The **Follow-up** capability is one of the strongest differentiators from ordinary news aggregators.

### Antigravity MCP configuration

Antigravity supports installing custom MCP servers through its MCP configuration rather than restricting you to the built-in MCP Store. citeturn19view1

A local configuration should conceptually look like:

```json
{
  "mcpServers": {
    "sentinel": {
      "command": "uv",
      "args": [
        "run",
        "python",
        "-m",
        "sentinel.mcp.server"
      ]
    }
  }
}
```

Then Antigravity can ask:

```text
Show me today's high-confidence AI discoveries.
```

which maps to:

```text
sentinel.get_daily_digest(...)
```

Or:

```text
Is the new inference engine we saw this morning
actually mature enough for my Parkinson's project?
```

Sentinel can combine:

```text
stored event
+
evidence graph
+
project profile
+
community reports
```

without Antigravity independently crawling the internet again.

### A strong first prompt for Antigravity

Once the empty repository is created, this is close to the prompt I would give its coding agent:

```text
We are building a local-first autonomous technical-intelligence
system named Sentinel.

System constraints:
- Windows
- NVIDIA RTX 3050
- 16 GB RAM
- zero paid infrastructure
- Python
- SQLite
- async network ingestion
- local Ollama for optional LLM analysis
- one MCP server exposed to Antigravity
- all external sources are read-only

Do not build the web UI yet.

Implement the foundation:

1. pyproject.toml and src layout
2. Pydantic settings system
3. SQLite schema and migrations
4. abstract SourceAdapter interface
5. canonical Signal model
6. source run state / incremental cursors
7. retry, exponential backoff and rate limiting
8. structured logging
9. scheduler
10. graceful shutdown
11. pytest unit tests

Then implement source adapters in this order:

- Hacker News
- arXiv
- PyPI RSS
- Crossref
- OpenAlex
- GitHub

Adapters must never return source-specific objects downstream.
They must convert everything into canonical Signal objects.

Do not add LLM functionality yet.

Security:
- no shell execution from external content
- no arbitrary URL execution
- enforce source host allowlists
- secrets only through environment variables
- sanitize external HTML
- all connectors read-only

Generate a walkthrough and run tests before considering
the task complete.
```

That is much better than asking:

```text
"Build my whole AI news application."
```

Use Antigravity to build one independently testable layer at a time.

Current MCP security guidance specifically warns about command execution and malicious input crossing MCP boundaries and recommends validation, least privilege and isolation. citeturn20view8

## The zero-cost build roadmap and final system specification

The biggest mistake would be starting with fifty connectors.

Build the **intelligence architecture correctly with six**, then make adding another source almost trivial.

### Foundation

Start with:

```text
SQLite
SourceAdapter
Signal
scheduler
source state
logs
```

The abstract adapter contract can be roughly:

```python
class SourceAdapter:
    id: str

    async def poll(self, cursor=None) -> list[Signal]:
        ...

    async def expand(self, signal: Signal) -> list[Signal]:
        ...

    async def health(self):
        ...
```

Every source keeps a cursor:

```text
source_state
────────────────
source_id
last_poll
last_cursor
last_success
next_allowed_poll
failure_count
quota_remaining
```

This makes the engine polite and prevents unnecessary network usage.

### Initial source pack

Your **first production version** should have only:

```text
Hacker News
arXiv
OpenAlex
Crossref
GitHub
PyPI
```

Why these?

Together they provide:

```text
discovery
+
research
+
citation metadata
+
research identity
+
implementation
+
software releases
```

without paid infrastructure.

HN's API currently reports no rate limit; arXiv provides a public API under explicit low-rate use requirements; OpenAlex offers free access/budget; Crossref exposes open metadata APIs; GitHub has generous authenticated personal quotas; PyPI exposes native release feeds. citeturn20view3turn20view6turn20view2turn20view4turn18search1

Then add:

```text
OpenReview
PubMed
Europe PMC
Hugging Face
Stack Overflow
GitLab
Context7
Microsoft Learn
```

NCBI's default free access capacity alone—three requests per second without an API key and ten with a free key—is more than adequate for incremental PubMed monitoring. citeturn20view7

### Intelligence pipeline

Once ingestion is stable:

```text
Signal
  ↓
URL / ID dedupe
  ↓
entity extraction
  ↓
topic rules
  ↓
project similarity
  ↓
candidate threshold
```

Do this **without an LLM first**.

Then introduce the lightweight embedding model.

Then introduce Qwen3:4B only to:

```text
extract claims
explain relevance
summarize evidence
identify disagreements
produce digest prose
```

The RTX 3050 is supported by Ollama's current GPU matrix, and the Qwen3:4B quantized Ollama artifact is roughly 2.5 GB, making it an intentionally conservative model choice for your hardware. citeturn20view0turn20view1

### Evidence expansion

For only the most interesting events:

```text
paper
 ↓
DOI
 ↓
OpenAlex/Crossref
 ↓
repository?
 ↓
GitHub
 ↓
package?
 ↓
PyPI/Hugging Face
 ↓
developer discussion?
 ↓
HN/StackOverflow
```

Notice how this minimizes calls.

You're not asking:

```text
Search 20 platforms for everything.
```

You're asking:

```text
Something interesting appeared.
Now investigate it.
```

That is dramatically more intelligent and efficient.

### Project intelligence

Then implement:

```text
/context/projects
       ↓
filesystem scanner
       ↓
technology extraction
       ↓
project profile
       ↓
watch graph
       ↓
event matching
```

No cloud embeddings required.

### Daily and persistent UX

Only after the intelligence engine works should you implement the dashboard.

I would use five screens:

```text
┌──────────────────────────────────┐
│ TODAY                            │
│ Ranked discoveries              │
└──────────────────────────────────┘

┌──────────────────────────────────┐
│ FOLLOW-UPS                       │
│ Changed evidence around old      │
│ discoveries / starred items      │
└──────────────────────────────────┘

┌──────────────────────────────────┐
│ PROJECTS                         │
│ Recommendations by project       │
└──────────────────────────────────┘

┌──────────────────────────────────┐
│ STARRED                          │
│ Persistent personal library      │
└──────────────────────────────────┘

┌──────────────────────────────────┐
│ SOURCES                          │
│ Health, requests, failures,      │
│ last poll, useful-result ratio   │
└──────────────────────────────────┘
```

### Automatically judge whether a source deserves to stay

This is a feature I strongly recommend.

For every source calculate:

```text
discovered_items
duplicate_items
candidate_items
digest_items
starred_items
false_positive_items
poll_failures
bytes_downloaded
requests_used
```

Then:

```text
source_yield =
    high_quality_discoveries
    /
    requests_or_events_processed
```

You may discover after a month:

```text
Source               Events    Useful
─────────────────────────────────────
arXiv                 12,100      173
Hacker News            8,300       82
GitHub                  3,900      129
random tech RSS        22,500       11
```

Sentinel can automatically reduce:

```text
random tech RSS
```

from:

```text
every 30 min
```

to:

```text
every 6 h
```

because it produces almost nothing valuable for you.

This creates a **self-tuning source network**.

### Automatically discover new MCPs — but never automatically install them

One particularly interesting 2026 capability is monitoring the official MCP Registry itself. It is being actively updated with newly published MCP servers and exposes registry API/search functionality. citeturn21search14turn21search0

So Sentinel can periodically ask:

```text
Any new MCP servers related to:

research
arXiv
scientific papers
machine learning
Hugging Face
benchmarking
GitHub
compiler
CUDA
storage
database
documentation
developer community
?
```

Then produce:

```text
NEW MCP CANDIDATE

io.github.example/new-ai-papers

Capabilities:
- conference feeds
- citation graph
- PDF retrieval

Registry status:
published

Security:
UNREVIEWED

Potential value:
high

Recommendation:
inspect source code
```

**It must not install it automatically.**

That distinction matters because MCP servers can expose tools capable of filesystem/network/process operations; current MCP security guidance explicitly discusses remote-code-execution and data-exfiltration risks and recommends sandboxing and least privilege for relevant architectures. citeturn20view8

A new community MCP should pass:

```text
registry entry
      ↓
open-source repository?
      ↓
license?
      ↓
recent maintenance?
      ↓
dependencies inspected?
      ↓
network hosts declared?
      ↓
read-only functionality?
      ↓
source pinned?
      ↓
sandbox test
      ↓
manual approval
```

Only then:

```text
ACTIVE
```

### Security boundary

I would establish these rules permanently:

```text
SOURCE MCP
   │
   ├── internet access
   ├── no user files
   ├── no shell
   └── read only

PROJECT ANALYZER
   │
   ├── project/context folder only
   ├── no arbitrary internet upload
   └── read only

SENTINEL CORE
   │
   ├── database
   └── normalized source results

ANTIGRAVITY
   │
   └── talks only to Sentinel MCP
```

Antigravity's MCP system supports MCP permissions/access control, while MCP's own security documentation recommends defense-in-depth rather than treating server-provided content as automatically trustworthy. citeturn19view1turn20view8

### Polling policy I would use

A sensible starting configuration is:

```yaml
scheduler:

  hackernews:
    interval: 15m

  github_watchlist:
    interval: 30m

  pypi_watchlist:
    interval: 30m

  huggingface:
    interval: 1h

  vendor_feeds:
    interval: 1h

  arxiv:
    interval: 6h

  openreview:
    interval: 3h

  pubmed:
    interval: 6h

  crossref:
    mode: evidence_only

  openalex:
    mode: evidence_only

  stackoverflow:
    interval: 2h

  mcp_registry:
    interval: 12h

  context_scan:
    interval: 10m

  daily_digest:
    at: "07:00"
```

These are design choices rather than upstream requirements; each adapter should separately enforce its service's actual limits. For example, arXiv specifies no more than one legacy API/RSS/OAI request every three seconds, while Stack Exchange uses daily quotas/backoff, and GitHub uses hourly quota accounting. citeturn20view6turn20view5turn20view4

### Handling a sleeping computer

There is one unavoidable constraint.

A local program cannot collect information while your computer is physically powered off.

So the zero-cost local version should record:

```text
last_successful_poll
```

and on startup:

```text
NOW - last_successful_poll
        ↓
perform catch-up ingestion
        ↓
dedupe
        ↓
resume normal polling
```

Therefore:

```text
PC asleep overnight
      ↓
PC wakes 08:20
      ↓
Sentinel sees last successful run 23:14
      ↓
catch-up scan
      ↓
08:25 digest generated
```

You lose essentially no discovery coverage from sources that support historical/incremental retrieval.

Truly:

```text
24 / 7
even while laptop is OFF
```

requires another always-on computer/server. With your zero-cost requirement, I would not introduce a hosted dependency unless you already own an always-on device.

### The eventual intelligence loop

Once everything is finished, Sentinel should operate like this:

```text
                       ┌──────────────┐
                       │   DISCOVER   │
                       └──────┬───────┘
                              ↓
                       ┌──────────────┐
                       │  NORMALIZE   │
                       └──────┬───────┘
                              ↓
                       ┌──────────────┐
                       │   DEDUPE     │
                       └──────┬───────┘
                              ↓
                      ┌───────────────┐
                      │    MATCH      │
                      │ topics/project│
                      └───────┬───────┘
                              ↓
                       ┌──────────────┐
                       │ INVESTIGATE  │
                       └──────┬───────┘
                              ↓
                  ┌───────────────────────┐
                  │ BUILD EVIDENCE GRAPH  │
                  └───────────┬───────────┘
                              ↓
                    ┌──────────────────┐
                    │ COMMUNITY CHECK  │
                    └────────┬─────────┘
                             ↓
                    ┌──────────────────┐
                    │ CLASSIFY STATUS  │
                    └────────┬─────────┘
                             ↓
                    ┌──────────────────┐
                    │ PROJECT IMPACT   │
                    └────────┬─────────┘
                             ↓
                     ┌────────────────┐
                     │ RANK + NOTIFY  │
                     └────────┬───────┘
                              ↓
                       USER INTERACTION
                      /       |        \
                   READ      STAR     IGNORE
                    │         │          │
                    └─────────┼──────────┘
                              ↓
                      preference learning
                              ↓
                         NEXT CYCLE
```

That final feedback loop is important.

A star should not merely save an article.

It should teach the system:

```text
Vinay repeatedly stars:
- inference optimization
- CUDA memory optimization
- compiler work
- medical AI
- storage architecture

Vinay repeatedly ignores:
- consumer AI product launches
- generic startup funding
- marketing announcements
```

Then his radar gradually changes.

But I would never let behavioral personalization completely suppress exploration. Reserve perhaps:

```text
70–80% personalized intelligence
20–30% exploratory discoveries
```

so the system can still show you something genuinely novel.

### What the finished system becomes

What you are describing ultimately sits somewhere between:

```text
Google Scholar alerts
+
GitHub watch
+
Hacker News
+
technical RSS
+
research assistant
+
developer community analysis
+
personal recommender
+
knowledge graph
```

but with one major difference:

**it maintains longitudinal technical judgment.**

A discovery can evolve:

```text
DAY 1
New paper appears.
Status: PROMISING

DAY 3
Code released.
Status: STRONG PRIMARY EVIDENCE

DAY 12
Developers reproduce result.
Status: EARLY REPLICATION

DAY 30
Independent benchmark confirms most claims.
Status: STRONGLY SUPPORTED

DAY 48
Performance regression found on consumer GPUs.
Status: SUPPORTED WITH LIMITATIONS

DAY 90
You open your relevant project.
Sentinel:
"This is now mature enough that I recommend testing it."
```

That is the engine worth building.

It is no longer a **news aggregator**.

It is a personal, autonomous **technology intelligence and evidence-monitoring system**—local-first, compatible with your RTX 3050/16 GB machine, built around free/public incremental sources, dynamically extensible through MCP, and exposed to Antigravity through a single trusted MCP boundary. The current ecosystem already supplies strong building blocks across arXiv, OpenAlex, GitHub, GitLab, Hugging Face, Hacker News, Stack Overflow and multi-source scholarly search; the remaining value comes from the evidence graph, project context, longitudinal memory, and source-specific filtering that you build on top. citeturn21search1turn21search3turn22search1turn22search2turn22search7turn22search11turn21search2