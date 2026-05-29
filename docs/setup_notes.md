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
streamlit run app.py
```

The app will be available at `http://localhost:8501`.

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

**Fix (implemented in `app.py`):** `nest_asyncio.apply()` is called at module
load (before Streamlit executes any callbacks), and the pipeline is invoked with
`asyncio.get_event_loop().run_until_complete(...)` instead of `asyncio.run()`:

```python
import nest_asyncio
nest_asyncio.apply()  # must be called before any Streamlit callback executes

# In the button handler:
report = asyncio.get_event_loop().run_until_complete(run_graph(data_room_path))
```

**Status:** Resolved. `nest_asyncio` is in `requirements.txt`.

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
├── pipeline.py          # Monolithic pipeline: schemas, LLM singletons, all nodes, graph
├── app.py               # Streamlit frontend with nest_asyncio bridge
├── Dockerfile           # FROM python:3.11-slim; EXPOSE 8501
├── requirements.txt     # Core dependencies (aiohttp pin needed — see §6.1)
├── data_room/           # Default document directory (create before first run)
├── docs/
│   ├── DESIGN.md        # Consolidated decision ledger (v11 + post-implementation decisions)
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

# 5. Build Docker image
docker build -t prismforge-ai:latest .

# 6. Run container
docker run \
  -e ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY \
  -e GOOGLE_API_KEY=$GOOGLE_API_KEY \
  -p 80:8501 \
  prismforge-ai:latest

# 7. Access at http://<EC2-public-IP>
```

---

*Document version: 1.0 — created post Phase 7 feedback loop*
*Reflects actual deployment state as of implementation completion*
