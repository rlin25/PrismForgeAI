# pipeline.py — Walkthrough

`pipeline.py` is the entire application backend. Every schema, singleton, node, helper
function, graph, and entry point lives here. `app.py` imports only `run_graph` from it.

---

## 1. Purpose

`pipeline.py` exists to express the Dynamic Semantic Topology (DST) Engine as a single,
self-contained LangGraph graph. Its job is:

1. Crawl a directory of corporate documents.
2. Per document: route it (Gemini Flash), chunk it, fan out extraction workers across the
   `chunks × lenses` cross-product (Claude Sonnet), and hand the results off to parent state.
3. Synthesize all extraction records into a cross-referenced Markdown risk report (Claude Sonnet).

The monolith is deliberate. See "Why monolithic" below.

---

## 2. Why Monolithic (Decision 3.17)

A `src/` module tree would split schemas, singletons, nodes, helpers, and graph construction
into separate files. In a 10-hour sprint with no test harness, each module boundary adds import
chain management, potential circular dependency surfaces, and navigation overhead without
improving testability or runtime behavior. A single file is trivially greppable and eliminates
import-order bugs at module initialization. The correct time to decompose is when test coverage
warrants it — not during a sprint.

---

## 3. Relationships

- **Imports from:** `langchain_anthropic`, `langchain_google_genai`,
  `langchain_text_splitters`, `langgraph`, `pydantic`, standard library (`asyncio`, `json`,
  `pathlib`, `operator`).
- **Imported by:** `app.py` (imports only `run_graph`). Nothing else.
- **Deliberately does not touch:** the filesystem outside the user-specified data room path;
  no vector store (Invariant S3); no database; no web requests outside LLM API calls; no
  direct threading (`app.py` handles the ThreadPoolExecutor bridge; `pipeline.py` uses only
  asyncio internally).

---

## 4. Section-by-Section Rationale

### 4.1 Pydantic Schemas

Five schemas are defined. Their purpose is not validation for its own sake but to enforce
structural contracts at two specific boundaries:

- **`RouterOutput`** is the binding target for `structured_router`. It exists because the
  router must produce both a semantic summary and a lens list in one API call (Decision 3.15,
  Invariant R1). Without a combined structured schema, two separate calls would be needed,
  doubling router latency and creating a partial-failure surface where one call succeeds and
  the other does not.

- **`DependencyLink`** and **`UniversalForm`** together form the binding target for
  `structured_llm`. `DependencyLink` is nested inside `UniversalForm` to force the extraction
  worker to emit typed cross-document references rather than freeform text. Freeform strings
  for cross-document links cannot be programmatically traversed by the synthesis node (Decision
  3.8).

- **`ExtractionRecord`** is the unit of `global_inbox`. It is always a Pydantic object in
  the accumulator, never a raw dict (Invariant X5). This is enforced so that the synthesis
  node can call `.model_dump()` on each record without guarding against heterogeneous types.

- **`WorkerPayload`** is the boundary between `route_matrix_to_workers` and
  `extraction_worker`. It carries `semantic_summary` as a required field (Invariants W2, E4)
  because `extraction_worker` has no state parameter and therefore no other path to the
  summary. All fields are JSON-primitive (Invariant W1) because LangGraph `Send` payloads
  require serializable dicts.

### 4.2 LLM Singletons (Invariant S1)

Four singletons are declared at module scope:

```
router_llm        ChatGoogleGenerativeAI("gemini-2.5-flash")
structured_router router_llm.with_structured_output(RouterOutput)
llm               ChatAnthropic("claude-sonnet-4-20250514")
structured_llm    llm.with_structured_output(UniversalForm)
```

They are at module scope for two reasons. First, re-instantiating a LLM client inside a
node or worker called hundreds of times would add connection-pool creation overhead on every
call. Second, Invariant S1 is a hard constraint: violating it means the singleton optimization
is lost and the module-load side effect (API key validation) runs per-worker instead of once.

`gemini-2.5-flash` is used instead of `gemini-2.0-flash` because `gemini-2.0-flash` is not
available for new Google AI API accounts (Decision 3.21). The model name is the only change;
the API interface and structured output support are identical.

`structured_llm` binds to `UniversalForm`, not to `ExtractionRecord`. The worker constructs
`ExtractionRecord` itself from the `UniversalForm` result. This means the LLM is responsible
only for the extraction content; the worker supplies the surrounding metadata (lens name,
source file, chunk index).

No module-level `asyncio.Semaphore` exists (Invariant S2). A semaphore at module scope raises
`RuntimeError: got Future attached to a different loop` when LangGraph initializes its own event
loop. Concurrency is controlled at graph invocation time via `max_concurrency=50` (Invariant I1).

### 4.3 Chunker Singleton (Invariant C1)

```python
splitter = RecursiveCharacterTextSplitter(chunk_size=4000, chunk_overlap=800)
```

The singleton is at module scope for the same reason as the LLM singletons: creating it once
avoids repeated initialization. `chunk_size=4000` is in characters, not tokens. English prose
averages ~4 characters per token, so 4000 characters targets approximately 1000 tokens per
chunk, matching the design spec's stated target. Setting `chunk_size=1000` would produce
~250-token chunks — undersized for the extraction task. The 20% overlap (`chunk_overlap=800`)
ensures that findings that span a chunk boundary are not split across two worker calls with
neither side having enough context.

`RecursiveCharacterTextSplitter` is used instead of a custom chunker because it handles
mid-sentence boundary cases correctly and its edge cases are well-tested. Writing a sliding
window chunker from scratch would consume sprint hours with no quality benefit (Decision 3.5).

### 4.4 State Schemas

#### ParentState

`ParentState` is the only LangGraph state schema in the graph. It has five fields:

- **`directory_path`** — read-only input; set at invocation, never written again.
- **`crawled_files`** — no reducer (Invariant P2). It is written exactly once by
  `directory_crawler` before any sub-graph runs. If it had an `add` reducer, a bug that
  wrote to it a second time would silently append duplicates rather than raising an error.
- **`summary_store`** — merge reducer `lambda a, b: {**a, **b}` (Invariant P1). When N
  `doc_pipeline` sub-graphs complete in parallel and each propagates
  `{"summary_store": {file_name: summary}}`, LangGraph calls the reducer once per completion to
  merge the new single-key dict into the accumulating parent dict. Without the merge reducer,
  the default overwrite behavior would mean only the last sub-graph to complete would have its
  summary survive.
- **`global_inbox`** — `operator.add` reducer. Same logic: N parallel sub-graph completions,
  each contributing a list of `ExtractionRecord` objects, are accumulated via list
  concatenation.
- **`master_risk_report`** — no reducer; written exactly once by `master_round_table_node`.

#### DocumentSubState — The Sub-Graph State Schema

`DocumentSubState` is passed to `StateGraph(DocumentSubState)` to build the `doc_pipeline`
sub-graph. It is the live state schema for each per-document sub-graph execution — checkpointed,
reduced, and propagated by LangGraph at runtime.

Its fields fall into two categories:

**Internal fields** — used within the sub-graph and not propagated to the parent:
`source_material`, `file_name`, `semantic_summary`, `dynamic_topology`, `document_chunks`,
`local_inbox`.

**Output fields** — written by `handoff_node` and propagated to `ParentState` when the
sub-graph completes:
- `global_inbox: Annotated[List[ExtractionRecord], add]` — matches the same key and reducer in
  `ParentState`, so LangGraph accumulates records from parallel sub-graphs via `operator.add`.
- `summary_store: Annotated[Dict[str, str], lambda a, b: {**a, **b}]` — matches the same key
  and merge reducer in `ParentState`, so parallel sub-graph summaries accumulate rather than
  overwriting each other (Invariant P1).

The `gap_detected` and `blind_spots` fields that appeared in an earlier version of the spec
are intentionally absent. Blind spot detection was demoted from a LangGraph state field to a
pure Python function in Decision 3.16 (Invariant M3).

---

### 4.5 The Sub-Graph Architecture (Decision 3.18 Revisited) — Spec-Compliant Implementation

The design spec described a sub-graph per document: `StateGraph(DocumentSubState)` with
`router_node`, a chunk node, `route_matrix_to_workers` as a conditional edge, extraction
workers dispatched via LangGraph `Send`, and `handoff_node` — all as distinct LangGraph nodes
within each sub-graph. `pipeline.py` implements this exactly.

The parent graph has three nodes:

```
directory_crawler → doc_pipeline (dispatched N times via Send) → master_round_table_node
```

`doc_pipeline` is a compiled `StateGraph(DocumentSubState)` sub-graph with the following
internal topology:

```
START → router_node → chunk_node
chunk_node --[route_matrix_to_workers conditional edge]--> extraction_worker
extraction_worker → handoff_node → END
```

`dispatch_subgraphs` (the parent conditional edge) emits one
`Send("doc_pipeline", initial_DocumentSubState)` per crawled file. LangGraph runs the
resulting sub-graph executions with up to `max_concurrency=50` in parallel.

**State propagation across the sub-graph boundary:** `DocumentSubState` declares
`global_inbox` and `summary_store` as output fields with reducers that match `ParentState`.
When each sub-graph completes, LangGraph detects these overlapping keys and applies the parent
reducers — accumulating extraction records via `operator.add` and summaries via the merge
reducer `lambda a, b: {**a, **b}`. This is the mechanism that allows parallel sub-graphs to
contribute to a shared parent inbox without race conditions.

**Why this works now:** The key requirement is that `DocumentSubState` declares
`global_inbox` and `summary_store` as annotated output fields with matching reducers. With
those declarations in place, LangGraph's sub-graph channel scoping propagates them to the
parent reliably. Decision 3.18 (recorded in DESIGN.md) documents the earlier flat
architecture and the rationale for the rewrite.

---

### 4.6 System Prompt Constants

Three module-level constants define the LLM call shapes:

- **`ROUTER_SYSTEM_PROMPT`** — instructs `gemini-2.5-flash` to produce a `RouterOutput`
  object. It lists valid lens names to constrain `dynamic_topology`. Single call per document
  per Invariant R1. The lens name list is in the system prompt rather than constructed
  dynamically so that the constant is stable and the router call has consistent behavior across
  different documents.

- **`EXTRACTION_SYSTEM_PROMPT`** — instructs `claude-sonnet-4-20250514` to extract one
  `UniversalForm`-shaped finding. It does not include the lens name because the lens is
  injected into the user-side of the anchored prompt (the `anchored_prompt` string assembled
  inside `extraction_worker`). Keeping the lens out of the system prompt means
  `EXTRACTION_SYSTEM_PROMPT` is reused across all workers without modification — a single
  constant drives all extraction calls regardless of lens (Decision 3.20).

- **`SYNTHESIS_SYSTEM_PROMPT`** — instructs `claude-sonnet-4-20250514` to produce a
  free-form Markdown report. It uses `llm` (not `structured_llm`) because the synthesis output
  is unconstrained Markdown, not a `UniversalForm`. A required report structure is embedded in
  the prompt rather than enforced via schema because the synthesis sections (Executive Summary,
  Critical Findings, Contradictions, etc.) do not map cleanly to a fixed Pydantic shape.

---

### 4.7 `detect_blind_spots` (Pure Function)

```python
def detect_blind_spots(crawled_files, global_inbox) -> List[str]:
    covered = {record.source_file for record in global_inbox}
    return [f for f in crawled_files if f not in covered]
```

This function exists because the design spec included a `[ Blind Spot Discovery ]` graph node
in the topology diagram but defined no implementation for it. Decision 3.16 demoted it to a
Python filter in the Round-Table preamble (Invariant M3).

A file appears in `crawled_files` but not in `global_inbox` when: it was an empty document,
all its chunks failed extraction (worker exceptions returning `{"local_inbox": []}`), or the
crawler read it but all workers produced no records. The function is deterministic and has no
side effects — it is testable independently of the graph.

The `blind_spot_block` string that the function's output generates is prepended to the
synthesis prompt so that the LLM explicitly acknowledges coverage gaps in the report, rather
than silently omitting files that produced no findings.

---

### 4.8 `compress_inbox` (Pure Function)

```python
def compress_inbox(global_inbox, limit=500) -> Tuple[List[ExtractionRecord], str]:
```

This function exists to prevent the synthesis prompt from exceeding the practical coherence
ceiling of frontier models. The 500-record threshold corresponds to approximately 15 files at
typical extraction density (7 chunks × 5 lenses = 35 workers per file). Above ~1000 records
the synthesis prompt approaches the limit where cross-reference tracking degrades even on
200k-context models.

When truncation occurs, records are sorted descending by `implied_liability_score` so that
high-risk signals are preserved. The returned `truncation_warning` string is a Markdown
section prepended to the synthesis prompt, informing the LLM (and by extension the analyst
reading the report) that low-priority records were dropped (Invariant M2). Passing the raw
`global_inbox` to synthesis without this guard would produce an unpredictable failure when
document count grows — either a context overflow error or a degraded report with no warning.

---

### 4.9 `route_matrix_to_workers` (LangGraph Conditional Edge, Invariants E1–E4)

`route_matrix_to_workers` is a LangGraph conditional edge registered in `doc_pipeline` with
the spec-compliant signature:

```python
def route_matrix_to_workers(state: DocumentSubState) -> List[Send]:
```

It receives the full `DocumentSubState` (Invariant E1 — single parameter only). `semantic_summary`
is always present at the time this edge fires because `router_node` runs earlier in the same
sub-graph execution and writes it into `DocumentSubState` (Invariant E2).

The function constructs the full `chunks × dynamic_topology` cross-product and returns one
`Send("extraction_worker", worker_config.model_dump())` per combination. LangGraph then
dispatches each `Send` as an independent `extraction_worker` node invocation within the
sub-graph.

**Why `.model_dump()` (Invariant E3):** Each `WorkerPayload` is constructed to validate the
fields, then immediately serialized to a primitive dict via `.model_dump()` before being placed
in the `Send`. LangGraph `Send` payloads must be JSON-primitive-serializable — passing a Pydantic
instance directly is not guaranteed to work and may produce silent serialization errors. The
primitive dict boundary is explicit: after `.model_dump()`, the data is a plain Python dict.
`extraction_worker` reconstructs a `WorkerPayload` from it on entry to re-validate.

**Why `semantic_summary` is stamped at dispatch time (Invariant E4):** The summary is
resolved once per document (one router call) and stamped into every payload in the fan-out
batch. This is the only channel by which a worker receives the summary — `extraction_worker`
has no state parameter (Invariant X1) and LangGraph does not inject sub-graph state into
`Send`-dispatched nodes. Stamping at dispatch time means the summary is carried in the
payload only; it does not create a separate LangGraph channel write for each of the N workers.

---

### 4.10 `extraction_worker` (Async Function)

```python
async def extraction_worker(payload_dict: Dict[str, Any]) -> Dict[str, Any]:
```

This function satisfies five invariants. Each constraint exists for a specific reason:

**Invariant X1 — single parameter:** `extraction_worker` takes only `payload_dict`. LangGraph
`Send`-dispatched nodes receive only the `Send` payload — LangGraph does not inject sub-graph
or parent state into them. Adding a `state: DocumentSubState` or `state: ParentState`
parameter would resolve to an empty dict at runtime, causing `summary_store.get()` to always
return `""`. The single-parameter signature is therefore both a correctness requirement and
the only valid calling convention for this node.

**Invariant X2 — summary from payload, never from state:** Follows directly from X1. The
summary must travel inside the payload. See the dispatch-time stamping discussion in §4.9.

**Invariant X3 — `await structured_llm.ainvoke`:** Calling sync `.invoke()` inside an async
LangGraph node blocks the event loop for the duration of the HTTP round-trip, preventing
other concurrently dispatched nodes from making progress. `.ainvoke()` yields at the I/O
boundary; `.invoke()` does not.

**Invariant X4 — entire body in `try/except`:** The `try` block begins before `WorkerPayload`
construction, not after. This is intentional: if `payload_dict` contains an unexpected field
or a field with the wrong type, `WorkerPayload(**payload_dict)` raises a Pydantic
`ValidationError`. If the try block started after construction, that error would propagate
and crash the worker node. One worker failure — from any cause, including a malformed payload,
a provider API error, or a Pydantic validation error on the LLM's response — must return
`{"local_inbox": []}` so the remaining workers in the sub-graph complete normally. The file
will appear in `detect_blind_spots` output if all workers for that file fail.

**Invariant X5 — returns `ExtractionRecord`, not raw dict:** The `local_inbox` accumulator
in `ParentState` has type `List[ExtractionRecord]`. Inserting raw dicts would break the
`.model_dump()` call in `master_round_table_node` and the `source_file` attribute access in
`detect_blind_spots`.

---

### 4.11 `directory_crawler` Node

This node exists entirely to satisfy Invariant P2: `crawled_files` must be written once,
before any document processing begins. It performs a defensive read loop that silently skips
binary files, subdirectories, and files with permission errors (Decision 3.6). Crashing on a
`.DS_Store` or system metadata file at the first node of the graph would block the entire
pipeline.

The node reads each file and discards the content — it returns only the list of filenames.
File content is re-read by `dispatch_subgraphs` later. This is a deliberate trade-off:
`crawled_files` is specified as `List[str]` (filenames only), not `Dict[str, str]`, so
`detect_blind_spots` can match on filename strings. Re-reading the content at dispatch time
adds one extra I/O pass per file but keeps the state schema clean.

---

### 4.12 `doc_pipeline` Sub-Graph — Per-Document Processing

`doc_pipeline` is the compiled `StateGraph(DocumentSubState)` sub-graph. It receives a
fully initialized `DocumentSubState` via `Send("doc_pipeline", ...)` from `dispatch_subgraphs`
and propagates `global_inbox` and `summary_store` to `ParentState` when it completes. The
four nodes within it are responsible for:

1. **`router_node`** — one `await structured_router.ainvoke(...)` per document (Invariant R1).
   Writes `semantic_summary` and `dynamic_topology` into `DocumentSubState`. These fields are
   available to all subsequent nodes in the same sub-graph execution.

2. **`chunk_node`** — `splitter.split_text(state["source_material"])` using the module-level
   singleton. Writes `document_chunks` into `DocumentSubState`.

3. **`extraction_worker`** (×N, dispatched via `Send` from `route_matrix_to_workers`) — one
   `await structured_llm.ainvoke(...)` per chunk × lens combination. Each worker writes a
   single `ExtractionRecord` to `DocumentSubState["local_inbox"]` via the `operator.add`
   reducer. Invariant X4 ensures exceptions are caught inside each worker, returning
   `{"local_inbox": []}` on failure so one failed worker cannot block others.

4. **`handoff_node`** — the single atomic handoff per sub-graph (Invariants H1, H2). Fires
   after all `extraction_worker` nodes complete. Writes:
   ```python
   {
       "global_inbox": sub_state["local_inbox"],
       "summary_store": {sub_state["file_name"]: sub_state["semantic_summary"]},
   }
   ```
   There is no pre-fan-out handoff. Workers receive the summary from their `WorkerPayload`,
   not from `ParentState["summary_store"]`. The Round-Table node reads `summary_store` only
   after all sub-graphs complete, so writing it post-workers is always in time.

---

### 4.13 `master_round_table_node` — Preamble Before Synthesis

This node runs once, after all `process_document` nodes complete. Its preamble is ordered for
a specific reason:

**Why `detect_blind_spots` runs before `compress_inbox`:** Blind spots are detected from
`crawled_files` vs `global_inbox` — the full, uncompressed inbox. Running `detect_blind_spots`
after `compress_inbox` would mean a file with only low-scoring records might have all its
records dropped by compression, causing it to appear as a false blind spot. Detecting blind
spots on the raw inbox guarantees the result is based on actual extraction coverage, not
on the compressed subset passed to synthesis.

**Why `compress_inbox` runs before serialization:** The synthesis prompt is built from the
compressed record set. Passing the raw `global_inbox` to `json.dumps` when it exceeds 500
records would produce a prompt that approaches or exceeds the synthesis LLM's practical
coherence ceiling. The 500-record guard is the contract boundary between variable-size
extraction output and the fixed-context synthesis call (Invariant M2, Decision 3.10).

**Why `llm.ainvoke` (not `structured_llm.ainvoke`) for synthesis:** The synthesis output is
free-form Markdown with a defined narrative structure. Constraining it to a Pydantic schema
would require either an extremely complex schema (mirroring the full report structure) or
accepting a schema that the LLM must partially serialize to, losing the natural prose quality
of the report. `llm.ainvoke` returns an `AIMessage`, and the `content` field can be either
`str` or `List[dict]` depending on the provider and model version. The node handles both cases
explicitly (Decision 3.20) rather than assuming one format.

**Why single-shot synthesis (Invariant M1):** Map-reduce hierarchical aggregation would require
per-group summarization calls, sub-summary accumulation, and a final orchestration call —
adding LangGraph routing complexity for a step that frontier models can handle in a single
200k-context call at the expected data volume. The `compress_inbox` guard extends the
single-shot paradigm to handle larger document sets without adding complexity (Decision 3.10).

---

### 4.14 `dispatch_subgraphs` (Conditional Edge)

This function emits one `Send("doc_pipeline", initial_DocumentSubState)` per filename in
`crawled_files`. The `initial_DocumentSubState` is a fully initialized dict with empty
accumulator fields (`local_inbox: []`, `global_inbox: []`, `summary_store: {}`). It
re-reads file content here because `crawled_files` is `List[str]` (filenames only) per the
contract spec — the file text was not stored in state by `directory_crawler`. This is the
only conditional edge registered with the parent LangGraph builder. (Previously named
`dispatch_documents` in earlier implementation versions.)

---

### 4.15 Graph Construction

There are two graph compilation steps. First, the sub-graph:

```python
_sub_builder = StateGraph(DocumentSubState)
_sub_builder.add_node("router_node", router_node)
_sub_builder.add_node("chunk_node", chunk_node)
_sub_builder.add_node("extraction_worker", extraction_worker)
_sub_builder.add_node("handoff_node", handoff_node)
_sub_builder.add_edge(START, "router_node")
_sub_builder.add_edge("router_node", "chunk_node")
_sub_builder.add_conditional_edges("chunk_node", route_matrix_to_workers, ["extraction_worker"])
_sub_builder.add_edge("extraction_worker", "handoff_node")
_sub_builder.add_edge("handoff_node", END)
doc_pipeline = _sub_builder.compile()
```

Then the parent graph, with `doc_pipeline` registered as a node:

```
START → directory_crawler
directory_crawler --[dispatch_subgraphs conditional edge]--> doc_pipeline
doc_pipeline → master_round_table_node
master_round_table_node → END
```

`dispatch_subgraphs` returns a list of `Send` objects. LangGraph interprets a list return from
a conditional edge as a fan-out: it dispatches one `doc_pipeline` sub-graph execution per
`Send`, all running concurrently (up to `max_concurrency`). When all `doc_pipeline`
executions complete, LangGraph advances to `master_round_table_node`.

---

### 4.16 `run_graph` — The Entry Point

```python
async def run_graph(directory_path: str) -> str:
```

This is the only symbol imported by `app.py`. It initializes a `ParentState` with empty
defaults for the accumulator fields (`summary_store: {}`, `global_inbox: []`,
`master_risk_report: ""`), sets `max_concurrency=50` (Invariant I1), invokes the graph, and
returns `master_risk_report`.

`run_graph` is an async function, not a synchronous wrapper around `asyncio.run()`. The
caller (`app.py`) is responsible for the event loop bridge via `ThreadPoolExecutor` and
`asyncio.new_event_loop()`. `asyncio.run()` cannot be called inside Streamlit's callback,
and `nest_asyncio` is insufficient under LangGraph's concurrent Send dispatch. The solution
is in `app.py`, not here (Invariant I2, Decision 3.23).

---

## 5. What `pipeline.py` Does NOT Do

- Does not render any UI. No Streamlit imports.
- Does not manage API keys. They are injected as environment variables by the container
  runtime or the shell; `langchain_anthropic` and `langchain_google_genai` read them
  automatically from `ANTHROPIC_API_KEY` and `GOOGLE_API_KEY`.
- Does not write any output files. The report is a return value, not a written artifact.
- Does not use a vector store (Invariant S3). Chunking is string-based via
  `RecursiveCharacterTextSplitter`; retrieval is not needed because every chunk is processed
  by every applicable lens.
- Does not implement streaming to the UI. The synthesis response is collected in full inside
  `master_round_table_node` before being returned to `app.py`.
- Does not contain any test code. No test files exist in the repository.
- Does not preprocess raw HTML. `preprocess.py` handles EDGAR `.htm` → `.txt` conversion
  before `pipeline.py` is invoked.

---

## 6. v5 Touch Points

- **Streaming synthesis:** `master_round_table_node` calls `llm.ainvoke` and collects the
  full response. v5 would switch to `llm.astream` and yield tokens back through `run_graph`
  to `app.py` for incremental Streamlit rendering. This requires changing `run_graph`'s return
  type from `str` to an async generator and changing how `app.py` consumes it.
- **Module decomposition:** When test coverage warrants it: `src/schemas.py` for Pydantic
  models, `src/nodes.py` for node functions, `src/graph.py` for graph construction and
  `run_graph`, `src/prompts.py` for the three system prompt constants. `app.py` imports only
  `run_graph` so the `app.py`/`pipeline.py` boundary is unchanged.
- **`aiohttp` pin:** `aiohttp>=3.13.5` should be added to `requirements.txt` (see
  `docs/DESIGN.md` §3.22). The current file omits this, requiring a runtime upgrade after
  container start.
- **Concurrency tuning:** `max_concurrency=50` is set by convention from the design spec.
  Under production load, the correct value depends on provider rate limits and document
  density. A configurable parameter (e.g., via environment variable) would make this
  tunable without code changes.
