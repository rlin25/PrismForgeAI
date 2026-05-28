# INTERFACE CONTRACT — PrismForge AI v4 (DST Engine)

> Binding contract derived from the v11 consolidated design and subplans 00–04.
> This document defines every signature, schema shape, reducer, and invariant
> across module boundaries. Any code that violates a clause here is a build
> failure. Where the contract and prose disagree, the contract wins.

---

## 0. Module Layout & Singletons

| Symbol | Kind | Instantiated | Bound schema |
|---|---|---|---|
| `router_llm` | `ChatGoogleGenerativeAI(model="gemini-2.0-flash")` | module scope, once | — |
| `structured_router` | `router_llm.with_structured_output(RouterOutput)` | module scope, once | `RouterOutput` |
| `llm` | `ChatAnthropic(model="claude-sonnet-4-20250514")` | module scope, once | — |
| `structured_llm` | `llm.with_structured_output(UniversalForm)` | module scope, once | `UniversalForm` |

**Invariant S1.** All four are module-level singletons. Re-instantiating any of
them inside a node, edge function, or worker is a violation.

**Invariant S2.** No module-level `asyncio.Semaphore`. Concurrency is governed
solely by `config={"max_concurrency": 50}` at graph invocation.

**Invariant S3.** No vector-store symbol is imported or instantiated anywhere.

---

## 1. Data Schemas (`pydantic.BaseModel`)

### `RouterOutput`
```
semantic_summary: str          # 200–400 words
dynamic_topology: List[str]    # 3–7 lens identifiers
```
Produced by `structured_router`. Both fields populated in a single call.

### `DependencyLink`
```
target_file: str
target_concept: str
nature_of_contradiction: str
```

### `UniversalForm`
```
entity_or_concept: str
factual_evidence_quote: str
implied_liability_score: int                 # ge=1, le=10
cross_reference_dependencies: List[DependencyLink]   # default []
```
Produced by `structured_llm`.

### `ExtractionRecord`
```
lens_name: str
source_file: str
chunk_index: int
payload: UniversalForm
```
The unit of `local_inbox` / `global_inbox`. **Never** a raw dict in those channels.

### `WorkerPayload`
```
lens_name: str
source_file: str
chunk_index: int
target_chunk_text: str
semantic_summary: str          # stamped at dispatch time
```
**Invariant W1.** JSON-primitive fields only — no `datetime`, `numpy`, or
complex classes. `Send` fails silently otherwise.
**Invariant W2.** `semantic_summary` is a required field carried inside the
payload — it is the only channel by which a worker receives the summary.

---

## 2. State Schemas (`TypedDict`)

### `ParentState`
| Field | Type | Reducer |
|---|---|---|
| `directory_path` | `str` | none |
| `crawled_files` | `List[str]` | **none** (single write by crawler) |
| `summary_store` | `Dict[str, str]` | **merge** `lambda a, b: {**a, **b}` |
| `global_inbox` | `List[ExtractionRecord]` | `operator.add` |
| `master_risk_report` | `str` | none |

**Invariant P1.** `summary_store` MUST use the merge reducer. Default overwrite
loses all but the last sub-graph when files run in parallel.
**Invariant P2.** `crawled_files` carries no reducer; it is written exactly once
by the crawler before any sub-graph runs.

### `DocumentSubState`
| Field | Type | Reducer |
|---|---|---|
| `source_material` | `str` | none |
| `file_name` | `str` | none |
| `semantic_summary` | `str` | none |
| `dynamic_topology` | `List[str]` | none |
| `document_chunks` | `List[str]` | none |
| `local_inbox` | `List[ExtractionRecord]` | `operator.add` |

**Invariant D1.** No `gap_detected` and no `blind_spots` fields. They were
removed in v6; blind-spot detection is a Python filter in the Round-Table
preamble, not state.

---

## 3. Node & Edge Contracts

### `directory_crawler` (node)
```
in:  ParentState (reads directory_path)
out: {"crawled_files": List[str]}   # every successfully read filename
```
Defensive read loop catching `UnicodeDecodeError`, `IsADirectoryError`,
`PermissionError`; unreadable/binary files skipped silently. Populates
`crawled_files` before any sub-graph runs.

### `router_node` (node, async)
```
sig: async def router_node(state: DocumentSubState) -> Dict[str, Any]
in:  reads state["source_material"]
out: {"semantic_summary": str, "dynamic_topology": List[str]}
```
**Invariant R1.** Exactly one `await structured_router.ainvoke(...)` per
document. Never two calls (no separate summary + lens calls).

### `route_matrix_to_workers` (conditional edge function)
```
sig: def route_matrix_to_workers(state: DocumentSubState) -> List[Send]
```
**Invariant E1.** Single `state: DocumentSubState` parameter only. A
`(state, parent_state)` signature raises `TypeError` at compile time.
**Invariant E2.** Reads `semantic_summary` from `state` (written by
`router_node` earlier in the same sub-graph — always present at dispatch).
**Invariant E3.** Emits the full `chunks × dynamic_topology` cross-product as
`Send("extraction_worker", worker_config.model_dump())` — primitive dicts only,
never a Pydantic instance.
**Invariant E4.** Stamps `semantic_summary` into every `WorkerPayload`, resolved
once per dispatch batch.

### `extraction_worker` (node, async)
```
sig: async def extraction_worker(payload_dict: Dict[str, Any]) -> Dict[str, Any]
out (success): {"local_inbox": [ExtractionRecord(...)]}
out (failure): {"local_inbox": []}
```
**Invariant X1.** Exactly one parameter (`payload_dict`). **No `state`
parameter** — LangGraph does not inject parent state into `Send`-dispatched
nodes; it would resolve empty.
**Invariant X2.** Reads `semantic_summary` from the payload, never from state.
**Invariant X3.** Uses `await structured_llm.ainvoke(...)`. Sync `.invoke()` is
a violation (blocks the event loop).
**Invariant X4.** Wrapped in `try/except`; on any exception returns
`{"local_inbox": []}` so one failure cannot crash the pool.
**Invariant X5.** Returns a constructed `ExtractionRecord`, not a raw dict.

### `handoff_node` (node, sync)
```
sig: def handoff_node(sub_state: DocumentSubState) -> Dict[str, Any]
out: {
       "global_inbox": sub_state["local_inbox"],
       "summary_store": {sub_state["file_name"]: sub_state["semantic_summary"]},
     }
```
**Invariant H1.** Exactly one handoff per sub-graph, firing **after** workers
complete. No pre-fan-out handoff exists.
**Invariant H2.** Writes both `summary_store` and `global_inbox` in one atomic
return dict. Pure dict mapping — no I/O, no LLM call.

### `master_round_table_node` (node, terminal)
```
in:  ParentState (reads crawled_files, global_inbox)
out: {"master_risk_report": str}   # streamed Markdown
```
Preamble runs, in order:
1. `detect_blind_spots(crawled_files, global_inbox) -> List[str]` → builds
   `blind_spot_block` naming zero-record files.
2. `compress_inbox(global_inbox, limit=500) -> (records, warning_block)` →
   sorts desc by `implied_liability_score`, truncates to 500 if needed.
3. Synthesis prompt = `blind_spot_block + truncation_warning + "\n\n" +
   json.dumps([r.model_dump() for r in records])`.

**Invariant M1.** Single-shot long-context streaming synthesis. No map-reduce.
**Invariant M2.** Synthesis receives the **compressed** records, never the raw
`global_inbox`.
**Invariant M3.** Blind-spot detection is a Python filter here, not a graph node.

---

## 4. Pure Function Contracts

### `detect_blind_spots`
```
def detect_blind_spots(crawled_files: List[str],
                       global_inbox: List[ExtractionRecord]) -> List[str]
```
Returns filenames present in `crawled_files` but absent from
`{r.source_file for r in global_inbox}`. Deterministic; no side effects.

### `compress_inbox`
```
def compress_inbox(global_inbox: List[ExtractionRecord], limit: int = 500
                   ) -> tuple[List[ExtractionRecord], str]
```
- `len <= limit` → `(global_inbox, "")`.
- else → top-`limit` records by `implied_liability_score` desc, plus a
  non-empty Markdown truncation-warning string.

### Chunking
```
splitter = RecursiveCharacterTextSplitter(chunk_size=4000, chunk_overlap=800)
chunks: List[str] = splitter.split_text(document_text)
```
**Invariant C1.** `chunk_size` is **characters**, not tokens (~4000 ch ≈ 1000
tok). Writes `DocumentSubState["document_chunks"]`. No hand-rolled chunker.

---

## 5. Invocation & Runtime Contract

```
await graph.ainvoke(inputs, config={"max_concurrency": 50})
```
**Invariant I1.** `max_concurrency=50` set only at graph invocation.

### Streamlit bridge
```
import nest_asyncio; nest_asyncio.apply()        # at module load
report = asyncio.get_event_loop().run_until_complete(run_graph(inputs, config))
st.markdown(report)
```
**Invariant I2.** Never `asyncio.run()` inside Streamlit. `nest_asyncio` must be
in `requirements.txt`.

---

## 6. Dataflow Summary (single source of truth)

```
semantic_summary path:
  router_node ──writes──► DocumentSubState["semantic_summary"]
        │                          │
        │           route_matrix_to_workers reads it ──► WorkerPayload.semantic_summary
        │                          │                            │
        │                          ▼                            ▼
        │                   Send(primitive dict) ──► extraction_worker reads payload
        │
        └──(post-workers) handoff_node ──► ParentState["summary_store"][file_name]
                                                  (merge reducer) ──► Master Round-Table

extraction records path:
  extraction_worker ──► DocumentSubState["local_inbox"] (add)
        └─ handoff_node ──► ParentState["global_inbox"] (add) ──► Master Round-Table
```

**The one rule that ties it together:** the summary reaches a worker only by
being stamped into its `WorkerPayload` at dispatch; it reaches the Round-Table
only via the post-workers handoff into `summary_store`. There is no other path,
no parent-state injection into workers, and no pre-fan-out handoff.

---

*Contract Version: 1 (tracks design v11)*
