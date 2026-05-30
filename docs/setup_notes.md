# Setup Notes — PrismForge AI v4

> Operational reference for deploying and running PrismForge AI v4 (DST Engine).
> Covers environment setup, API key configuration, Docker deployment, and known
> runtime issues encountered post-implementation.

---

## 1. Prerequisites

- Python 3.11 (matches the Docker base image; 3.10 is untested)
- Docker (for containerized deployment)
- An AWS EC2 instance with port 80 open (for public demo access)
- Two paid API accounts:
  - **Anthropic** — Claude Sonnet 4 (extraction + synthesis)
  - **Google Cloud** — Gemini Flash (document routing). A paid billing account is
    required; free-tier quota is exhausted almost immediately by the routing phase
    even on small document sets.

---

## 2. API Keys

Both keys must be present in the runtime environment. The pipeline will not start
extraction without them — `app.py` checks at load time and disables the run button
if either is missing.

### Local development (non-Docker)

Do **not** store keys in `~/.bashrc`. On most Linux systems (including EC2 and
WSL2), `~/.bashrc` contains an interactive-shell guard (`[ -z "$PS1" ] && return`)
that prevents environment variables from being exported to non-interactive child
processes such as Streamlit or Docker daemon shells.

Store keys in `~/.profile` instead:

```bash
# ~/.profile — sourced for login shells (Docker, Streamlit non-interactive)
export ANTHROPIC_API_KEY="sk-ant-..."
export GOOGLE_API_KEY="AIza..."
```

After editing `~/.profile`, either log out/in or source it explicitly:

```bash
source ~/.profile
```

Verify the keys are visible:

```bash
echo $ANTHROPIC_API_KEY   # should print the key, not blank
echo $GOOGLE_API_KEY
```

### Docker deployment

Keys are injected at `docker run` time via `-e` flags. They are **never** baked
into the image layer:

```bash
docker run \
  -e ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY \
  -e GOOGLE_API_KEY=$GOOGLE_API_KEY \
  -p 80:8501 \
  prismforge-ai:latest
```

---

## 3. Local Installation (no Docker)

```bash
cd /path/to/PrismForgeAI
pip install -r requirements.txt
python3 preprocess.py          # convert source_docs/*.htm → data_room/*.txt
streamlit run app.py
```

The app will be available at `http://localhost:8501`.

The UI includes:
- An animated 6-stage pipeline diagram (CRAWL → ROUTE → CHUNK → EXTRACT → SYNTHESIZE → REPORT)
  with CSS pulse animation; stages turn green as they complete during a run.
- A dynamic lens selection topology widget: colored chips appear per document as routing
  completes, showing which lenses were assigned to each file.
- A worker counter showing live progress ("Workers: 23/50 complete | 2 retrying...").
- Document preview expanders in the config panel showing the first 1,500 characters of each
  `.txt` file in the data room, with total character count.
- The report section renders only after generation is complete — no placeholder shown beforehand.

`beautifulsoup4` is listed in `requirements.txt` and will be installed by the
`pip install` step above. `preprocess.py` also includes a fallback self-installer
for environments where it is missing.

---

## 4. Docker Build and Deploy

```bash
# Build
docker build -t prismforge-ai:latest .

# Run locally (port 8501)
docker run \
  -e ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY \
  -e GOOGLE_API_KEY=$GOOGLE_API_KEY \
  -p 8501:8501 \
  prismforge-ai:latest

# Run on EC2 (map to port 80 for public access without :port suffix in URL)
docker run \
  -e ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY \
  -e GOOGLE_API_KEY=$GOOGLE_API_KEY \
  -p 80:8501 \
  prismforge-ai:latest
```

The Streamlit server binds to `0.0.0.0:8501` inside the container (set in the
Dockerfile CMD). Port 80 on the EC2 host maps to 8501 in the container.

---

## 5. Data Room Directory

The pipeline expects a directory of plain-text files (UTF-8 encoded). The default
path is `./data_room` relative to the project root, but any absolute or relative
path can be entered in the Streamlit UI.

The `data_room/` directory is populated by running `preprocess.py`, which reads raw
EDGAR `.htm` filings from `source_docs/` and writes clean `.txt` extracts. The
original synthetic fixture files (`file_a.txt`, `file_b.txt`, `file_c.txt`) have been
replaced with real EDGAR documents:

- `dot_hill_10k_2006.txt` — extracted from the Dot Hill Systems FY2006 10-K
  (Item 1 Business + Item 1A Risk Factors)
- `hp_product_purchase_agreement.txt` — extracted from the HP Product Purchase
  Agreement EX-10.1 (Sections 14–20 and Exhibit L: IP warranty, indemnification,
  liability cap)

Run `python3 preprocess.py` before starting the app whenever the `source_docs/`
files change or when setting up a fresh environment.

- Binary files (`.DS_Store`, PDFs, images) are skipped silently by the directory
  crawler — they produce no error and do not crash the run.
- Files that produce zero extraction records (e.g. encoding failures, empty
  content, LLM refusal) are listed in the "Coverage Gaps" section of the final
  report.
- There is no minimum or maximum file count, but practical performance degrades
  above approximately 30 files due to API rate limits. The `max_concurrency=50`
  cap at graph invocation throttles parallel document pipelines.

---

## 6. Known Issues and Workarounds

### 6.1 aiohttp `ClientConnectorDNSError` — missing symbol (Critical)

**Symptom:** Import error at startup or connection failure during LLM calls:

```
AttributeError: module 'aiohttp' has no attribute 'ClientConnectorDNSError'
```

**Cause:** The `langchain-google-genai` SDK (and its transitive dependencies)
reference `aiohttp.ClientConnectorDNSError`, which was added in `aiohttp>=3.10`.
The version that ships by default (3.9.5 pinned by many Python environments) is
missing this symbol.

**Workaround (applied at runtime):**

```bash
pip install "aiohttp>=3.13.5"
```

**Permanent fix:** Pin `aiohttp>=3.13.5` in `requirements.txt`. This is not yet
reflected in the committed `requirements.txt` — it was applied as a runtime patch
during deployment.

**Status:** Known issue. `requirements.txt` should be updated to include
`aiohttp>=3.13.5` before the next Docker build.

---

### 6.2 Gemini model `gemini-2.0-flash` deprecated for new accounts

**Symptom:** API error during the routing phase:

```
google.api_core.exceptions.InvalidArgument: 400 gemini-2.0-flash is not supported
for generateContent. Please use a different model.
```

or similar deprecation/quota error from the Google AI API.

**Cause:** `gemini-2.0-flash` was deprecated for new Google AI API accounts and
free-tier users. Google migrated new-account traffic to `gemini-2.5-flash`.

**Fix (applied in `pipeline.py`):** The `router_llm` singleton was updated:

```python
# Before (deprecated for new accounts):
router_llm = ChatGoogleGenerativeAI(model="gemini-2.0-flash")

# After (current):
router_llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash")
```

**Status:** Applied. `pipeline.py` currently uses `gemini-2.5-flash`.

---

### 6.3 Google API free-tier quota exhausted

**Symptom:** `429 Resource Exhausted` errors from the Google AI API during
routing, typically after the first 1–2 document runs.

**Cause:** The Google AI free tier has very low RPM and daily quotas. A 3-file
data room can exhaust free-tier quota on the first run.

**Fix:** Enable billing on the Google Cloud project associated with the API key.
Paid quota limits are orders of magnitude higher and sufficient for demo workloads.

**Status:** Operational requirement. Billing must be enabled for reliable use.

---

### 6.4 `asyncio.run()` raises `RuntimeError` inside Streamlit

**Symptom:**

```
RuntimeError: This event loop is already running
```

**Cause:** Streamlit manages its own internal event loop. Calling `asyncio.run()`
from within a Streamlit callback creates a nested event loop, which Python's
default asyncio policy does not allow.

**Fix (implemented in `app.py`):** The pipeline runs in a dedicated
`ThreadPoolExecutor` thread that creates a fresh `asyncio.new_event_loop()`:

```python
def _run_pipeline(directory_path: str) -> str:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(run_graph(directory_path))
    finally:
        loop.close()

with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
    report = ex.submit(_run_pipeline, data_room_path).result(timeout=600)
```

**Status:** Resolved via Decision 3.23. `nest_asyncio` remains in `requirements.txt`
but `nest_asyncio.apply()` is no longer called.

---

### 6.6 Anthropic Tier 1 rate limits cause silent worker failures

**Symptom:** The final report has sparse findings — most files have few or no extraction
records despite the pipeline completing without errors.

**Cause:** Anthropic Tier 1 accounts are capped at 50 requests per minute. When 50+
extraction workers fire simultaneously, the majority receive 429 RESOURCE_EXHAUSTED errors.
Each worker's bare `try/except` catches the error and returns `{"local_inbox": []}`,
silently omitting those chunk × lens combinations from the report.

**Fix (implemented in `pipeline.py`):** `extraction_worker` retries up to 3 attempts on
rate-limit errors (detected by "429" or "rate_limit" in the error string), waiting 15
seconds after the first failure and 30 seconds after the second before giving up permanently.

**Status:** Resolved via Decision 3.24. See also §6.7 for the `MAX_CHARS` cap that limits
total worker count to stay within Tier 1 quota.

---

### 6.7 Document extraction capped at 20k characters per file (Tier 1 rate limits)

**Symptom:** Extraction output covers only a portion of long documents; later sections
are not analyzed.

**Cause:** `preprocess.py` caps extraction at `MAX_CHARS = 20_000` characters per file.
This limit was deliberately reduced from 90k to keep total worker count within Anthropic
Tier 1 rate limits (~50 RPM). A 90k-character document would produce ~22 chunks at
`chunk_size=4000`; with 5 lenses assigned, that is ~110 workers per file — already over
the Tier 1 ceiling for a single file.

**Fix:** Increase `MAX_CHARS` in `preprocess.py` and upgrade the Anthropic account to
Tier 2 or higher. Tier 2 raises the RPM ceiling enough to handle 90k-character documents
with typical lens assignments.

**Status:** Known limitation. Tier 1 constraint is documented in `preprocess.py`.

---

### 6.8 Python 3.9 incompatibility: `Path | None` union type hint

**Symptom:** `SyntaxError` when running `preprocess.py` on EC2 or any Python 3.9
environment:

```
SyntaxError: unsupported operand type(s) for |: 'type' and 'NoneType'
```

**Cause:** The `Path | None` union syntax for type hints requires Python 3.10+. EC2
Amazon Linux 2 and some other deployment targets ship with Python 3.9 by default.

**Fix (applied in `preprocess.py`):** The `Path | None` type annotation was removed from
the function signature. The function behavior is unchanged; only the type hint is absent.

**Status:** Resolved.

---

### 6.5 `nest_asyncio` insufficient for LangGraph concurrent Send dispatch

**Symptom:**

```
RuntimeError: Task got Future <Future pending> attached to a different loop
```

**Cause:** `nest_asyncio.apply()` (the original Invariant I2 prescription) patches
the running loop to allow nested `run_until_complete` calls, which is sufficient
for simple single-coroutine invocations. It does not prevent LangGraph from creating
tasks that reference different loop instances when running dozens of parallel
extraction workers via Send dispatch inside the spec-compliant sub-graph architecture.

**Fix:** The `ThreadPoolExecutor` bridge (§6.4, Decision 3.23). The dedicated thread
owns a completely isolated event loop; LangGraph's task scheduler, the httpx clients
inside LangChain's LLM wrappers, and all async futures are created and resolved within
the same loop. No cross-loop future references are possible.

**Status:** Resolved. `nest_asyncio.apply()` removed from `app.py`.

---

## 7. Environment Variable Checklist

| Variable | Required | Source |
|---|---|---|
| `ANTHROPIC_API_KEY` | Yes | Anthropic console (console.anthropic.com) |
| `GOOGLE_API_KEY` | Yes | Google Cloud console (AI Studio or Cloud Console) |

---

## 8. File Layout

```
PrismForgeAI/
├── pipeline.py          # Sub-graph pipeline: schemas, LLM singletons, all nodes, graph
├── app.py               # Streamlit frontend with ThreadPoolExecutor async bridge
├── preprocess.py        # EDGAR .htm → clean .txt converter (run before app.py)
├── Dockerfile           # FROM python:3.11-slim; EXPOSE 8501
├── requirements.txt     # Core dependencies (aiohttp pin needed — see §6.1)
├── source_docs/         # Raw EDGAR .htm source filings (input to preprocess.py)
│   ├── dot_hill_systems_10-k.html
│   └── dot_hill_systems_ex_10.1.html
├── data_room/           # Preprocessed .txt files (output of preprocess.py; pipeline input)
│   ├── dot_hill_10k_2006.txt
│   └── hp_product_purchase_agreement.txt
├── docs/
│   ├── DESIGN.md        # Consolidated decision ledger (v13 + post-implementation decisions)
│   ├── INTERFACE_CONTRACT.md  # Binding signature/schema/invariant contract
│   ├── GLOSSARY.md      # Term definitions
│   └── setup_notes.md   # This file
└── plans/
    ├── 00_MASTERPLAN.md
    ├── 01_SUBPLAN_environment_and_crawler.md
    ├── 02_SUBPLAN_schemas_router_handoff.md
    ├── 03_SUBPLAN_matrix_and_workers.md
    └── 04_SUBPLAN_synthesis_blindspot_deploy.md
```

---

## 9. Quick-Start Sequence (EC2 Deploy)

```bash
# 1. SSH into EC2 instance
# 2. Clone or copy the repo
# 3. Ensure keys are available in the shell
source ~/.profile

# 4. Fix aiohttp version (until requirements.txt is updated)
pip install "aiohttp>=3.13.5"

# 5. Preprocess EDGAR source files → data_room/ (local, before Docker build)
python3 preprocess.py

# 6. Build Docker image
docker build -t prismforge-ai:latest .

# 7. Run container
docker run \
  -e ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY \
  -e GOOGLE_API_KEY=$GOOGLE_API_KEY \
  -p 80:8501 \
  prismforge-ai:latest

# 8. Access at http://<EC2-public-IP>
```

---

*Document version: 1.1 — updated post-Phase 7 UI improvements and Tier 1 rate-limit fixes*
*Reflects actual deployment state as of implementation completion*
