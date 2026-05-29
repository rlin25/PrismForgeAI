# GLOSSARY — PrismForge AI v4 (Post-Implementation Reference)

> This glossary is organized into three parts for two audiences.
> Part 1 is written for nontechnical readers (recruiters, investors, business reviewers).
> Parts 2 and 3 are written for developers returning to the codebase.
> All invariant identifiers (S1, W1, P1, R1, E1–E4, X1–X5, D1, H1–H2, M1–M3,
> C1, I1–I2) cross-reference binding constraints defined in INTERFACE_CONTRACT.md.

---

## Part 1 — Domain and System Overview

### What the System Does

PrismForge AI v4 is a corporate due diligence analysis engine. A user points it at
a folder of documents (a "data room") and receives a structured Markdown risk report.
The system reads every file, decides which legal and business risk categories apply to
each document, extracts evidence-backed findings, and synthesizes all findings into a
single cross-referenced report. The entire pipeline runs automatically with no human
review step between ingestion and output.

---

### Domain Terms

**data room**
A collection of documents assembled for review during a transaction or investment
process. In the context of PrismForge AI, the data room is a local directory on disk
whose path the user provides as input. The system reads every file in that directory.

**due diligence**
The structured investigation a buyer, investor, or acquirer conducts before
completing a transaction. The goal is to identify risks — legal, financial, technical,
and operational — that the seller has not voluntarily disclosed. PrismForge AI
automates the reading and risk-flagging step of this process.

**liability**
A legal or financial obligation owed by one party to another. In due diligence,
reviewers look for clauses that create unexpected liabilities: situations where the
target company could owe money, be subject to injunctions, or face regulatory
penalties after the deal closes.

**indemnification**
A contractual promise by one party to compensate the other for specific losses. For
example, a vendor contract might require the target company to pay a customer's legal
costs if a product defect causes harm. Indemnification clauses are flagged because
they transfer financial risk to the indemnifying party.

**warranty**
A contractual assertion that a stated fact is true. In software and IP transactions,
the seller typically warrants that it owns the code it is selling and that the code
does not infringe third-party rights. A false warranty can void a deal or create
post-closing liability.

**IP ownership**
The question of who legally owns the intellectual property in a product or codebase.
Disputes arise when contractors, open-source contributors, or prior employers have
unassigned rights. A due diligence review checks employment agreements, contractor
agreements, and IP assignment records to confirm clean ownership.

**license compliance**
Whether the target company's products comply with the terms of every software license
they depend on. Open-source licenses (GPL, AGPL, LGPL, MIT, Apache) impose different
conditions on distribution and commercial use. A GPL-licensed dependency in a
proprietary product can create an obligation to open-source the entire product.

**liability cap**
A contractual ceiling on the maximum damages one party can owe to the other under
the agreement. Liability caps limit downside risk but also limit the buyer's remedy
if something goes wrong after closing. Reviewers flag caps that are lower than the
deal value.

**data privacy**
The obligations a company has regarding personal data it collects, stores, or
processes. Relevant regulations include GDPR (European Union), CCPA (California), and
sector-specific rules. Non-compliance can result in regulatory fines and reputational
damage. PrismForge AI flags clauses and disclosures related to data handling
obligations.

**counterparty**
The other party in a contract or transaction. Understanding counterparty risk means
asking whether the other party can fulfill their obligations and whether contractual
terms adequately protect against their failure to do so.

**cross-reference / contradiction**
A finding where a claim, right, or obligation in one document conflicts with or
modifies a claim in another document. For example, a confidentiality agreement might
grant narrower IP rights than the employment contract for the same employee.
PrismForge AI explicitly tracks these cross-document links as structured
`DependencyLink` objects and surfaces them in the final report.

---

### System Concepts

**lens**
A named risk-extraction category that the system applies to a document. Each lens
represents a specific domain of due diligence concern. Examples: `IP_Ownership`,
`License_Compliance`, `Liability_Cap`, `Indemnification`, `Change_of_Control`,
`Data_Privacy`, `Employment_Obligations`, `Revenue_Share`, `Regulatory_Approval`,
`IP_Warranty`. Lenses are not a fixed list — the router assigns 3 to 7 lenses per
document based on the document's actual content. This makes the extraction set dynamic
rather than uniform across all files. This property is called Dynamic Semantic
Topology (DST).

**semantic summary**
A 200–400 word dense profile of a single document produced by the router step. It
captures key entities, contractual obligations, and risk domains at the
whole-document level. The semantic summary is not displayed to the user directly.
Its primary role is to give each extraction worker full-document context even when
that worker is operating on a small text chunk. It is also archived in `summary_store`
so the Master Round-Table Node can reference which documents were analyzed. Governed
by Invariant W2: the summary reaches a worker only by being stamped into its payload
at dispatch time — there is no other delivery path.

**extraction record**
The output of one extraction worker operating on one chunk of one document under one
lens. Each record contains: the lens name, the source filename, the chunk index, a
verbatim evidence quote, a risk score (1–10), and any cross-document dependency
links. Extraction records are the atomic unit of analysis that feeds into the final
report. They accumulate in `global_inbox` via an append reducer.

**risk score (implied_liability_score)**
An integer from 1 to 10 assigned by the extraction worker to each finding.
9–10 = existential or critical risk; 7–8 = major risk; 5–6 = significant risk;
3–4 = moderate risk; 1–2 = minor or informational. The synthesis step orders
findings by score and never omits any finding with a score of 7 or above. When the
total number of extraction records exceeds 500, lower-scoring records are dropped
first (see `compress_inbox`).

**blind spot**
A file that was crawled and read successfully by the directory crawler but produced
zero extraction records. This indicates the file contained no machine-readable
risk-relevant content under any assigned lens — for example, a binary embedded in a
text-readable wrapper, an empty file, or a document for which all extraction workers
failed. Blind spots are detected by `detect_blind_spots()` and reported explicitly in
the Coverage Gaps section of the final report so a human reviewer knows which files
were not analyzed. Governed by Invariant M3: blind-spot detection is a Python filter,
not a graph node.

---

## Part 2 — Architecture and Execution

### Pipeline Stages in Execution Order

**1. Directory Crawler**
The `directory_crawler` LangGraph node reads `ParentState["directory_path"]` and
attempts to open every file in the directory with UTF-8 encoding. Files that raise
`UnicodeDecodeError`, `IsADirectoryError`, or `PermissionError` are skipped silently
— this is the binary file filter. The output is `crawled_files: List[str]`, a list of
filenames that were successfully read. Written exactly once with no reducer (Invariant
P2). Subdirectories are not recursed; only the top-level directory is scanned.

**2. Router (single combined call — Invariant R1)**
Inside `process_document`, the first step is a single `await structured_router.ainvoke`
call against the full document text. This call produces both `semantic_summary` (a
200–400 word profile) and `dynamic_topology` (a list of 3–7 lens identifiers) in one
shot. Invariant R1 prohibits splitting this into two separate LLM calls. The router
uses `gemini-2.5-flash` via `structured_router`, which is bound to the `RouterOutput`
schema. The result is stored as local variables in `process_document` and used in
all subsequent stages.

**3. Chunking**
After the router completes, the document text is split using
`RecursiveCharacterTextSplitter` with `chunk_size=4000` characters and
`chunk_overlap=800` characters. The overlap ensures that a finding spanning a chunk
boundary is not lost — the 800-character overlap means each chunk shares context with
its neighbors. Chunk size is measured in characters, not tokens (approximately 1,000
tokens per chunk at typical token densities). Governed by Invariant C1: the singleton
`splitter` is used; no hand-rolled chunker is permitted.

**4. Matrix Fan-Out / Chunks x Lenses Cross-Product**
`route_matrix_to_workers` is called with the filename, chunk list, lens list, and
semantic summary. It constructs the full cross-product: every chunk is paired with
every lens, producing `len(chunks) * len(lenses)` worker payloads. Each payload is a
primitive dict (never a Pydantic instance) containing the lens name, source filename,
chunk index, chunk text, and the semantic summary stamped in at dispatch time
(Invariants E3, E4, W1, W2). A document with 5 chunks and 5 lenses produces 25
payloads.

**5. Extraction Worker Pool (asyncio.gather — not LangGraph Send)**
All payloads are executed concurrently via
`asyncio.gather(*[extraction_worker(p) for p in payloads])`. Each `extraction_worker`
call makes one `await structured_llm.ainvoke` call to `claude-sonnet-4-20250514` with
the `UniversalForm` structured output schema. Workers run in parallel within the
document; parallel documents are gated by `max_concurrency=50` at graph invocation
(Invariant I1). Each worker is independently wrapped in a `try/except` that covers
the entire function body including payload construction (Invariant X4). On failure the
worker returns `{"local_inbox": []}` and logs the error — one failed worker cannot
crash the pool or block other workers.

**6. Handoff (inlined in process_document — Invariants H1, H2)**
After `asyncio.gather` completes, `process_document` returns a single dict:
```python
{
    "global_inbox": local_inbox,
    "summary_store": {file_name: router_result.semantic_summary},
}
```
This is the only handoff per document. It fires after all workers complete, never
before fan-out. LangGraph accumulates `global_inbox` via the `operator.add` append
reducer and `summary_store` via the merge reducer `lambda a, b: {**a, **b}`. The
merge reducer is critical for parallel document runs: without it, each document's
handoff would overwrite the previous document's summary (Invariant P1).

**7. Master Round-Table Node**
The terminal synthesis node. Executed once, after all `process_document` invocations
complete. It runs two preamble steps before synthesis:
- `detect_blind_spots(crawled_files, global_inbox)` — identifies files with no records.
- `compress_inbox(global_inbox, limit=500)` — sorts records by `implied_liability_score`
  descending and truncates to 500 if needed (Invariant M2). A truncation warning is
  prepended to the prompt if records were dropped.

The synthesis call is a single `await llm.ainvoke` (no streaming in the graph) that
sends all compressed records to `claude-sonnet-4-20250514` (Invariant M1). The
response is an `AIMessage` whose `.content` field is handled for both `str` and
`list[dict]` cases before being returned as `master_risk_report`.

---

### Architectural Patterns

**process_document node (flat LangGraph node)**
The actual architectural unit for per-document processing. The design specified
LangGraph sub-graphs (`StateGraph(DocumentSubState)`) with `router_node`,
`chunk_node`, and `handoff_node` as distinct LangGraph nodes. The implementation
consolidates all of this into a single async LangGraph node, `process_document`,
which is dispatched once per file via LangGraph `Send` from the `dispatch_documents`
conditional edge. This decision was made to eliminate the complexity of LangGraph
parent-to-child state propagation for `global_inbox` and `summary_store`, which
risked silent data loss at sub-graph boundaries. All behavioral invariants are
satisfied regardless of this structural difference. See INTERFACE_CONTRACT.md
Implementation Deviations, Deviation 1.

**Send dispatch (document-level fan-out)**
LangGraph `Send` is used at the document level: `dispatch_documents` (a LangGraph
conditional edge) returns a list of `Send("process_document", {source_material, file_name})`
objects — one per crawled file. LangGraph runs the resulting `process_document`
invocations with up to `max_concurrency=50` in parallel. Note: `Send` is not used
for worker-level fan-out; that is handled by `asyncio.gather` inside
`process_document`.

**Dynamic Semantic Topology (DST)**
The property that each document receives its own set of extraction lenses, determined
at runtime by the router based on document content. DST is what distinguishes
PrismForge AI v4 from a fixed-lens extractor. The `dynamic_topology` list produced
by the router and the `semantic_summary` that contextualizes each worker are the two
components of DST. Together they ensure that a software license agreement and an
employment contract receive different, content-appropriate analysis lenses.

**Merge reducer on summary_store**
`ParentState["summary_store"]` uses `lambda a, b: {**a, **b}` as its LangGraph
reducer. When multiple `process_document` nodes complete in parallel, each returns
`{"summary_store": {filename: semantic_summary}}`. The merge reducer combines these
into a single dict mapping every filename to its summary. Without this reducer,
parallel handoffs would overwrite one another and only the last document's summary
would survive (Invariant P1).

**Append reducer (add) on global_inbox**
`ParentState["global_inbox"]` uses `operator.add` as its LangGraph reducer. Each
`process_document` handoff appends its `local_inbox` list to the global list.
`DocumentSubState["local_inbox"]` also carries `operator.add` as a reducer annotation
in the TypedDict definition, though `DocumentSubState` is not used as a live LangGraph
state schema (see Part 3).

**Module-level singletons (Invariant S1)**
Four LLM objects are instantiated once at module load and never inside a node, edge
function, or worker: `router_llm` (Gemini), `structured_router` (Gemini with
`RouterOutput` schema), `llm` (Claude), and `structured_llm` (Claude with
`UniversalForm` schema). Re-instantiating these per-call would create a new
authenticated HTTP connection per invocation, adding latency and exhausting API
connection pools. No module-level `asyncio.Semaphore` exists (Invariant S2);
concurrency is governed entirely by `max_concurrency=50`.

**max_concurrency: 50 (Invariant I1)**
Set only at graph invocation: `await graph.ainvoke(inputs, config={"max_concurrency": 50})`.
This limits how many `process_document` nodes run in parallel. It does not limit
workers within a single document — those are all launched simultaneously via
`asyncio.gather`. Setting this value here and only here is the invariant; placing a
semaphore at module scope is a violation.

**Structured output**
Both LLM calls that produce structured data (`structured_router.ainvoke` and
`structured_llm.ainvoke`) use LangChain's `with_structured_output` binding, which
instructs the underlying model to return JSON conforming to the Pydantic schema and
automatically parses the response into the schema instance. This eliminates manual
JSON parsing and format-mismatch errors.

---

### Safety Mechanisms

**Binary file filtering**
`directory_crawler` attempts to open every file with `open(..., encoding="utf-8")`.
Files that raise `UnicodeDecodeError` (binary files, non-UTF-8 files),
`IsADirectoryError` (subdirectory entries), or `PermissionError` (unreadable files)
are silently skipped. The filename is not added to `crawled_files` and no `Send` is
dispatched for it.

**Worker try/except — entire body wrapped (Invariant X4)**
The `try/except` in `extraction_worker` wraps the entire function body, including the
`WorkerPayload(**payload_dict)` construction at the top. A malformed payload dict, a
missing field, or any LLM API error results in `{"local_inbox": []}` being returned
rather than an exception propagating to `asyncio.gather`. A single failed worker
cannot abort the pool or contaminate the state.

**detect_blind_spots()**
A pure deterministic function with no side effects. Signature:
`detect_blind_spots(crawled_files: List[str], global_inbox: List[ExtractionRecord]) -> List[str]`.
Returns the set difference: filenames in `crawled_files` that do not appear in any
`ExtractionRecord.source_file` field. The result is injected into the synthesis
prompt as a Coverage Gaps preamble block so the analyst report explicitly names
unanalyzed files. Governed by Invariant M3: this is a Python filter, not a graph node.

**compress_inbox() — 500-record ceiling**
`compress_inbox(global_inbox, limit=500)` guards against synthesis context-window
overflow. If `len(global_inbox) <= 500`, it returns the list unchanged with an empty
warning string. Otherwise it sorts by `implied_liability_score` descending, keeps the
top 500, and returns a Markdown truncation warning string that is prepended to the
synthesis prompt. The synthesis node receives only the compressed records (Invariant
M2) — it never sees the raw `global_inbox`.

**nest_asyncio bridge (Invariant I2)**
Streamlit runs its own event loop. Calling `asyncio.run()` inside Streamlit raises a
"cannot run nested event loop" error. `nest_asyncio.apply()` at module load patches
the event loop to allow nesting. The graph is then invoked with
`asyncio.get_event_loop().run_until_complete(run_graph(...))`. Using `asyncio.run()`
is a violation.

---

## Part 3 — Implementation Reference

### pipeline.py

All logic lives in the single file `/root/PrismForgeAI/pipeline.py`. There is no
`src/` subdirectory, no test files, and no separate module per concern.

---

**RouterOutput** (Pydantic BaseModel)
Produced by `structured_router` in a single call per document (Invariant R1).
Fields:
- `semantic_summary: str` — 200–400 word dense document profile.
- `dynamic_topology: List[str]` — 3–7 lens identifiers for this document.

Both fields are populated in the same call. Splitting into two calls is a violation.

---

**UniversalForm** (Pydantic BaseModel)
Produced by `structured_llm` inside each `extraction_worker` call.
Fields:
- `entity_or_concept: str` — primary asset, liability, or operational vector.
- `factual_evidence_quote: str` — verbatim text from the source document.
- `implied_liability_score: int` — risk score, constrained `ge=1, le=10`.
- `cross_reference_dependencies: List[DependencyLink]` — defaults to `[]`.

`DependencyLink` fields: `target_file`, `target_concept`, `nature_of_contradiction`.

---

**ExtractionRecord** (Pydantic BaseModel)
The unit stored in `local_inbox` and `global_inbox`. Never a raw dict in those
channels (Invariant X5). Fields: `lens_name`, `source_file`, `chunk_index`,
`payload: UniversalForm`.

---

**WorkerPayload** (Pydantic BaseModel — Invariants W1, W2)
The message passed to each `extraction_worker` invocation. Fields: `lens_name`,
`source_file`, `chunk_index`, `target_chunk_text`, `semantic_summary`.
All fields are JSON-primitive (Invariant W1). `semantic_summary` is required and
stamped at dispatch time — it is the only channel by which a worker receives the
document's global context (Invariant W2). Instances are immediately serialized to
primitive dicts via `.model_dump()` before being passed to `asyncio.gather`;
`route_matrix_to_workers` never returns Pydantic instances (Invariant E3).

---

**ParentState** (TypedDict — the live LangGraph state schema)
The state schema passed to `StateGraph(ParentState)`. All five fields:
- `directory_path: str` — no reducer; read by `directory_crawler` and
  `dispatch_documents`.
- `crawled_files: List[str]` — no reducer; written exactly once by
  `directory_crawler` (Invariant P2).
- `summary_store: Annotated[Dict[str, str], lambda a, b: {**a, **b}]` — merge
  reducer; accumulates one entry per document across parallel handoffs (Invariant P1).
- `global_inbox: Annotated[List[ExtractionRecord], add]` — append reducer;
  accumulates all extraction records across all documents.
- `master_risk_report: str` — no reducer; written once by
  `master_round_table_node`.

---

**DocumentSubState** (TypedDict — documentation artifact only, Invariant D1)
Defined in `pipeline.py` as a TypedDict but NOT passed to `StateGraph()`. No
LangGraph sub-graph with `StateGraph(DocumentSubState)` exists. This type serves as
a documentation artifact and type reference only. Its fields describe the logical
state that flows through `process_document` as local variables: `source_material`,
`file_name`, `semantic_summary`, `dynamic_topology`, `document_chunks`,
`local_inbox`. There are no `gap_detected` or `blind_spots` fields — these were
removed in v6 (Invariant D1). See INTERFACE_CONTRACT.md Deviation 4.

---

**route_matrix_to_workers** (pure function — Invariants E2, E3, E4)
Actual signature (differs from contract spec — see INTERFACE_CONTRACT.md Deviation 2):
```python
def route_matrix_to_workers(
    file_name: str,
    document_chunks: List[str],
    dynamic_topology: List[str],
    semantic_summary: str,
) -> List[Dict[str, Any]]
```
Not a LangGraph conditional edge. Called directly from inside `process_document`.
Returns primitive dicts, not `Send` objects and not Pydantic instances (Invariant E3).
Stamps `semantic_summary` into every dict (Invariant E4). Emits the full
`chunks × dynamic_topology` cross-product (Invariant E3).

---

**extraction_worker** — single-parameter signature (Invariants X1–X5)
```python
async def extraction_worker(payload_dict: Dict[str, Any]) -> Dict[str, Any]
```
Exactly one parameter, `payload_dict`. No `state` parameter (Invariant X1). Reads
`semantic_summary` from the payload, never from external state (Invariant X2). Uses
`await structured_llm.ainvoke(...)` — sync `.invoke()` is prohibited (Invariant X3).
Entire body (including the `WorkerPayload(**payload_dict)` construction at the top)
wrapped in `try/except` (Invariant X4). Returns a constructed `ExtractionRecord` on
success, not a raw dict (Invariant X5). On any exception returns
`{"local_inbox": []}`. Called via `asyncio.gather` from `process_document`, not via
LangGraph `Send` (INTERFACE_CONTRACT.md Deviation 3).

---

**await ainvoke() requirement**
All LLM calls in the pipeline use `await ...ainvoke(...)`. Using the synchronous
`.invoke()` inside an async function blocks the event loop, preventing
`asyncio.gather` from running workers concurrently. This would serialize all workers
and eliminate the concurrency benefit of the architecture. Invariant X3 makes this
explicit for `extraction_worker`; the same principle applies to `process_document`'s
router call and `master_round_table_node`'s synthesis call.

---

**process_document — combined sub-graph equivalent**
`process_document` is the async LangGraph node that implements what the design
described as a per-document sub-graph. It encapsulates, in order: the router call
(equivalent of `router_node`), chunking (equivalent of `chunk_node`), fan-out matrix
construction (`route_matrix_to_workers`), the worker pool (`asyncio.gather`), result
collection, and the handoff return (equivalent of `handoff_node`). It is dispatched
via LangGraph `Send` from `dispatch_documents`, making it the unit of document-level
parallelism. Its return value feeds directly into `ParentState` via the merge and
append reducers. See INTERFACE_CONTRACT.md Deviation 5.

---

### app.py

**nest_asyncio bridge pattern (Invariant I2)**
`app.py` applies the bridge at module load:
```python
import nest_asyncio
nest_asyncio.apply()
```
The graph is then invoked synchronously from Streamlit's execution context using:
```python
report = asyncio.get_event_loop().run_until_complete(run_graph(directory_path))
```
This pattern is required because Streamlit runs inside an event loop that already
exists when user code executes. `asyncio.run()` would attempt to create a second
event loop and raise a `RuntimeError`. `nest_asyncio` patches the running loop to
permit nested `run_until_complete` calls. The bridge must be applied before any
`await` is attempted.

The UI provides: a text input for the data room directory path, a spinner wrapping
the `run_until_complete` call, `st.markdown(report)` to render the returned Markdown
report, and a download button for the report text.

---

*Glossary version: 2.0 — post-implementation rewrite, tracks pipeline.py and INTERFACE_CONTRACT.md v1.1*
