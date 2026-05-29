# Architectural Design Document: Dynamic Semantic Topology (DST) Engine
## PrismForge AI v4 — Adaptive Corporate Due Diligence Architecture
### Format: Consolidated Decision Ledger for LLM Synthesis Context — v8 (Final)

---

## 0. System Overview

PrismForge AI v4 is a multi-agent LangGraph pipeline designed to ingest a directory of corporate due diligence documents, decompose each file into semantically chunked units, apply domain-specific extraction lenses in parallel, and synthesize a cross-referenced liability risk report. The architecture is constrained to a 10-hour implementation sprint.

**Primary Technology Stack:** LangGraph, Pydantic v2, LangChain, asyncio, Streamlit, Docker, Anthropic Claude / Google Gemini Flash.

> **Patch Note (v6):** Chroma removed from the stack. No node in the pipeline reads from or writes to a vector store — chunking is handled by `RecursiveCharacterTextSplitter` on raw text, and extraction workers operate on string payloads directly. Chroma was vestigial from a prior architecture version. Carrying an undefined dependency into the sprint is a confusion and import-error hazard.

---

## 1. Global Topology

```
[ Directory Crawler Node ]
│  (populates crawled_files + reads source_material per file)
│
├───► [ Sub-Graph Sandbox: File 1 ] ──► [workers] ──► [Single Handoff: summary_store + global_inbox] ──┐
├───► [ Sub-Graph Sandbox: File 2 ] ──► [workers] ──► [Single Handoff: summary_store + global_inbox] ──┤
└───► [ Sub-Graph Sandbox: File N ] ──► [workers] ──► [Single Handoff: summary_store + global_inbox] ──┘
                                                                                                        │
          Single Handoff (post-workers): semantic_summary → ParentState["summary_store"][file_name]     │
                                         local_inbox      → ParentState["global_inbox"]  (append)       │
                                                                                                        ▼
                                                                               [ Parent State Inbox ]
                                                                    (global_inbox + summary_store fully populated)
                                                                                 │
                                                                                 ▼
                                                                    [ Master Round-Table Node ]
                                                                    ┌─────────────────────────────┐
                                                                    │ Preamble (pure Python):     │
                                                                    │  detect_blind_spots()       │
                                                                    │  → blind_spot_block str     │
                                                                    │                             │
                                                                    │ Synthesis:                  │
                                                                    │  single-shot LLM call       │
                                                                    │  streaming Markdown output  │
                                                                    └─────────────────────────────┘
                                                                                 │
                                                                                 ▼
                                                                       Final Risk Report
```

### Sub-Graph Sandbox Internal Process

> **Diagram Note (v11):** There is ONE state handoff per sub-graph, not two. It fires after workers complete and writes both `summary_store` and `global_inbox` to parent state in a single atomic return. A prior version of this diagram split the handoff into two moments — labeling one "pre-fan-out" with the stated purpose of making the summary available to `route_matrix_to_workers`. That rationale was incorrect: `route_matrix_to_workers` is a conditional edge function that receives `DocumentSubState`, not `ParentState`. It reads `semantic_summary` directly from sub-graph state, where it was written by `router_node` earlier in the same sub-graph execution. No parent state access is needed at dispatch time. `ParentState["summary_store"]` is consumed only by the Master Round-Table Node, which runs after all sub-graphs complete — so populating it post-workers is always in time.

```
[ Raw File Payload ] ──► [ Single-Pass Combined Router (Throttled, Gemini Flash) ]
                                          │
                         Structured Output: RouterOutput schema
                         Emits BOTH simultaneously:
                           - semantic_summary: str  → DocumentSubState["semantic_summary"]
                           - dynamic_topology: List[str]  → DocumentSubState["dynamic_topology"]
                         Written atomically into DocumentSubState
                                          │
                                          ▼
                         [ Dynamic Map-Reduce Semantic Chunking ]
                         (~1,000 Token Target / 20% Overlap)
                         via RecursiveCharacterTextSplitter
                         (chunk_size=4000 chars ≈ 1,000 tokens)
                                          │
                                          ▼
                         [ Contextual Anchoring Pointer Construction ]
                         (source_file ref key + target_chunk_text only)
                                          │
                                          ▼
                         [ Matrix Cross-Product Fan-Out Mapper ]
                                  [ Chunks ⊗ Lenses ]
                         (route_matrix_to_workers reads semantic_summary
                          from DocumentSubState — written by router_node
                          above; stamps it into each WorkerPayload)
                                          │
                                          ▼
                         [ Concurrent Async Worker Pool ]
                         (Strict In-Node Payload Unpacking)
                         (semantic_summary carried in WorkerPayload —
                          injected at dispatch time in route_matrix_to_workers;
                          extraction_worker has NO state parameter)
                                          │
                                          ▼
                         [ Append-Only Local Inbox Register ]
                         (ExtractionRecord objects, not raw dicts)
                                          │
                                          ▼
                         ╔══════════════════════════════════════════════╗
                         ║  SINGLE HANDOFF — After Workers Complete     ║
                         ║  Writes atomically:                          ║
                         ║    semantic_summary →                        ║
                         ║      ParentState["summary_store"][file_name] ║
                         ║    local_inbox →                             ║
                         ║      ParentState["global_inbox"]  (via add)  ║
                         ║  Both fields written in one return dict.     ║
                         ║  summary_store is consumed only by the       ║
                         ║  Master Round-Table Node — all sub-graphs    ║
                         ║  complete before it runs, so timing is safe. ║
                         ╚══════════════════════════════════════════════╝
```

---

## 2. Production State Schemas

```python
from operator import add
from typing import Annotated, Any, Dict, List
from pydantic import BaseModel, Field
from typing_extensions import TypedDict


# ── Router Output Schema ──────────────────────────────────────────────────────
# Patch (v6): The Two-Tier Hierarchical Router is collapsed into a single
# structured LLM call. RouterOutput is the combined schema bound via
# .with_structured_output(). One network round-trip produces both outputs
# atomically, eliminating a separate summary call and a separate lens call.

class RouterOutput(BaseModel):
    semantic_summary: str = Field(
        description="A dense, high-information profile of the document's primary subject matter, "
                    "key entities, contractual obligations, and risk domains. 200-400 words."
    )
    dynamic_topology: List[str] = Field(
        description="Array of domain-specific extraction lens identifiers applicable to this "
                    "document (e.g. 'IP_Ownership', 'License_Compliance', 'Liability_Cap', "
                    "'Change_of_Control', 'Data_Privacy'). 3-7 lenses per document."
    )


# ── Extraction Schemas ────────────────────────────────────────────────────────

class DependencyLink(BaseModel):
    target_file: str = Field(description="The precise filename or entity ID being contradicted or complemented.")
    target_concept: str = Field(description="The explicit contractual clause, open-source license, or operational liability field.")
    nature_of_contradiction: str = Field(description="Detailed technical evaluation of the variance between the source documents.")

class UniversalForm(BaseModel):
    entity_or_concept: str = Field(description="Primary target asset, liability, or operational vector identifier.")
    factual_evidence_quote: str = Field(description="Verbatim text string extracted directly from the source material.")
    implied_liability_score: int = Field(ge=1, le=10, description="Risk quantification weight score.")
    cross_reference_dependencies: List[DependencyLink] = Field(
        default=[],
        description="Structured array of identified links to outside files or domains."
    )

class ExtractionRecord(BaseModel):
    lens_name: str
    source_file: str
    chunk_index: int
    payload: UniversalForm

class WorkerPayload(BaseModel):
    lens_name: str
    source_file: str
    chunk_index: int
    target_chunk_text: str
    semantic_summary: str  # Patch (v8): injected at dispatch time from DocumentSubState["semantic_summary"].
                           # Prior spec had extraction_worker read this from a `state: ParentState`
                           # parameter, but LangGraph does not inject parent state into Send-dispatched
                           # nodes — that parameter would always be empty. Summary is ~300 words;
                           # per-payload duplication cost is negligible at this scale.


# ── State Definitions ─────────────────────────────────────────────────────────

class ParentState(TypedDict):
    directory_path: str
    # Patch (v6): summary_store added. Summaries are generated inside sub-graphs
    # and transferred here via the single handoff exit node (post-workers).
    # IMPORTANT: summary_store must use a dict-merge reducer (e.g. operator.or_
    # or a custom merge fn) so parallel sub-graph handoffs accumulate entries
    # rather than overwriting each other. Without this, only the last sub-graph's
    # summary survives when N files run concurrently.
    summary_store: Annotated[Dict[str, str], lambda a, b: {**a, **b}]  # merge reducer: {file_name: semantic_summary}
    crawled_files: List[str]  # Set once by Directory Crawler Node before sub-graphs run.
                              # No reducer needed — single write, never updated by handoff nodes.
    global_inbox: Annotated[List[ExtractionRecord], add]   # append-only across all sub-graphs
    master_risk_report: str

class DocumentSubState(TypedDict):
    source_material: str
    file_name: str
    semantic_summary: str
    dynamic_topology: List[str]    # Array of localized lens identifiers
    document_chunks: List[str]     # Array of token-window chunks
    local_inbox: Annotated[List[ExtractionRecord], add]
    # gap_detected and blind_spots removed (v6): blind spot detection is a
    # Python filter function in the Master Round-Table Node preamble, not a
    # sub-graph state field. See Decision 3.16.
```

---

## 3. Decision Ledger

Each entry follows the structure: **Problem → Selected Paradigm → Rejected Alternative → Rationale**.

---

### 3.1 Sub-Graph to Parent-Graph State Propagation

**Problem:** LangGraph sub-graphs execute in isolated scopes. Naive reliance on native state surfacing causes silent data loss when nested list reducers attempt to propagate across graph boundaries.

**Selected Paradigm:** Explicit Edge-Mapping State Handoff Pipeline.

Upon completion of all parallel sub-graph tasks, an explicit exit node intercepts `DocumentSubState["local_inbox"]` and `DocumentSubState["semantic_summary"]` and executes a hard mapping injection into `ParentState["global_inbox"]` and `ParentState["summary_store"]` respectively — in a single atomic return dict.

**Rejected Alternative:** Native LangGraph Automatic State Bubbling.

**Rationale:** LangGraph sub-graphs do not implicitly surface nested updates or list reductions to the parent graph scope unless keys are identical and globally exposed. Silent data dropping during cross-boundary state compilation is non-deterministic and untestable. Explicit hand-offs guarantee absolute data durability with full observability.

---

### 3.2 Context Anchoring Strategy (Memory Bloat Mitigation)

**Problem:** Passing the global semantic summary as a raw string payload through every worker channel in a high-fan-out matrix (250+ parallel workers) multiplies memory allocation and checkpoint serialization size by a factor of `(Chunks × Lenses)`.

**Selected Paradigm:** Dispatch-Time Summary Stamping via `DocumentSubState["semantic_summary"]`.

`route_matrix_to_workers` reads `semantic_summary` once from `DocumentSubState` (written there by `router_node` earlier in the same sub-graph) and stamps it into each `WorkerPayload` at dispatch time. The `extraction_worker` then reads the summary directly from its payload and assembles the composite prompt string inside volatile execution memory immediately prior to LLM invocation:

```python
async def extraction_worker(payload_dict: Dict[str, Any]) -> Dict[str, Any]:
    # Patch (v8): `state: ParentState` parameter removed. LangGraph does not inject parent
    # state into Send-dispatched nodes — the parameter resolved to an empty dict at runtime.
    # semantic_summary is now carried in WorkerPayload and injected at dispatch time.
    payload = WorkerPayload(**payload_dict)

    anchored_prompt_payload = (
        f"GLOBAL FILE CONTEXT:\n{payload.semantic_summary}\n\n"
        f"TARGET CHUNK:\n{payload.target_chunk_text}"
    )

    try:
        result: UniversalForm = await structured_llm.ainvoke(anchored_prompt_payload)
        record = ExtractionRecord(
            lens_name=payload.lens_name,
            source_file=payload.source_file,
            chunk_index=payload.chunk_index,
            payload=result
        )
        return {"local_inbox": [record]}
    except Exception as e:
        # Patch (v8): bare except added — one worker failure must not crash the async pool.
        # Returns empty list so the lens/chunk combination is silently skipped.
        # The blind spot detector will surface files with zero total records.
        print(f"[extraction_worker] FAILED lens={payload.lens_name} file={payload.source_file} chunk={payload.chunk_index}: {e}")
        return {"local_inbox": []}
```

**Rejected Alternative:** Composite Global-Context Anchored Payloads inside State Channels (PrismForge AI v3).

**Rationale:** Passing thousands of duplicate characters down hundreds of parallel worker channels causes severe heap bloat and inflates the LangGraph state checkpoint ledger. Volatile-scope string assembly fully preserves the attention-middle-loss mitigation strategy while cutting memory usage by multiple orders of magnitude.

> **Patch Note (v6):** Three fixes applied. First, `summary_anchor` was specified to be read from `state["summary_store"]` via a `state: ParentState` parameter on `extraction_worker`. Second, the worker uses `await structured_llm.ainvoke(...)` (async) instead of `.invoke()` (sync). Third, the return value is a constructed `ExtractionRecord` object.

> **Patch Note (v8):** The `state: ParentState` parameter on `extraction_worker` is removed. LangGraph does not inject parent state into Send-dispatched nodes — the parameter resolves to an empty dict, causing `summary_store.get()` to always return `""`. The fix: `semantic_summary` is added to `WorkerPayload` and injected once per dispatch inside `route_matrix_to_workers`, which reads it from `DocumentSubState` where `router_node` wrote it earlier in the same sub-graph. At 200-400 words per summary the per-payload duplication cost is negligible. A bare `try/except` is also added to `extraction_worker` so a single provider error or malformed response does not crash the entire async pool.

---

### 3.3 Summary Store Access Pattern

**Problem:** The `extraction_worker` requires access to the `semantic_summary` generated during the router phase. Summaries do not exist before the graph runs, so they cannot be injected via `RunnableConfig` at invocation time. A module-level global dictionary introduces race conditions and is incompatible with LangGraph's checkpointing model.

**Selected Paradigm:** `DocumentSubState["semantic_summary"]` as the dispatch-time source; `ParentState["summary_store"]` as the post-run parent record.

The router node writes `RouterOutput.semantic_summary` into `DocumentSubState["semantic_summary"]`. The `route_matrix_to_workers` edge function reads it from there — it is always present at dispatch time because `router_node` runs earlier in the same sub-graph. After workers complete, the single handoff node writes both `semantic_summary` into `ParentState["summary_store"][file_name]` and `local_inbox` into `ParentState["global_inbox"]` in one atomic return. The Master Round-Table Node, which runs after all sub-graphs complete, has access to the fully populated `summary_store` if needed for synthesis context.

```python
# Single handoff node — runs after workers complete for each sub-graph.
# Synchronous by design — pure dict mapping, no I/O or LLM calls.
# Note: ParentState["summary_store"] must use a merge reducer (not default
# overwrite) if multiple sub-graphs run in parallel. Use operator.or_ or a
# custom dict-merge reducer on the summary_store field to accumulate entries
# from all sub-graphs without race-overwriting prior keys.
def handoff_node(sub_state: DocumentSubState) -> Dict[str, Any]:
    return {
        "global_inbox": sub_state["local_inbox"],
        "summary_store": {sub_state["file_name"]: sub_state["semantic_summary"]}
    }
```

Workers read directly from the payload — the summary was resolved and embedded at dispatch time:

```python
anchored_prompt_payload = (
    f"GLOBAL FILE CONTEXT:\n{payload.semantic_summary}\n\n"
    f"TARGET CHUNK:\n{payload.target_chunk_text}"
)
```

> **Patch Note (v8):** Workers no longer carry a `state: ParentState` parameter. That parameter was never populated by LangGraph for Send-dispatched nodes. `semantic_summary` is read once inside `route_matrix_to_workers` from `DocumentSubState` and stamped into each `WorkerPayload` at dispatch time.

> **Patch Note (v11):** The prior spec described a "Handoff Moment 1" occurring pre-fan-out specifically to make the summary available to `route_matrix_to_workers`. This was incorrect. `route_matrix_to_workers` is a conditional edge function receiving `DocumentSubState` — it never had access to `ParentState["summary_store"]` and did not need it. The summary is available in `DocumentSubState` from the moment `router_node` returns. The pre-fan-out handoff served no functional purpose. It is removed; a single post-workers handoff now writes both `summary_store` and `global_inbox` atomically.

**Rejected Alternative A:** `RunnableConfig` Pre-Injection at Invocation Time.

**Rationale:** `RunnableConfig` cannot carry summaries that don't yet exist. Populating it before `graph.ainvoke()` is a sequencing impossibility — the router that generates summaries runs inside the graph.

**Rejected Alternative B:** Module-Level Global Dictionary (`global_summary_store`).

**Rationale:** A global dict works in single-process local execution but is incompatible with concurrent graph invocations, horizontal scaling, and LangGraph's checkpointing replay model. Cross-request contamination is a silent failure mode with no observable error signal.

---

### 3.15 Pre-Pass Router Implementation (Single Combined Call)

**Problem:** The original "Two-Tier Hierarchical Router" implied two separate LLM calls per document — one for the semantic summary and one for the lens array — with no implementation spec for either. This was the most underspecified node in the pipeline and the highest-risk scope item for Phase 2.

**Selected Paradigm:** Single-Pass Combined Router using `RouterOutput` structured output schema.

One LLM call per document produces both outputs atomically. The model receives the full document text and returns a `RouterOutput` object containing `semantic_summary` (str) and `dynamic_topology` (List[str]) simultaneously. This is bound via `.with_structured_output(RouterOutput)` on a Gemini Flash singleton.

```python
from langchain_google_genai import ChatGoogleGenerativeAI

# Module-level singleton — instantiated once, reused across all sub-graphs
router_llm = ChatGoogleGenerativeAI(model="gemini-2.0-flash")
structured_router = router_llm.with_structured_output(RouterOutput)

ROUTER_SYSTEM_PROMPT = """You are a corporate due diligence document analyst.
Given the full text of a document, you must produce:
1. A dense semantic summary (200-400 words) covering key entities, obligations, and risk domains.
2. A list of 3-7 extraction lens identifiers that are directly applicable to this document.

Valid lens identifiers include but are not limited to:
IP_Ownership, License_Compliance, Liability_Cap, Indemnification,
Change_of_Control, Data_Privacy, Employment_Obligations, Revenue_Share,
Regulatory_Approval, IP_Warranty.

Return only the structured RouterOutput object. No preamble."""

async def router_node(state: DocumentSubState) -> Dict[str, Any]:
    result: RouterOutput = await structured_router.ainvoke([
        {"role": "system", "content": ROUTER_SYSTEM_PROMPT},
        {"role": "user", "content": state["source_material"]}
    ])
    return {
        "semantic_summary": result.semantic_summary,
        "dynamic_topology": result.dynamic_topology
    }
```

**Rejected Alternative:** Two separate sequential LLM calls (summary call → lens selection call).

**Rationale:** Two calls per document doubles router-phase API cost and latency. With N files in the directory, the pre-pass cost scales as `2N` calls before the extraction matrix even begins. A combined structured output call is equivalent in token consumption and halves round-trip overhead. Single-call atomicity also eliminates a class of partial-failure states where the summary succeeds but the lens call fails, leaving `DocumentSubState` in an inconsistent intermediate state.

---

### 3.4 Concurrency Throttle and Rate-Limit Protection

**Problem:** Burst fan-out across hundreds of parallel workers will exhaust upstream LLM provider rate limits (RPM/TPM). Throttling only the extraction workers leaves the pre-pass topology generation phase—which also issues bulk LLM calls per file in the directory—unprotected.

**Selected Paradigm:** Native LangGraph Graph-Level `max_concurrency` Configuration.

```python
await graph.ainvoke(inputs, config={"max_concurrency": 50})
```

This enforces a unified concurrency ceiling across all node types at the graph execution layer, eliminating per-node semaphore management.

**Rejected Alternative A:** Pure Worker-Node Only Throttling.

**Rationale:** Throttling only extraction workers leaves the pre-pass router exposed during bulk directory crawls, enabling RPM exhaustion before the main extraction phase begins.

**Rejected Alternative B:** Module-Level `asyncio.Semaphore` Primitives.

**Rationale:** Instantiating `asyncio.Semaphore(50)` at the module level causes `RuntimeError: got Future <Future pending> attached to a different loop` if LangGraph initializes a new event loop during execution. Native graph-level concurrency control is event-loop-agnostic and sprint-safe.

---

### 3.16 Blind Spot Discovery Implementation

**Problem:** The topology diagram showed a standalone `[ Blind Spot Discovery ]` graph node between the Parent State Inbox and the Master Round-Table Node. `DocumentSubState` carried `gap_detected: bool` and `blind_spots: List[Dict[str, Any]]` fields referencing this node. No implementation, trigger condition, input schema, or output behavior was defined anywhere in the spec. At sprint hour 8, this was a hidden scope item.

**Selected Paradigm:** Python Filter Function, not a LangGraph Node.

Blind spot detection is reduced to a deterministic Python scan of `global_inbox` executed synchronously inside the Master Round-Table Node's preamble. A file has a blind spot if it appears in the directory crawl but has zero `ExtractionRecord` entries in `global_inbox`. This covers the primary failure mode: a file that was parsed but produced no usable extraction output (empty document, encoding failure, all-binary content, LLM refusal).

```python
def detect_blind_spots(
    crawled_files: List[str],
    global_inbox: List[ExtractionRecord]
) -> List[str]:
    """Returns list of filenames with zero extraction records."""
    covered = {record.source_file for record in global_inbox}
    return [f for f in crawled_files if f not in covered]

# Inside the Master Round-Table Node preamble:
blind_spots = detect_blind_spots(state["crawled_files"], state["global_inbox"])
blind_spot_block = ""
if blind_spots:
    blind_spot_block = (
        "\n\n## ⚠️ Coverage Gaps Detected\n"
        "The following files produced no extraction records and are excluded from this report:\n"
        + "\n".join(f"- `{f}`" for f in blind_spots)
    )
```

The `blind_spot_block` string is prepended to the synthesis prompt so the Master Round-Table Node explicitly acknowledges gaps in the final report rather than silently omitting files.

`DocumentSubState["gap_detected"]` and `DocumentSubState["blind_spots"]` fields are removed from the schema (replaced by `List[str]` for simplicity). `ParentState` gains a `crawled_files: List[str]` field populated by the directory crawler node.

**Rejected Alternative:** Standalone LangGraph Conditional Node with Boolean Gate Routing.

**Rationale:** A conditional routing node adds a graph edge, a condition function, a state field check, and a branch path to a node that does nothing more than filter a list. The same logic in 10 lines of Python inside the Round-Table Node preamble is faster to write, easier to test, and produces a richer output (the blind spot names appear directly in the report). Reducing LangGraph node count is always the correct sprint move when the logic is pure and deterministic.

---

### 3.5 Text Chunking Implementation

**Problem:** Building a sliding-window token chunker from scratch is a known time sink. Edge cases including mid-sentence breaks, encoding anomalies, and off-by-one token boundary errors routinely consume more sprint hours than estimated.

**Selected Paradigm:** `RecursiveCharacterTextSplitter` from `langchain_text_splitters`.

```python
from langchain_text_splitters import RecursiveCharacterTextSplitter

# NOTE: chunk_size is measured in CHARACTERS, not tokens.
# ~4,000 characters ≈ 1,000 tokens for English prose (GPT-style tokenizer).
# Set chunk_size=4000, chunk_overlap=800 to match the spec's stated 1,000-token
# target. Using chunk_size=1000 would produce ~250-token chunks — undersized.
splitter = RecursiveCharacterTextSplitter(chunk_size=4000, chunk_overlap=800)
chunks = splitter.split_text(document_text)
```

**Rejected Alternative:** Custom Sliding-Window Token Parser built from scratch.

**Rationale:** A battle-tested library implementation eliminates edge case risk and compresses Phase 3 implementation time to minutes. Sprint hours should be allocated to the cross-product routing logic, not low-level text parsing.

---

### 3.6 Directory Crawler Robustness

**Problem:** A corporate document directory will contain non-text binary files (`.DS_Store`, system metadata, embedded media, etc.). An uncaught exception during file reading crashes the entire pipeline at Phase 1.

**Selected Paradigm:** Defensive `try/except` Wrapping with Binary File Filtering.

```python
for file_path in directory.iterdir():
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
        # proceed with pipeline
    except (UnicodeDecodeError, IsADirectoryError, PermissionError):
        continue  # skip non-text or unreadable files silently
```

**Rejected Alternative:** Unguarded file reading loop.

**Rationale:** Silent skipping of non-parseable files is the correct behavior for a due diligence context where document sets are heterogeneous. Crashing the graph on a hidden system file at hour 1 of the sprint is unacceptable.

---

### 3.7 Cross-Product Fan-Out and Serialization Typing

**Problem:** LangGraph's `Send` wrapper requires primitive-serializable payloads. If `WorkerPayload` is passed directly as a Pydantic model instance, initialization compatibility with the `Send` framework is not guaranteed, producing silent failures or cryptic serialization errors.

**Selected Paradigm:** Decoupled Decider-Router Matrix Mapping with Strict Primitive Serialization.

```python
# Patch (v9): route_matrix_to_workers is a conditional edge function — LangGraph
# only passes a single state argument to edge functions. A two-parameter signature
# (state, parent_state) is not a valid LangGraph calling convention and would raise
# a TypeError at graph compilation time.
#
# route_matrix_to_workers reads semantic_summary from DocumentSubState directly.
# It was written there by router_node earlier in the same sub-graph execution.
# No parent state access is needed — the summary is always present in sub-graph
# state at the point this edge function fires.

def route_matrix_to_workers(state: DocumentSubState) -> List[Send]:
    execution_matrix = []
    summary = state.get("semantic_summary", "")  # Written by router_node; always present at this point
    for chunk_idx, chunk_text in enumerate(state["document_chunks"]):
        for lens in state["dynamic_topology"]:
            worker_config = WorkerPayload(
                lens_name=lens,
                source_file=state["file_name"],
                chunk_index=chunk_idx,
                target_chunk_text=chunk_text,
                semantic_summary=summary  # Resolved once per dispatch batch, not per worker call
            )
            execution_matrix.append(
                Send("extraction_worker", worker_config.model_dump())  # Primitive dict, not Pydantic object
            )
    return execution_matrix

async def extraction_worker(payload_dict: Dict[str, Any]) -> Dict[str, Any]:
    payload = WorkerPayload(**payload_dict)  # Structural validation at node entry boundary
    # Full implementation in Decision 3.2
    ...
```

**Rejected Alternative:** Graph-Schema Auto-Generation via LLM Prompt Output, or passing Pydantic model instances directly into `Send`.

**Rationale:** Pure-Python cross-product computation is deterministic and fully testable independent of the LLM layer. Forcing an LLM to generate routing structures degrades reliability. Primitive dict serialization via `.model_dump()` guarantees `Send` compatibility and eliminates runtime type errors. The single-parameter edge function signature is the only valid LangGraph calling convention for conditional edges — a two-parameter `(state, parent_state)` signature raises a `TypeError` at graph compilation time. `semantic_summary` is already available in `DocumentSubState` at dispatch time because `router_node` writes it earlier in the same sub-graph execution; no parent state access is needed.

**Serialization Constraint:** `WorkerPayload` must contain only JSON-serializable primitives (str, int, list, dict). Any `datetime`, `numpy`, or complex class field will cause `Send` to fail silently or raise cryptic errors. This constraint is enforced by design in the schema above.

---

### 3.8 Multi-File Contradiction Linkage Typing

**Problem:** When the Master Round-Table Node reconciles findings across multiple documents, it must traverse structured cross-reference edges. Freeform string representations of cross-document relationships produce non-deterministic and highly variable descriptors that cannot be reliably parsed downstream.

**Selected Paradigm:** Strongly-Typed Graph-Edge Dependency Objects (`DependencyLink` Pydantic model).

```python
class DependencyLink(BaseModel):
    target_file: str
    target_concept: str
    nature_of_contradiction: str
```

**Rejected Alternative:** Flat Textual/String Representation arrays.

**Rationale:** Freeform text fields allow LLMs to output structurally inconsistent cross-references. The Master Round-Table Node requires clean structural graphs to execute multi-document reconciliation. Typed edges prevent downstream synthesis failures and enable programmatic traversal of the dependency network.

---

### 3.9 LLM Structured Output Enforcement

**Problem:** During high-concurrency extraction across a `(Chunks × Lenses)` matrix, any worker that drifts from the `UniversalForm` schema produces an unparseable record. Upstream failures propagate silently through the `local_inbox` accumulator, corrupting the `global_inbox` that the Master Round-Table Node depends on.

**Selected Paradigm:** Native API Binding via `.with_structured_output()`.

```python
# Singleton instantiation at module level — not recreated per worker
llm = ChatAnthropic(model="claude-sonnet-4-20250514")
structured_llm = llm.with_structured_output(UniversalForm)

# Inside extraction_worker (async context — must use ainvoke, not invoke):
result: UniversalForm = await structured_llm.ainvoke(anchored_prompt_payload)
```

**Rejected Alternative:** Graph-Level Reflexion Loop (Self-Correction Conditional Edge).

The reflexion approach allows the worker to output raw JSON, routes failures to a validation node, and re-invokes the worker with the Pydantic error trace appended to the prompt.

**Rationale:** Native tool-calling enforcement via `.with_structured_output()` offloads schema compliance to the provider API layer, which is heavily optimized for this pathway on frontier models. Building conditional routing logic, retry state management, and infinite-loop guards for a reflexion loop consumes disproportionate sprint hours. The reflexion approach also risks compounding TPM exhaustion when validation failures trigger multiple iterative API calls per worker task.

**Optimization:** Instantiate the bound model once at module scope as a singleton. Recreating the runnable chain inside 250+ concurrent worker invocations adds measurable overhead and is unnecessary.

---

### 3.10 Final Report Synthesis Strategy

**Problem:** The Master Round-Table Node must synthesize a final risk assessment from a large structured array of `ExtractionRecord` objects containing `UniversalForm` payloads and `DependencyLink` edges. The synthesis strategy determines both implementation complexity and user-perceived latency.

**Selected Paradigm:** Single-Shot Long-Context Markdown Streaming with Record-Count Guard.

The `global_inbox` array is passed through a `compress_inbox()` filter before serialization. If the record count is within the safe threshold (≤ 500 records ≈ ~15 files at typical density), the full array is serialized and passed to a single comprehensive synthesis prompt. If the record count exceeds the threshold, records are sorted descending by `implied_liability_score` and truncated to the top 500, with a warning prepended to the synthesis prompt. The model output is collected via the `nest_asyncio` + `get_event_loop().run_until_complete()` bridge and rendered through Streamlit (Decision 3.11).

```python
# Safe threshold: ~500 records ≈ ~15 files × ~7 chunks × ~5 lenses
# At this volume, serialized JSON fits comfortably within a 200k context window.
# Beyond ~1,000 records the prompt approaches the practical coherence ceiling
# for cross-reference synthesis even on frontier models.
SYNTHESIS_RECORD_LIMIT = 500

def compress_inbox(
    global_inbox: List[ExtractionRecord],
    limit: int = SYNTHESIS_RECORD_LIMIT
) -> tuple[List[ExtractionRecord], str]:
    """
    Returns (records_for_synthesis, warning_block).
    If truncation occurs, warning_block is a Markdown string to prepend to the
    synthesis prompt. If no truncation, warning_block is an empty string.
    """
    if len(global_inbox) <= limit:
        return global_inbox, ""

    sorted_records = sorted(
        global_inbox,
        key=lambda r: r.payload.implied_liability_score,
        reverse=True
    )
    truncated = sorted_records[:limit]
    dropped = len(global_inbox) - limit
    warning = (
        f"\n\n## ⚠️ Synthesis Truncation Warning\n"
        f"{dropped} lower-priority extraction records were dropped to fit the synthesis "
        f"context window. Only the top {limit} records by implied liability score are included. "
        f"High-risk signals are preserved; low-risk signals may be underrepresented.\n\n"
    )
    return truncated, warning

# Inside Master Round-Table Node preamble (runs after blind spot detection):
records_for_synthesis, truncation_warning = compress_inbox(state["global_inbox"])
inbox_payload = json.dumps(
    [r.model_dump() for r in records_for_synthesis],
    indent=2
)
synthesis_prompt = blind_spot_block + truncation_warning + "\n\n" + inbox_payload
```

**Rejected Alternative:** Map-Reduce Hierarchical Aggregation.

The hierarchical approach groups `ExtractionRecord` objects by `lens_name` or `target_concept`, runs a parallel batch of per-group summarization calls, and passes sub-summaries to a final orchestrator prompt.

**Rationale:** In a 10-hour sprint, the implementation overhead of hierarchical reduce routing is a net negative. Frontier models with 200k+ context windows (Claude Sonnet, GPT-4o) are capable of processing the complete structured `global_inbox` in a single pass with high coherence and reliable cross-reference tracking up to the 500-record threshold. Streaming Markdown provides immediate Time-To-First-Token (TTFT) feedback, which is critical for demo credibility. The `compress_inbox()` guard is eight lines of pure Python and costs zero sprint hours — it extends the single-shot paradigm to handle larger document sets without introducing LangGraph routing complexity. The hierarchical approach remains the correct upgrade path if the system is productionized beyond demo scale.

---

### 3.11 Frontend UI Layer

**Problem:** The sprint requires a functional visual interface for the streaming risk report output. Building a custom web frontend introduces JavaScript context switching, CORS configuration, SSE chunk-encoding debugging, and CSS layout overhead.

**Selected Paradigm:** Streamlit (Pure Python UI).

```python
import asyncio
import nest_asyncio  # pip install nest_asyncio
import streamlit as st

# Streamlit runs its own event loop internally. asyncio.run() raises
# "This event loop is already running" if called from within it.
# nest_asyncio patches the running loop to allow nested coroutines.
nest_asyncio.apply()

async def run_graph(inputs, config):
    """Run the async LangGraph pipeline and collect output."""
    output_chunks = []
    async for chunk in graph.astream(inputs, config=config):
        if "master_risk_report" in chunk:
            output_chunks.append(chunk["master_risk_report"])
    return "".join(output_chunks)

with st.spinner("Analyzing documents..."):
    report = asyncio.get_event_loop().run_until_complete(run_graph(inputs, config))
    st.markdown(report)
```

> **Implementation Note:** `asyncio.run()` raises `RuntimeError: This event loop is already running` inside Streamlit, which manages its own internal event loop. The fix is `nest_asyncio.apply()` (one line at module load) followed by `asyncio.get_event_loop().run_until_complete(...)` instead of `asyncio.run()`. Add `nest_asyncio` to `requirements.txt`.

**Rejected Alternative:** FastAPI + Vanilla JavaScript + Server-Sent Events (SSE).

The SSE approach serves a single `index.html` via Jinja2, uses Tailwind CSS via CDN, and streams tokens using the browser's `EventSource` API.

**Rationale:** Streamlit eliminates the frontend layer entirely. Remaining in the Python execution context is critical when sprint hours must be concentrated on LangGraph orchestration logic and schema validation. The `nest_asyncio` bridge is two lines of code at module load. The SSE approach, while lightweight, introduces JavaScript context switching and a non-trivial risk of debugging network tab encoding issues or DOM rendering edge cases at the worst possible time.

---

### 3.12 Deployment Strategy

**Problem:** The complete stack (LangGraph, Pydantic v2, Streamlit, LLM SDKs) must be deployed to a publicly accessible endpoint for demo delivery within the sprint window.

**Selected Paradigm:** Single-Container Docker Deployment on AWS EC2.

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
EXPOSE 8501
CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]
```

```bash
docker build -t prismforge-ai:latest .
docker run -e ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY -p 80:8501 prismforge-ai:latest
```

**Rejected Alternative:** Fully Managed PaaS (AWS App Runner).

**Rationale:** Managed PaaS services are unreliable with heavy AI dependency stacks. Pydantic v2's Rust core compilation and heavy async LLM SDK dependencies routinely fail in opaque App Runner build environments. If the build fails at hour 9, the debug cycle through abstracted cloud logs is unrecoverable within sprint constraints. Docker guarantees environmental determinism: if it runs locally, it runs in the cloud.

---

### 3.13 API Key Injection

**Problem:** Upstream LLM API keys (Anthropic, Google) must be available to the containerized runtime without being baked into the image layer or committed to version control.

**Selected Paradigm:** Runtime `-e` Environment Variable Injection.

```bash
docker run \
  -e ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY \
  -e GOOGLE_API_KEY=$GOOGLE_API_KEY \
  -p 80:8501 prismforge-ai:latest
```

**Rejected Alternative:** `.env` File Volume Mount.

```bash
docker run -v $(pwd)/.env:/app/.env -p 80:8501 prismforge-ai:latest
```

**Rationale:** Runtime `-e` injection keeps the container image 100% generic and environment-agnostic. Keys are held only in the container process memory and are never written to the filesystem or image layer history. Volume-mounted `.env` files introduce file permission risks and create a persistent path to accidental git commits of credentials.

---

### 3.14 Vector Store — REMOVED

> **Patch Note (v6):** Decision 3.14 (Chroma persistence strategy) has been removed from the spec entirely. Chroma appeared in the v5 technology stack but had no assigned role in any node, state schema, or sprint phase. No pipeline stage reads from or writes to a vector store — text chunking is handled by `RecursiveCharacterTextSplitter` on raw strings, and extraction workers receive `target_chunk_text` directly. Retaining an undefined dependency introduces import errors, version conflicts, and cognitive overhead during implementation. The stack is cleaner without it.

---

---

### 3.17 Monolithic `pipeline.py` vs. Separate `src/` Modules

**Problem:** A complex multi-agent pipeline with Pydantic schemas, TypedDict state definitions, LLM singletons, a chunker singleton, node functions, pure helper functions, graph construction, and an async entry point can be organized into a flat monolithic file or decomposed into a `src/` module tree (e.g. `src/schemas.py`, `src/nodes.py`, `src/graph.py`, `src/prompts.py`).

**Selected Paradigm:** Single monolithic `pipeline.py`.

All pipeline components live in one file: Pydantic schemas, TypedDict state definitions, LLM singletons, the `RecursiveCharacterTextSplitter` singleton, all node functions, the `route_matrix_to_workers` pure function, `extraction_worker`, `detect_blind_spots`, `compress_inbox`, LangGraph graph construction, and `run_graph`. `app.py` imports only `run_graph` from `pipeline.py`.

**Rejected Alternative:** `src/` module decomposition with separate files per concern layer.

**Rationale:** Sprint decomposition has a measurable overhead cost — each module boundary introduces an import chain, a potential circular dependency surface, and additional cognitive context-switching during rapid iteration. In a 10-hour sprint, module organization is an optimization that yields negative returns: it adds file navigation time without improving testability (no tests exist) or runtime performance. A monolithic file is trivially greppable, fully self-contained for LLM code synthesis context, and eliminates any risk of import-order bugs at module initialization time. The correct time to decompose into `src/` modules is when the codebase is productionized and test coverage warrants it.

---

### 3.18 Flat LangGraph Graph vs. LangGraph Sub-Graphs

**Problem:** The design spec described LangGraph sub-graphs (`StateGraph(DocumentSubState)`) — one per document — dispatched via `Send` from the parent graph, with `router_node`, a chunk node, `route_matrix_to_workers` as a conditional edge, extraction workers, and `handoff_node` all as distinct LangGraph nodes within each sub-graph. The key challenge was propagating `global_inbox` and `summary_store` from child sub-graph state back to parent state.

**Selected Paradigm:** Flat `StateGraph(ParentState)` with `process_document` as a single async node.

The actual graph has exactly three nodes:

```
directory_crawler → process_document (dispatched N times via Send) → master_round_table_node
```

`process_document` is a single async LangGraph node that receives `{source_material, file_name}` via `Send` from `dispatch_documents` (a conditional edge), executes all per-document logic sequentially in Python (router → chunk → fan-out matrix → `asyncio.gather` worker pool → handoff return), and returns `{"global_inbox": [...], "summary_store": {...}}` directly to `ParentState` via LangGraph's reducers. No sub-graph exists.

**Rejected Alternative:** `StateGraph(DocumentSubState)` sub-graphs with LangGraph `Send` for workers, as specified in the design.

**Rationale:** LangGraph sub-graph state propagation requires explicit key mapping between child state and parent state at sub-graph exit. For `global_inbox` (a list with an `add` reducer) and `summary_store` (a dict with a merge reducer), implementing this reliably requires understanding LangGraph's internal sub-graph channel scoping rules, which are non-obvious and have changed across minor versions. The risk of silent data loss at the sub-graph boundary — where a mis-scoped key produces no error but drops all records — is unacceptable in a sprint context with no test harness. The flat architecture eliminates this boundary entirely: `process_document` returns a plain Python dict, and LangGraph applies the parent-state reducers directly and predictably. All 12 non-negotiable invariants are satisfied. The structural difference is invisible at the invariant level.

---

### 3.19 `asyncio.gather` for Worker Pool vs. LangGraph `Send` for Workers

**Problem:** Per the spec, extraction workers were to be dispatched via LangGraph `Send("extraction_worker", payload_dict)` as individual LangGraph nodes within a sub-graph. Without sub-graphs, an alternative mechanism is needed to run the `Chunks × Lenses` cross-product concurrently.

**Selected Paradigm:** `asyncio.gather` inside `process_document`.

```python
worker_results = await asyncio.gather(
    *[extraction_worker(p) for p in payloads],
    return_exceptions=True,
)
```

`extraction_worker` is a standalone async function (not a LangGraph node). `asyncio.gather` runs all payloads concurrently within the event loop. `return_exceptions=True` ensures one failed coroutine does not cancel the others — it returns the exception object in the results list, where it is filtered out during result collection.

**Rejected Alternative:** LangGraph `Send("extraction_worker", ...)` dispatching workers as graph nodes.

**Rationale:** LangGraph `Send`-dispatched node calls have per-call overhead (state serialization, checkpoint writes, graph traversal). For a `Chunks × Lenses` matrix that can produce 200–500 worker calls per document, this overhead compounds materially. `asyncio.gather` is the idiomatic asyncio pattern for this fan-out shape and has no per-call graph overhead. The `extraction_worker` function itself is unchanged — same signature, same invariants, same behavior. The concurrency model is equivalent. `max_concurrency=50` at the LangGraph graph invocation level still throttles parallel `process_document` node executions (i.e., parallel document pipelines), which is the dominant concurrency concern for rate limiting.

---

### 3.20 Three LLM System Prompts — Implementation Choices

**Problem:** The design spec referenced a router LLM call and an extraction LLM call but did not fully specify the system prompt content, the anchored prompt assembly pattern for extraction, or the synthesis prompt structure. These needed to be defined during implementation.

**Selected Paradigm:** Three module-level system prompt constants — `ROUTER_SYSTEM_PROMPT`, `EXTRACTION_SYSTEM_PROMPT`, `SYNTHESIS_SYSTEM_PROMPT`.

**Router (`ROUTER_SYSTEM_PROMPT`):** Instructs the model to produce a 200–400 word semantic summary and a list of 3–7 extraction lens identifiers. Lists all valid lens names. Bound to `structured_router.ainvoke([{system}, {user}])` where user content is the full document text. Single call per document per Invariant R1.

**Extraction (`EXTRACTION_SYSTEM_PROMPT`):** Instructs the model to act as a risk extraction specialist, apply a named lens to a target chunk, and return one `UniversalForm`-shaped finding. The anchored prompt passed as user content concatenates: lens name, `GLOBAL FILE CONTEXT` (the `semantic_summary`), and `TARGET CHUNK` (the chunk text with source file and chunk index). The lens name is injected into the user prompt rather than the system prompt so that the `EXTRACTION_SYSTEM_PROMPT` constant is reused across all workers without modification.

**Synthesis (`SYNTHESIS_SYSTEM_PROMPT`):** Instructs the model to synthesize all extraction records into a structured Markdown risk report with defined sections: Executive Summary, Critical Findings (score ≥ 8), Cross-Document Contradictions, Risk Analysis by Category, Coverage Gaps, and Recommendations. Uses `llm.ainvoke` (not `structured_llm`) to produce free-form Markdown rather than a constrained schema.

**AIMessage content handling:** The synthesis response `content` field can be either `str` or `List[dict]` depending on provider and model version. `master_round_table_node` handles both cases:

```python
if isinstance(content, str):
    report = content
elif isinstance(content, list):
    parts = [p if isinstance(p, str) else p.get("text", "") for p in content]
    report = "".join(parts)
```

**Rejected Alternative:** A single system prompt reused across all LLM call types.

**Rationale:** Router, extraction, and synthesis calls have fundamentally different output shapes and purposes. Forcing them through a shared prompt would require conditional branching inside the prompt and would degrade structured output reliability. Module-scope constants are free to define and make each call's intent immediately readable during sprint debugging.

---

### 3.21 Gemini Model Update: `gemini-2.0-flash` → `gemini-2.5-flash`

**Problem:** During deployment, the router phase failed immediately with a 400 error from the Google AI API. `gemini-2.0-flash` was not available for new Google AI API accounts or accounts migrated to the new billing tier.

**Error observed:**

```
google.api_core.exceptions.InvalidArgument: 400 gemini-2.0-flash is not supported
for generateContent. Please use a different model.
```

**Selected Paradigm:** Update `router_llm` singleton to use `gemini-2.5-flash`.

```python
# Before:
router_llm = ChatGoogleGenerativeAI(model="gemini-2.0-flash")

# After:
router_llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash")
```

This change is applied in `pipeline.py` and reflected in the `INTERFACE_CONTRACT.md` module singleton table.

**Rejected Alternative:** Revert to an older, universally supported Gemini model (e.g. `gemini-1.5-flash`).

**Rationale:** `gemini-2.5-flash` is the direct successor model and is available on all account tiers. It maintains the same API interface and structured output support via `langchain-google-genai`. Using the most current available model is preferable for capability and output quality. No prompt changes were required.

**Note on free-tier quota:** Even with the correct model, Google AI free-tier quota (requests per minute and requests per day) is exhausted almost immediately by the routing phase on a 3-file data room. Paid Google Cloud billing must be enabled for reliable operation.

---

### 3.22 aiohttp Version Incompatibility and Runtime Upgrade

**Problem:** After installing `requirements.txt`, the pipeline failed at first import with:

```
AttributeError: module 'aiohttp' has no attribute 'ClientConnectorDNSError'
```

**Root cause:** `langchain-google-genai` (and its transitive dependency `google-auth-httpx-transport` or similar) references `aiohttp.ClientConnectorDNSError`, which was added in `aiohttp>=3.10`. The default `aiohttp` version in the Python 3.11-slim Docker image at the time of the sprint was `3.9.5`, which does not have this symbol.

**Selected Paradigm:** Runtime upgrade of `aiohttp` to `>=3.13.5`.

```bash
pip install "aiohttp>=3.13.5"
```

This resolved the import error immediately. `aiohttp>=3.13.5` is backwards-compatible with the rest of the dependency stack.

**Rejected Alternative:** Pin `aiohttp>=3.13.5` in `requirements.txt` at build time (correct long-term fix).

**Rationale for current state:** The runtime upgrade was applied as an emergency fix during deployment to avoid a Docker rebuild cycle. The correct permanent resolution is to add `aiohttp>=3.13.5` to `requirements.txt` so the Docker image includes the correct version from the start. This has not yet been applied to the committed `requirements.txt`. It should be the first change in the next maintenance pass.

**Impact:** Without the correct `aiohttp` version, no LLM calls can be made — the Google SDK cannot establish HTTP connections. This is a hard blocker at startup, not a degraded-operation condition.

---

## 4. Implementation Sprint Blueprint (10 Hours)

### Phase 1 — Environment Baseline & Adversarial Test Datasets [Hours 1–2]

- Establish Python runtime with `langgraph`, `pydantic v2`, `langchain`, `langchain-google-genai`, `langchain-anthropic`, `langchain-text-splitters`, and `nest_asyncio`.
- Build a deterministic mock data room directory with exactly three text payloads containing embedded cross-document contradictions (e.g., File A: proprietary code warranty; File B: GPL v3 upstream dependency declaration; File C: liability cap clause).
- Implement and validate the directory crawler with `try/except` binary file filtering. Populate `ParentState["crawled_files"]` with the list of successfully read filenames before any sub-graph runs.

### Phase 2 — Router Synthesis, Schema Wiring & State Handoff [Hours 3–5]

- Wire `DocumentSubState` and `ParentState` schemas including `summary_store: Dict[str, str]` and `crawled_files: List[str]`.
- Implement `router_node` using `structured_router = router_llm.with_structured_output(RouterOutput)` as a module-level singleton. Single call per document emits both `semantic_summary` and `dynamic_topology` into `DocumentSubState`.
- Implement the single handoff exit node (post-workers) that atomically maps `DocumentSubState["semantic_summary"]` → `ParentState["summary_store"][file_name]` and `DocumentSubState["local_inbox"]` → `ParentState["global_inbox"]` in one return dict.
- Instantiate and bind `UniversalForm` via `.with_structured_output(UniversalForm)` on Claude Sonnet as a module-level singleton (`structured_llm`).

### Phase 3 — Fork Matrix Construction & Async Extraction [Hours 6–7]

- Integrate `RecursiveCharacterTextSplitter(chunk_size=4000, chunk_overlap=800)` for chunking (~1,000 token target; splitter measures characters, not tokens).
- Build `route_matrix_to_workers(state: DocumentSubState)` cross-product mapper. Read `semantic_summary` from `state["semantic_summary"]` — written by `router_node` earlier in the same sub-graph; no parent state access needed. Stamp it into each `WorkerPayload`. Emit `Send("extraction_worker", worker_config.model_dump())` — primitive dicts only.
- Implement `extraction_worker(payload_dict)` (no `state` parameter) reading `semantic_summary` from payload, assembling the anchored prompt, calling `await structured_llm.ainvoke(...)`, and returning a fully constructed `ExtractionRecord` object inside `{"local_inbox": [record]}`. Wrap in `try/except` — return `{"local_inbox": []}` on failure.
- Verify `max_concurrency=50` is passed at graph invocation level.

### Phase 4 — Synthesis, Blind Spot Detection & Deployment [Hours 8–10]

- Implement `detect_blind_spots(crawled_files, global_inbox)` Python filter inside Master Round-Table Node preamble. Prepend blind spot block to synthesis prompt.
- Implement `compress_inbox(global_inbox, limit=500)` Python filter immediately after blind spot detection. Sort descending by `implied_liability_score`, truncate to 500 records, prepend truncation warning block if truncation occurred. Pass compressed records — not the raw `global_inbox` — to the synthesis prompt.
- Deploy Master Round-Table Node with single-shot long-context Markdown streaming synthesis.
- Wire Streamlit output layer: `nest_asyncio.apply()` + `get_event_loop().run_until_complete()` bridge + `st.markdown()` for report rendering.
- Build Docker image (no Chroma dependency), inject API keys via `-e`, deploy to EC2.

---

## 5. Open Constraint Checklist

| Constraint | Status | Note |
|---|---|---|
| `compress_inbox()` guard in Round-Table preamble | Required | Sorts by `implied_liability_score` desc, truncates to 500 records; prepends warning block if truncated |
| `WorkerPayload` fields are JSON-primitive only | Required | No `datetime`, `numpy`, or complex classes; `Send` fails silently otherwise |
| `WorkerPayload` carries `semantic_summary` | Required | Injected at dispatch time in `route_matrix_to_workers` from `DocumentSubState`; `extraction_worker` has no `state` parameter |
| `extraction_worker` has no `state` parameter | Required | LangGraph does not inject parent state into Send-dispatched nodes; the parameter resolves empty |
| `extraction_worker` wrapped in `try/except` | Required | Returns `{"local_inbox": []}` on failure; one bad worker must not crash the async pool |
| Singleton LLM bindings | Required | Both `structured_router` and `structured_llm` instantiated once at module scope |
| `summary_store` uses merge reducer | Required | `Annotated[Dict[str, str], lambda a, b: {**a, **b}]` — without this, parallel sub-graph handoffs overwrite each other |
| Single post-workers handoff writes both `summary_store` and `global_inbox` | Required | One atomic return dict; no pre-fan-out handoff needed — `route_matrix_to_workers` reads from `DocumentSubState`, not `ParentState` |
| `extraction_worker` uses `await .ainvoke()` | Required | Sync `.invoke()` blocks the event loop inside an async worker pool |
| `extraction_worker` returns `ExtractionRecord` object | Required | Not a raw dict; `global_inbox` reducer is typed `List[ExtractionRecord]` |
| Directory crawler populates `crawled_files` | Required | Required by `detect_blind_spots()` in Round-Table Node preamble |
| Directory crawler `try/except` | Required | Must catch `UnicodeDecodeError`, `IsADirectoryError`, `PermissionError` |
| `max_concurrency=50` via graph invocation config | Required | No module-level `asyncio.Semaphore` |
| Streamlit async bridge | Required | `asyncio.run()` crashes inside Streamlit's event loop; use `nest_asyncio.apply()` + `get_event_loop().run_until_complete()` instead |
| Chroma removed from dependencies | Required | No import, no instantiation; not part of any node or schema |

---

---

### 3.23 Streamlit Async Bridge — ThreadPoolExecutor Replaces nest_asyncio

**Problem:** The spec (Invariant I2) prescribed `nest_asyncio.apply()` + `asyncio.get_event_loop().run_until_complete()` as the Streamlit async bridge. At runtime, LangGraph's concurrent Send dispatch — which creates multiple parallel async tasks via the sub-graph fan-out — produced `RuntimeError: Task got Future attached to a different loop`. The `nest_asyncio` patch handles a single nested `run_until_complete` call but does not fully isolate LangGraph's internal task scheduler from Streamlit's event loop under high concurrency.

**Selected Paradigm:** Run the pipeline in a dedicated `ThreadPoolExecutor` thread with a fresh `asyncio.new_event_loop()`.

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

The dedicated thread owns a completely isolated event loop. LangGraph's task scheduler, the httpx clients inside LangChain's LLM wrappers, and all async futures are created and resolved within the same loop. No cross-loop future references are possible.

**Rejected Alternative:** `nest_asyncio.apply()` + `get_event_loop().run_until_complete()` (Invariant I2 original prescription).

**Rationale:** `nest_asyncio` patches the running loop to allow nested `run_until_complete` calls, which is sufficient for simple single-coroutine invocations. It does not prevent LangGraph from creating tasks that reference different loop instances when running dozens of parallel extraction workers via Send dispatch. The thread-based approach provides full loop isolation without patching. `nest_asyncio` remains in `requirements.txt` as a declared dependency; `nest_asyncio.apply()` is no longer called at module load.

---

*Document Version: v13 — Post-Implementation*
*Patches applied: Router collapse (3.15), Blind spot demotion (3.16), summary_store state field + merge reducer, worker async fix, ExtractionRecord return type, Streamlit async bridge, topology diagram corrected, Chroma removal, extraction_worker state parameter removed + semantic_summary moved to WorkerPayload (v8), extraction_worker try/except added (v8), sub-graph topology diagram annotation corrected to match v8 worker contract (v9), route_matrix_to_workers signature fixed from illegal two-parameter edge function to single-parameter DocumentSubState edge function reading semantic_summary from sub-graph state (v9), sub-graph diagram split into two explicit handoff moments to eliminate single-node conflation ambiguity (v10), compress_inbox() record-count guard added to 3.10 with 500-record threshold and implied_liability_score sort (v10), pre-fan-out Handoff Moment 1 removed — route_matrix_to_workers reads semantic_summary from DocumentSubState not ParentState; single post-workers handoff now writes both summary_store and global_inbox atomically; diagram note, Decision 3.3, constraint checklist, and Phase 2 sprint blueprint updated accordingly (v11), post-implementation decisions 3.17–3.22 added: monolithic pipeline.py rationale, flat graph vs sub-graphs architectural deviation, asyncio.gather vs LangGraph Send for workers, three system prompt constants, gemini-2.0-flash → gemini-2.5-flash model update, aiohttp version incompatibility (v12)*
*Target Consumer: Claude Sonnet 4.5+ for implementation code synthesis*
