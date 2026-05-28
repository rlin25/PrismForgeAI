# MASTERPLAN — PrismForge AI v4 (DST Engine)

> Orchestration plan for Claude Code. Implements the v11 consolidated design.
> Each phase below maps to a standalone subplan file. Build strictly in order.
> Hard sprint budget: 10 hours.

---

## Mission

Build a multi-agent LangGraph pipeline that ingests a directory of corporate
due-diligence documents, decomposes each file into semantic chunks, runs a
`Chunks × Lenses` extraction matrix of async workers, and synthesizes a single
cross-referenced liability risk report rendered in Streamlit.

## Authoritative Stack

LangGraph · Pydantic v2 · LangChain · `langchain-text-splitters` ·
`langchain-google-genai` · `langchain-anthropic` · asyncio · `nest_asyncio` ·
Streamlit · Docker (EC2).

**No Chroma. No vector store.** Any vector-store import is a build error.

## Non-Negotiable Invariants (the spec's hard constraints)

These hold across every subplan. Violating any one is a build failure.

1. `extraction_worker` takes **one** parameter (`payload_dict`). It has **no**
   `state` parameter — LangGraph does not inject parent state into
   `Send`-dispatched nodes.
2. `semantic_summary` travels **inside `WorkerPayload`**, stamped at dispatch
   time by `route_matrix_to_workers`, which reads it from `DocumentSubState`.
3. `route_matrix_to_workers` is a conditional edge function with a **single**
   `state: DocumentSubState` parameter. A two-parameter signature raises a
   `TypeError` at compile time.
4. `Send` payloads are **primitive dicts only** (`worker_config.model_dump()`).
   No Pydantic instances, no `datetime`/`numpy`/complex classes.
5. There is **exactly one** state handoff per sub-graph, firing **after**
   workers complete. It writes both `summary_store` and `global_inbox` in one
   atomic return dict. No pre-fan-out handoff exists.
6. `summary_store` uses a **merge reducer** so parallel sub-graphs accumulate
   instead of overwriting.
7. `global_inbox` and `local_inbox` use the `add` reducer; entries are
   `ExtractionRecord` objects, never raw dicts.
8. `extraction_worker` uses `await ...ainvoke()` and is wrapped in `try/except`
   returning `{"local_inbox": []}` on failure.
9. LLM bindings (`structured_router`, `structured_llm`) are **module-level
   singletons**.
10. Concurrency is controlled only by `config={"max_concurrency": 50}` at graph
    invocation — never a module-level `asyncio.Semaphore`.
11. Chunking via `RecursiveCharacterTextSplitter(chunk_size=4000,
    chunk_overlap=800)` — characters, not tokens.
12. Streamlit async bridge: `nest_asyncio.apply()` +
    `get_event_loop().run_until_complete()` — never `asyncio.run()`.

## Build Order (subplans)

| # | Subplan | Hours | Produces |
|---|---|---|---|
| 1 | `01_SUBPLAN_environment_and_crawler.md` | 1–2 | env + crawler + mock data room |
| 2 | `02_SUBPLAN_schemas_router_handoff.md` | 3–5 | state schemas, router, handoff node, LLM singletons |
| 3 | `03_SUBPLAN_matrix_and_workers.md` | 6–7 | chunking, fan-out mapper, async worker pool |
| 4 | `04_SUBPLAN_synthesis_blindspot_deploy.md` | 8–10 | blind-spot + compress filters, synthesis, Streamlit, Docker/EC2 |

## Topology (target end-state)

```
Directory Crawler ──► [Sub-Graph per file] ──► single post-workers handoff
                          router → chunk → fan-out → async workers
                                                          │
                          (summary_store + global_inbox populated in parent)
                                                          ▼
                          Master Round-Table Node
                          preamble: detect_blind_spots() → compress_inbox()
                          synthesis: single-shot streaming Markdown
                                                          ▼
                                            Final Risk Report (Streamlit)
```

## Definition of Done

- `docker build` succeeds with no Chroma/vector imports.
- Three-file mock data room with embedded cross-document contradictions runs
  end-to-end and produces a report.
- A file that yields zero records is named in a "Coverage Gaps" block, not
  silently dropped.
- A forced worker exception does not crash the pool; the run still completes.
- Report streams to `st.markdown()` without the "event loop already running"
  error.

## Per-Phase Gate

Do not advance a phase until its subplan's verification checklist passes.
