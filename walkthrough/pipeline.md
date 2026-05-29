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
  threading (only asyncio).

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
  summary. All fields are JSON-primitive (Invariant W1) because LangGraph `Send` — and by
  extension `asyncio.gather` with these same dicts — requires serializable payloads.

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
  `directory_crawler` before any document processing begins. If it had an `add` reducer, a
  bug that wrote to it a second time would silently append duplicates rather than raising an
  error.
- **`summary_store`** — merge reducer `lambda a, b: {**a, **b}` (Invariant P1). When N
  `process_document` nodes run in parallel and each returns
  `{"summary_store": {file_name: summary}}`, LangGraph calls the reducer once per return to
  merge the new single-key dict into the accumulating parent dict. Without the merge reducer,
  the default overwrite behavior would mean only the last process_document to complete would
  have its summary survive. This is the only place where the parallel execution model touches
  `summary_store`.
- **`global_inbox`** — `operator.add` reducer. Same logic: N parallel returns, each
  contributing a list of `ExtractionRecord` objects, are accumulated via list concatenation.
- **`master_risk_report`** — no reducer; written exactly once by `master_round_table_node`.

#### DocumentSubState — A Documentation Artifact

`DocumentSubState` is defined as a TypedDict in `pipeline.py` but is **not passed to
`StateGraph()`**. No LangGraph sub-graph exists that uses it as its state schema. It is never
passed to a checkpoint, never has reducers applied to it at runtime, and never crosses a
LangGraph state boundary.

It exists for two reasons. First, it documents the per-document field surface that was
described in the design spec — if a future v5 refactor introduces true LangGraph sub-graphs,
this TypedDict is ready to become the sub-graph state schema. Second, it serves as a type
reference for the fields that `process_document` uses as local variables internally: the
`source_material`, `file_name`, `semantic_summary`, `dynamic_topology`, `document_chunks`,
and `local_inbox` variables inside `process_document` correspond directly to `DocumentSubState`
fields, making the correspondence to the design spec readable.

The `gap_detected` and `blind_spots` fields that appeared in an earlier version of the spec
are intentionally absent. Blind spot detection was demoted from a LangGraph state field to a
pure Python function in Decision 3.16 (Invariant M3).

---

### 4.5 The Flat Graph Architecture (Decision 3.18) — The Most Non-Obvious Decision

The design spec described a sub-graph per document: `StateGraph(DocumentSubState)` with
`router_node`, a chunk node, `route_matrix_to_workers` as a conditional edge, extraction
workers dispatched via LangGraph `Send`, and `handoff_node` — all as distinct LangGraph nodes
within each sub-graph. The implementation does none of this.

The actual graph has three nodes:

```
directory_crawler → process_document (dispatched N times via Send) → master_round_table_node
```

`process_document` is a single async LangGraph node. All per-document logic — routing,
chunking, fan-out matrix construction, the worker pool, and the handoff return — runs
sequentially in Python inside it.

**Why sub-graphs were abandoned:** LangGraph sub-graph state propagation requires explicit key
mapping between child state schema and parent state schema at sub-graph exit. For
`global_inbox` (a list with an `add` reducer) and `summary_store` (a dict with a merge
reducer), implementing this reliably requires understanding LangGraph's internal sub-graph
channel scoping rules, which are non-obvious and have changed across minor versions. The risk
is silent data loss: a mis-scoped key produces no runtime error but drops all records from the
affected document. In a sprint context with no test harness, that silent failure mode is
unacceptable.

The flat architecture eliminates the sub-graph boundary entirely. `process_document` returns a
plain Python dict, and LangGraph applies the ParentState reducers directly. The reducers are
exercised on every return from every `process_document` invocation — identically to how they
would work at a sub-graph handoff, but without the scoping complexity.

All 12 non-negotiable invariants are satisfied by the flat implementation. The structural
difference is invisible at the invariant level. The sub-graph architecture remains the correct
upgrade path if LangGraph's sub-graph state propagation API stabilizes with clear contracts
for reducer scoping.

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

### 4.9 `route_matrix_to_workers` (Pure Function, Not a LangGraph Edge)

The design spec defined `route_matrix_to_workers` as a LangGraph conditional edge function
with signature `def route_matrix_to_workers(state: DocumentSubState) -> List[Send]`. The
implementation has a different signature:

```python
def route_matrix_to_workers(
    file_name: str,
    document_chunks: List[str],
    dynamic_topology: List[str],
    semantic_summary: str,
) -> List[Dict[str, Any]]:
```

It returns `List[Dict[str, Any]]` (primitive dicts) rather than `List[Send]` because it is
not registered with the LangGraph builder. It is called directly from inside `process_document`
as a plain Python function.

**Why a pure function rather than a conditional edge:** Because there is no sub-graph, there
is no conditional edge to register. `route_matrix_to_workers` was extracted as a standalone
function (rather than inlined) to keep `process_document` readable and to preserve testability
of the cross-product logic independently of the async graph machinery.

**Why explicit parameters instead of a state dict:** The original `state: DocumentSubState`
single-parameter signature was required because LangGraph conditional edge functions receive
only one argument. Since this function is no longer a LangGraph edge, the constraint is
lifted. Explicit parameters make the function's dependencies readable without inspecting the
body and prevent accidental reads of fields not listed in the signature.

**Why `.model_dump()` (Invariant E3):** Each `WorkerPayload` is constructed to validate the
fields, then immediately serialized to a primitive dict via `.model_dump()`. The dicts are
passed to `asyncio.gather`, which does not require Pydantic serialization; but this practice
is retained from the original LangGraph `Send` design where primitive dicts are mandatory.
Keeping `.model_dump()` here makes the boundary explicit: after this point, the data is a
plain Python dict. `extraction_worker` reconstructs a `WorkerPayload` from it on entry to
re-validate (the round-trip through dict also catches any field name drift between the two
functions).

**Why `semantic_summary` is stamped at dispatch time (Invariant E4):** The summary is
resolved once per document (one router call) and stamped into every payload in the fan-out
batch. This is the only channel by which a worker receives the summary — `extraction_worker`
has no state parameter (Invariant X1) and cannot read from `ParentState`. Stamping at
dispatch time also means the summary is carried in volatile memory only (assembled as a string
inside the worker) rather than written to a LangGraph channel for each of the N workers,
avoiding heap bloat from N×summary duplicates in the checkpoint ledger (Decision 3.2).

---

### 4.10 `extraction_worker` (Async Function)

```python
async def extraction_worker(payload_dict: Dict[str, Any]) -> Dict[str, Any]:
```

This function satisfies five invariants. Each constraint exists for a specific reason:

**Invariant X1 — single parameter:** `extraction_worker` takes only `payload_dict`. In the
original LangGraph `Send` design, `Send`-dispatched nodes do not receive the parent graph
state — LangGraph injects only the Send payload. Adding a `state: ParentState` parameter
would resolve to an empty dict at runtime, causing `summary_store.get()` to always return
`""`. Even in the flat `asyncio.gather` design, the function is called with only `payload_dict`
— there is no injection mechanism for a second parameter.

**Invariant X2 — summary from payload, never from state:** Follows directly from X1. The
summary must travel inside the payload. See the dispatch-time stamping discussion in §4.9.

**Invariant X3 — `await structured_llm.ainvoke`:** Calling sync `.invoke()` inside an async
worker blocks the entire event loop for the duration of the HTTP round-trip, serializing all
concurrent workers. `asyncio.gather` only provides concurrency if all coroutines yield control
at I/O boundaries — `.ainvoke()` yields; `.invoke()` does not.

**Invariant X4 — entire body in `try/except`:** The `try` block begins before `WorkerPayload`
construction, not after. This is intentional: if `payload_dict` contains an unexpected field
or a field with the wrong type, `WorkerPayload(**payload_dict)` raises a Pydantic
`ValidationError`. If the try block started after construction, that error would propagate
and crash the `asyncio.gather` pool. One worker failure — from any cause, including a
malformed payload, a provider API error, or a Pydantic validation error on the LLM's response
— must return `{"local_inbox": []}` so the remaining workers in the batch complete normally.
The file will appear in `detect_blind_spots` output if all workers for that file fail.

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
File content is re-read by `dispatch_documents` later. This is a deliberate trade-off:
`crawled_files` is specified as `List[str]` (filenames only), not `Dict[str, str]`, so
`detect_blind_spots` can match on filename strings. Re-reading the content at dispatch time
adds one extra I/O pass per file but keeps the state schema clean.

---

### 4.12 `process_document` Node — The Inlined Sub-Graph

`process_document` is the most structurally significant node. It receives `{source_material,
file_name}` via LangGraph `Send` from `dispatch_documents` and returns `{"global_inbox": [...],
"summary_store": {...}}` directly to `ParentState` via the reducers. Between those two
boundaries, it is responsible for:

1. **Router call** — one `await structured_router.ainvoke(...)` per document (Invariant R1).
   Returns `RouterOutput` with `semantic_summary` and `dynamic_topology` as local variables.
   The result is never written to a LangGraph channel — it lives in the function's stack frame
   until used.

2. **Chunking** — `splitter.split_text(source_material)` using the module-level singleton.

3. **Fan-out matrix** — `route_matrix_to_workers(...)` called as a plain function with
   explicit arguments. Returns `List[Dict[str, Any]]`.

4. **Worker pool** — `asyncio.gather(*[extraction_worker(p) for p in payloads],
   return_exceptions=True)`. `return_exceptions=True` means if a coroutine raises an
   unhandled exception (one not caught inside `extraction_worker`'s own `try/except`), it
   appears as an exception object in the results list and is filtered out during collection
   rather than canceling the entire gather. In practice, Invariant X4 ensures exceptions are
   caught inside the worker, but `return_exceptions=True` is an additional safety layer.

5. **Handoff return** — the single atomic return dict (Invariants H1, H2). There is no
   pre-fan-out handoff. The summary and local inbox are written to parent state in the same
   return, after all workers have completed. A pre-fan-out handoff would have been needed if
   `summary_store` had to be populated before workers ran — but workers receive the summary
   from their payload, not from `ParentState["summary_store"]`. The Round-Table node, which
   reads `summary_store`, runs only after all `process_document` nodes complete. So writing
   `summary_store` post-workers is always in time.

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

### 4.14 `dispatch_documents` (Conditional Edge)

This function emits one `Send("process_document", {source_material, file_name})` per filename
in `crawled_files`. It re-reads file content here because `crawled_files` is `List[str]`
(filenames only) per the contract spec — the file text was not stored in state by
`directory_crawler`. This is the only edge function registered with the LangGraph builder.

---

### 4.15 Graph Construction

The graph has three nodes and the edges that connect them:

```
START → directory_crawler
directory_crawler --[dispatch_documents conditional edge]--> process_document
process_document → master_round_table_node
master_round_table_node → END
```

`dispatch_documents` returns a list of `Send` objects. LangGraph interprets a list return from
a conditional edge as a fan-out: it dispatches one `process_document` node execution per
`Send`, all running concurrently (up to `max_concurrency`). When all `process_document`
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
caller (`app.py`) is responsible for the event loop bridge. `asyncio.run()` cannot be called
inside Streamlit because Streamlit manages its own running event loop — doing so raises
`RuntimeError: This event loop is already running`. The solution is in `app.py`, not here
(Invariant I2, Decision 3.11).

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

---

## 6. v5 Touch Points

- **Streaming synthesis:** `master_round_table_node` calls `llm.ainvoke` and collects the
  full response. v5 would switch to `llm.astream` and yield tokens back through `run_graph`
  to `app.py` for incremental Streamlit rendering. This requires changing `run_graph`'s return
  type from `str` to an async generator and changing how `app.py` consumes it.
- **True LangGraph sub-graphs:** If LangGraph's sub-graph state propagation API provides
  clear contracts for reducer scoping, `process_document` is the natural candidate for
  refactoring into a `StateGraph(DocumentSubState)` sub-graph. `DocumentSubState` is already
  defined and ready.
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
