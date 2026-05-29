# Prompt: Generate Walkthrough Directory

**Purpose:** Generate a `walkthrough/` directory of annotated design rationale documents for every source file in the project.
**When to use:** After all subplans are implemented and the codebase is complete.
**Run order:** Step 4 of 6 — see `prompts/BATCH.md` for the full sequence.

---

## Before Running This Prompt

The source file list below must be updated once implementation is complete. All other values are pre-filled for PrismForge AI v4.

| Item | Value |
|---|---|
| Project name | PrismForge AI |
| Current version | v4 |
| Next version | v5 |
| Source files | **Fill in after implementation — see placeholder below** |

---

## Source Files

Replace `{SOURCE_FILES}` with the full list of implemented source files in logical execution order once Phase 6 is complete. Expected structure based on the subplans:

```
{SOURCE_FILES}
# Expected files (confirm against actual implementation):
# src/schemas.py               — Pydantic schemas (RouterOutput, DependencyLink, UniversalForm, ExtractionRecord, WorkerPayload)
# src/state.py                 — TypedDict state definitions (ParentState, DocumentSubState)
# src/crawler.py               — directory_crawler node
# src/router.py                — router_node, LLM singletons (structured_router, structured_llm)
# src/chunker.py               — chunking and contextual anchoring pointer construction
# src/matrix.py                — route_matrix_to_workers conditional edge function
# src/worker.py                — extraction_worker node
# src/handoff.py               — handoff_node
# src/roundtable.py            — master_round_table_node, detect_blind_spots(), compress_inbox()
# src/graph.py                 — LangGraph graph assembly and compilation
# app.py                       — Streamlit entry point, nest_asyncio bridge
# Dockerfile                   — container definition
```

Adjust this list to match what was actually built. File names and module boundaries may differ from the subplan estimates.

---

## Prompt

Create a `walkthrough/` directory in the project root. For each source file in the project, create a corresponding markdown file explaining it to someone who understands the overall system design but is reading the implementation for the first time.

Each walkthrough file should cover:

1. **Purpose** — what this file does and why it exists as a separate module. Reference the specific design decisions or invariants from `docs/INTERFACE_CONTRACT.md` that created it.
2. **Relationships** — what it imports from, what imports it, and what it deliberately does not touch.
3. **Decision rationale** — for non-obvious implementation choices, explain why the code is written that way rather than what it is doing. Reference invariant identifiers (S1, W1, P1, R1, E1–E4, X1–X5, D1, etc.) where relevant.
4. **What it does not do** — responsibilities explicitly excluded from this file and where those responsibilities live instead.
5. **v5 touch points** — which parts of this file are intentionally minimal in v4 and what will likely change in v5.

Do not explain syntax. Do not describe what lines of code do — describe why they exist. If a section of code is self-explanatory, skip it.

Name each walkthrough file to match its source file: `walkthrough/schemas.md` for `src/schemas.py`, `walkthrough/app.md` for `app.py`, and so on.

Source files to cover:
`{SOURCE_FILES}`

Reference documents:
- `docs/INTERFACE_CONTRACT.md` — authoritative for all signatures, invariants, and data shapes
- `docs/DESIGN.md` — authoritative for design decisions and rejected alternatives
- `plans/00_MASTERPLAN.md` — authoritative for build sequence and non-negotiable constraints

---

## Priority Walkthrough Files

The following files carry the most non-obvious design decisions and should receive the most thorough treatment:

**`src/matrix.py` / `route_matrix_to_workers`**
The conditional edge function has three non-obvious constraints: single `state` parameter only (Invariant E1), reads `semantic_summary` from sub-graph state not parent state (Invariant E2), and emits only primitive dicts via `.model_dump()` (Invariant E3). The walkthrough must explain why each constraint exists and what breaks if it is violated.

**`src/state.py` / State schemas**
The reducer annotations on `summary_store` (merge) and `global_inbox` (add) are the difference between a working parallel pipeline and one that silently loses data. The walkthrough must explain what happens without the merge reducer and why `crawled_files` intentionally has no reducer.

**`src/worker.py` / `extraction_worker`**
The single-parameter signature (Invariant X1), `await ainvoke()` requirement (Invariant X3), and `try/except` returning `{"local_inbox": []}` on failure (Invariant X4) all have specific reasons. The walkthrough must make each explicit.

**`src/roundtable.py` / `master_round_table_node`**
The preamble / synthesis split — why `detect_blind_spots()` runs in pure Python before the LLM call, and why `compress_inbox()` enforces a 500-record ceiling — is the core correctness story for the final output. The walkthrough must explain both.

**`app.py` / Streamlit bridge**
The `nest_asyncio.apply()` + `get_event_loop().run_until_complete()` pattern exists because `asyncio.run()` raises inside Streamlit's internal event loop. The walkthrough must explain why this specific bridge was chosen and what `asyncio.run()` would break.

---

## Notes

- Run this after all subplans are complete and the Phase 7 feedback loop is done.
- The goal is decision rationale, not documentation. If a walkthrough file reads like a comment block, it is too shallow.
- Update the source file list before running — the expected files listed above are estimates from the subplans, not a guarantee of what was built.
