# PrismForge AI v4 — Walkthrough Index

This directory documents the architecture and rationale of PrismForge AI v4, a multi-agent
LangGraph pipeline for corporate due diligence risk analysis. These files explain WHY the
code is written as it is — not what each line does.

All application logic lives in a single monolithic `pipeline.py`. There is no `src/`
subdirectory. See Decision 3.17 for the rationale.

---

## File Flow Diagram

```mermaid
flowchart TD
    subgraph DF["Dockerfile"]
        direction TB
        DK["Dockerfile\nFROM python:3.11-slim\nWORKDIR /app\nCOPY + pip install\nEXPOSE 8501\nCMD streamlit run app.py"]:::proc
    end

    subgraph PL["pipeline.py  (execution order top → bottom)"]
        direction TB
        SC["1. Pydantic schemas\nRouterOutput · WorkerPayload\nUniversalForm · ExtractionRecord"]:::proc
        ST["2. TypedDict states\nParentState · DocumentSubState"]:::state
        SG["3. LLM singletons\nrouter_llm (Gemini Flash)\nstructured_router\nllm (Claude Sonnet)\nstructured_llm"]:::llm
        SP["4. splitter singleton\nRecursiveCharacterTextSplitter\nchunk_size=4000  overlap=800"]:::proc
        ND["5. Nodes + helpers\ndirectory_crawler\nrouter_node · chunk_node\nroute_matrix_to_workers\nextraction_worker · handoff_node\nmaster_round_table_node\ndetect_blind_spots\ncompress_inbox"]:::proc
        GC["6. Graph construction\nStateGraph(DocumentSubState) → doc_pipeline\nStateGraph(ParentState) + doc_pipeline node\ndispatch_subgraphs edge\ncompile()"]:::guard
        RG["7. run_graph()\nawait graph.ainvoke()\nmax_concurrency=50"]:::entry
    end

    subgraph AP["app.py"]
        direction TB
        TB["ThreadPoolExecutor(max_workers=1)\n_run_pipeline() → new_event_loop()"]:::guard
        UI["Streamlit UI\ntwo-column layout\ntext_input for data room path\nspinner"]:::proc
        RR["ex.submit(_run_pipeline, path)\n.result(timeout=600)"]:::entry
        MR["st.markdown(report)\nst.download_button(...)"]:::output
    end

    DK -->|"packages pipeline.py + app.py\ninto single container"| PL
    DK --> AP
    RG -->|"run_graph imported by app.py"| RR
    TB --> UI
    UI --> RR
    RR --> MR

    SC --> ST --> SG --> SP --> ND --> GC --> RG

    classDef llm fill:#FEF3C7,stroke:#D97706,color:#92400E,font-weight:bold
    classDef state fill:#FDF4FF,stroke:#A855F7,color:#6B21A8
    classDef entry fill:#DBEAFE,stroke:#2563EB,color:#1E3A8A,font-weight:bold
    classDef output fill:#D1FAE5,stroke:#059669,color:#065F46,font-weight:bold
    classDef guard fill:#EDE9FE,stroke:#7C3AED,color:#4C1D95
    classDef proc fill:#DBEAFE,stroke:#2563EB,color:#1E3A8A
```

_Legend: yellow = LLM singleton, purple-tinted = state schema, blue = processing step or invocation entry point, green = rendered output, lavender = guard / graph wiring. Numbered annotations show the logical top-to-bottom execution order within `pipeline.py` at module load time._

---

## File Index

| File | What it covers |
|---|---|
| [pipeline.md](pipeline.md) | The monolithic `pipeline.py` — all schemas, singletons, nodes, helpers, and graph construction |
| [app.md](app.md) | `app.py` — the Streamlit frontend and async bridge |
| [dockerfile.md](dockerfile.md) | `Dockerfile` — container build, deployment, and API key injection |

---

## High-Level Data Flow

```
[app.py]
  ThreadPoolExecutor(max_workers=1)     -- dedicated thread with isolated event loop
  _run_pipeline() → asyncio.new_event_loop().run_until_complete(run_graph(path))
          |
          v
[pipeline.py — LangGraph graph]

  START
    |
    v
  directory_crawler                     -- reads all UTF-8 files; populates crawled_files
    |
    | dispatch_subgraphs (conditional edge)
    | emits one Send("doc_pipeline", initial_DocumentSubState) per file
    |
    v  (up to 50 concurrent, per max_concurrency)
  doc_pipeline  [x N files — StateGraph(DocumentSubState) sub-graph]
    |  router_node: structured_router.ainvoke → RouterOutput
    |     (semantic_summary + dynamic_topology in one call)
    |  chunk_node: splitter.split_text → document_chunks
    |  route_matrix_to_workers (conditional edge):
    |     emits Send("extraction_worker", payload_dict) × (chunks × lenses)
    |  extraction_worker [x M workers per sub-graph]:
    |     structured_llm.ainvoke → ExtractionRecord → local_inbox
    |  handoff_node: writes global_inbox + summary_store to DocumentSubState output fields
    |
    | (ParentState reducers accumulate as sub-graphs complete:
    |   global_inbox via operator.add
    |   summary_store via lambda a, b: {**a, **b})
    |
    v
  master_round_table_node
    |  1. detect_blind_spots(crawled_files, global_inbox)
    |  2. compress_inbox(global_inbox, limit=500)
    |  3. llm.ainvoke → free-form Markdown report
    |
    v
  END → master_risk_report (str)
          |
          v
[app.py]
  st.markdown(report)
  st.download_button(...)
```

---

## Key Architectural Decisions (Summary)

| Decision | What was chosen | Why |
|---|---|---|
| 3.17 | Monolithic `pipeline.py` | Sprint overhead of module decomposition exceeds benefit with no test harness |
| 3.18 | Spec-compliant sub-graphs (`doc_pipeline`) | `DocumentSubState` output fields with matching reducers enable reliable parent propagation |
| 3.16 | `detect_blind_spots` as Python function | A list filter is simpler and more transparent than a conditional graph node |
| 3.10 | `compress_inbox` 500-record guard | Keeps synthesis prompt within frontier model context limits |
| 3.4 | `max_concurrency=50` at graph invocation | Single unified throttle; no module-level Semaphore |
| 3.11 | Streamlit + Python async bridge | Stays in pure Python; eliminates JavaScript/SSE layer |
| 3.23 | `ThreadPoolExecutor` replaces `nest_asyncio` | Full event loop isolation; `nest_asyncio` insufficient under concurrent Send dispatch |
| 3.12 | Single Docker container on EC2 | Environmental determinism; managed PaaS fails with heavy AI dependency stacks |

---

## Invariant Quick Reference

The following invariants are referenced throughout these walkthrough files. For the full
binding contract see `docs/INTERFACE_CONTRACT.md`.

| ID | Rule |
|---|---|
| S1 | All four LLM singletons at module scope — never inside a node or worker |
| S2 | No module-level `asyncio.Semaphore` |
| S3 | No vector store imported or instantiated anywhere |
| P1 | `summary_store` uses merge reducer `lambda a, b: {**a, **b}` |
| P2 | `crawled_files` has no reducer — single write by crawler |
| R1 | Exactly one `structured_router.ainvoke` call per document |
| E3 | `route_matrix_to_workers` emits primitive dicts via `.model_dump()`, never Pydantic instances |
| E4 | `semantic_summary` stamped into every `WorkerPayload` at dispatch time |
| X1 | `extraction_worker` takes exactly one parameter (`payload_dict`) — no state parameter |
| X2 | `extraction_worker` reads `semantic_summary` from payload, never from state |
| X3 | `extraction_worker` uses `await structured_llm.ainvoke(...)` — never sync `.invoke()` |
| X4 | `extraction_worker` entire body wrapped in `try/except` — returns `{"local_inbox": []}` on failure |
| X5 | `extraction_worker` returns a constructed `ExtractionRecord`, not a raw dict |
| H1 | Exactly one handoff per document, firing after all workers complete |
| H2 | Handoff writes both `summary_store` and `global_inbox` in a single return dict |
| M1 | Single-shot synthesis — no map-reduce |
| M2 | Synthesis receives compressed records, never raw `global_inbox` |
| M3 | Blind-spot detection is a Python filter, not a graph node |
| C1 | `chunk_size=4000` is characters, not tokens |
| I1 | `max_concurrency=50` set only at graph invocation |
| I2 | Never `asyncio.run()` inside Streamlit — use `ThreadPoolExecutor` + `asyncio.new_event_loop()` |
| W1 | `WorkerPayload` fields are JSON-primitive only |
| W2 | `semantic_summary` is a required `WorkerPayload` field |

---

## v5 Touch Points (Cross-File)

These are the areas most likely to change in v5, independent of any single file:

- **Streaming output to Streamlit:** `master_round_table_node` currently collects the full
  report before `app.py` renders it. v5 would use `graph.astream` and update the Streamlit
  component incrementally, requiring a refactor of both `app.py` and the synthesis node.
- **`requirements.txt` pin for `aiohttp`:** `aiohttp>=3.13.5` must be pinned. The current
  `requirements.txt` omits this, requiring a runtime `pip install` after container start.
- **Module decomposition:** When test coverage warrants it, `pipeline.py` should split into
  `src/schemas.py`, `src/nodes.py`, `src/graph.py`, and `src/prompts.py`. `app.py` imports
  only `run_graph` so the split would not change the `app.py`/`pipeline.py` boundary.
