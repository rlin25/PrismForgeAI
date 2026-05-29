# Dockerfile — Walkthrough

The Dockerfile produces a single container image that runs the PrismForge AI v4 Streamlit
application. It encapsulates the Python runtime, dependencies, and application code into a
reproducible unit that runs identically in local development and on EC2.

---

## 1. Purpose

The Dockerfile exists to solve a specific sprint deployment problem: the PrismForge AI
dependency stack (LangGraph, Pydantic v2, LangChain, async LLM SDKs) is heavy and its
transitive dependency resolution is sensitive to Python and OS version. A Docker container
guarantees that the runtime which passes local testing is the same runtime that runs on the
deployment host. If it works locally, it works in production (Decision 3.12).

---

## 2. Relationships

- **References:** `requirements.txt` (copied and installed in the image), all application
  files (copied via `COPY . .`), port 8501 (exposed for Streamlit).
- **Referenced by:** nothing in the application code. The Dockerfile is purely an operational
  artifact — `app.py` and `pipeline.py` have no knowledge of it.
- **Deliberately does not:** install Chroma or any vector store dependency (Invariant S3);
  bake API keys into the image layer; use a multi-stage build (unnecessary for a
  single-container sprint deployment).

---

## 3. Base Image Choice

```dockerfile
FROM python:3.11-slim
```

`python:3.11-slim` is chosen over the full `python:3.11` image to reduce image size —
`slim` omits build tools and documentation that are not needed at runtime. Python 3.11
specifically is chosen because Pydantic v2's Rust core extension (`pydantic-core`) and the
LangChain/LangGraph ecosystem are tested against it. Using a newer minor version risks
untested edge cases in Pydantic v2's compiled layer during a sprint.

The `slim` variant still includes enough OS tooling to compile any packages with C extensions
during `pip install`. If a package required OS-level headers (e.g., `libssl`), the `slim`
base would need an `apt-get install` step first — but the current dependency set does not
require this.

---

## 4. Why Not Managed PaaS (Decision 3.12)

AWS App Runner and similar managed PaaS services were rejected because they abstract the build
environment in ways that produce opaque failures with heavy AI dependency stacks. Pydantic v2's
Rust core compilation and the transitive dependency chains of LangGraph, LangChain, and the LLM
SDKs routinely fail in managed build environments with cryptic errors. If the App Runner build
fails at hour 9 of a sprint, the debug cycle through abstracted cloud logs is unrecoverable
within sprint constraints. Docker guarantees environmental determinism.

---

## 5. Layer Order Rationale

```dockerfile
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
```

Dependencies are installed before application code is copied. This is the standard Docker
layer caching pattern: `requirements.txt` changes infrequently; application code changes on
every iteration. By separating the two `COPY` steps, Docker's layer cache can reuse the
`pip install` layer on rebuilds that only modify application code, saving the full
dependency installation time (which can be several minutes for this stack).

`--no-cache-dir` removes pip's download cache after installation, keeping the image layer
smaller. The cache has no value in a container image because `pip` is not run again after
image build.

---

## 6. API Key Injection (Decision 3.13)

```dockerfile
# API keys injected at runtime via -e flags (Decision 3.13)
# docker run -e ANTHROPIC_API_KEY=... -e GOOGLE_API_KEY=... -p 80:8501 prismforge-ai:latest
```

No API keys appear in the Dockerfile. They are injected at container start time via Docker's
`-e` flag:

```bash
docker run \
  -e ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY \
  -e GOOGLE_API_KEY=$GOOGLE_API_KEY \
  -p 80:8501 prismforge-ai:latest
```

Keys injected via `-e` exist only in the container's process environment. They are never
written to the filesystem, never appear in `docker history` or the image manifest, and are not
accessible to any other container. Volume-mounting a `.env` file (the rejected alternative)
creates a persistent file path that risks accidental git commits of credentials.

The `app.py` UI checks for the presence of these variables before enabling the run button
(see `app.md` §6). `langchain_anthropic` reads `ANTHROPIC_API_KEY` automatically;
`langchain_google_genai` reads `GOOGLE_API_KEY` automatically. Neither requires explicit
configuration in `pipeline.py`.

---

## 7. Port and CMD

```dockerfile
EXPOSE 8501
CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]
```

`EXPOSE 8501` documents the port; it does not publish it. The `-p 80:8501` flag at `docker
run` time maps host port 80 to container port 8501, making the Streamlit UI accessible on the
EC2 instance's public IP at the standard HTTP port without requiring users to specify a port
in the URL.

`--server.address=0.0.0.0` is required so Streamlit binds to all network interfaces inside
the container, not just loopback. Without this, the Streamlit server is inaccessible from
outside the container even with port mapping configured correctly.

`CMD` uses the exec form (JSON array) rather than the shell form (`CMD streamlit run ...`).
The exec form means Streamlit is PID 1 inside the container, which ensures SIGTERM signals
from `docker stop` are delivered directly to the Streamlit process for clean shutdown.

---

## 8. Known Issue: `aiohttp` Version

The `requirements.txt` does not pin `aiohttp>=3.13.5`. The base image's default `aiohttp`
version (3.9.5) lacks `aiohttp.ClientConnectorDNSError`, which is referenced by
`langchain-google-genai`'s transitive dependencies. This causes an `AttributeError` at
import time:

```
AttributeError: module 'aiohttp' has no attribute 'ClientConnectorDNSError'
```

The current workaround is a runtime `pip install "aiohttp>=3.13.5"` after the container
starts. The permanent fix — adding `aiohttp>=3.13.5` to `requirements.txt` — has not yet
been applied to the committed file and should be the first change in the next maintenance
pass (see `docs/DESIGN.md` §3.22). Without the correct `aiohttp` version, no LLM calls can
be made. This is a hard blocker at startup, not a degraded-operation condition.

---

## 9. What the Dockerfile Does NOT Do

- Does not install Chroma or any vector store (Invariant S3). The `requirements.txt` the
  Dockerfile installs also contains no vector store dependency.
- Does not configure LLM API keys in the image. Keys are injected at runtime.
- Does not copy a `.env` file. There is no `.env` file in the repository.
- Does not use a multi-stage build. A multi-stage build would reduce image size by separating
  build-time tools from the runtime image, but the dependency set does not include
  compile-heavy packages that would benefit materially from this optimization.
- Does not run tests. No test files exist in the repository.
- Does not mount a data room directory. The data room path is provided by the user at runtime
  via the Streamlit UI and must exist on the host; it can be volume-mounted via
  `-v /host/data_room:/app/data_room` if needed, but this is not in the Dockerfile.

---

## 10. v5 Touch Points

- **`aiohttp` pin:** Add `aiohttp>=3.13.5` to `requirements.txt`. This is the only required
  Dockerfile-adjacent change for the current deployment to work without a manual post-start
  step.
- **Health check:** A `HEALTHCHECK` instruction would let `docker run` and orchestration
  platforms (ECS, Kubernetes) know when the container is ready to serve traffic. Streamlit
  exposes `/_stcore/health` for this purpose.
- **Non-root user:** The current image runs as root inside the container. Adding a
  `RUN useradd -m appuser && chown -R appuser /app` step and `USER appuser` before `CMD`
  would reduce the attack surface in production.
- **`.dockerignore`:** A `.dockerignore` file should exclude `__pycache__`, `.git`,
  `data_room/`, and any local `.env` files from the build context to keep build times short
  and prevent accidental credential inclusion.
- **Pinned base image digest:** `FROM python:3.11-slim` resolves to the latest patch at
  build time, which can change. Production builds should pin to a specific digest
  (e.g., `FROM python:3.11-slim@sha256:...`) for full reproducibility.
