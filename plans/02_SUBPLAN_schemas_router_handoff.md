# SUBPLAN 02 — Schemas, Router & State Handoff [Hours 3–5]

Parent: `00_MASTERPLAN.md` · Spec: Decisions 3.1, 3.3, 3.7, 3.8, 3.9, 3.15; §2; Phase 2.

## Goal

Wire all state schemas, the single-call router, the singleton LLM bindings, and
the one post-workers handoff node.

## Tasks

### 1. Schemas (verbatim from §2)
- `RouterOutput` — `semantic_summary: str`, `dynamic_topology: List[str]`.
- `DependencyLink`, `UniversalForm`, `ExtractionRecord`.
- `WorkerPayload` — **must include `semantic_summary: str`**. JSON-primitive
  fields only (no `datetime`/`numpy`/complex classes).
- `ParentState`:
  - `summary_store: Annotated[Dict[str, str], lambda a, b: {**a, **b}]` — merge
    reducer is mandatory; default overwrite loses all but the last sub-graph.
  - `crawled_files: List[str]` — no reducer.
  - `global_inbox: Annotated[List[ExtractionRecord], add]`.
  - `directory_path`, `master_risk_report`.
- `DocumentSubState`: `source_material`, `file_name`, `semantic_summary`,
  `dynamic_topology`, `document_chunks`,
  `local_inbox: Annotated[List[ExtractionRecord], add]`.
  **Do not** add `gap_detected` or `blind_spots` — removed in v6.

### 2. Router node (single combined call — Decision 3.15)
Module-level singleton, Gemini Flash, structured output:
```python
router_llm = ChatGoogleGenerativeAI(model="gemini-2.0-flash")
structured_router = router_llm.with_structured_output(RouterOutput)
```
`router_node(state: DocumentSubState)` issues **one** `await
structured_router.ainvoke(...)` and returns both `semantic_summary` and
`dynamic_topology` into `DocumentSubState`. One call per document — never two.

### 3. Extraction LLM singleton (Decision 3.9)
```python
llm = ChatAnthropic(model="claude-sonnet-4-20250514")
structured_llm = llm.with_structured_output(UniversalForm)
```
Instantiate once at module scope — never inside a worker.

### 4. Single handoff node (Decisions 3.1, 3.3)
Fires **after** workers complete. Synchronous, pure dict mapping:
```python
def handoff_node(sub_state: DocumentSubState) -> Dict[str, Any]:
    return {
        "global_inbox": sub_state["local_inbox"],
        "summary_store": {sub_state["file_name"]: sub_state["semantic_summary"]},
    }
```
There is **no** pre-fan-out handoff. `summary_store` is consumed only by the
Master Round-Table Node, which runs after all sub-graphs — so post-workers
population is always in time.

## Verification
- Router returns a populated `RouterOutput`; exactly one network round-trip per file.
- Two concurrent sub-graph handoffs both survive in `summary_store` (merge
  reducer working).
- Schemas import cleanly with no removed fields lingering.

## Gate to Phase 3
Router emits both fields in one call; handoff merges without overwriting.
