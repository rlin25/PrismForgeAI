# Prompt: Rewrite Glossary

**Purpose:** Rewrite the design-phase glossary as a post-implementation reference organized for two audiences: recruiters reading the repo, and the developer returning to the codebase.
**When to use:** After all subplans are implemented and the codebase is complete.
**Run after:** `05_feedback_loop.md` — verify definitions against the actual implementation before rewriting.

---

## Before Running This Prompt

The source file list must be updated once implementation is complete. All other values are pre-filled for PrismForge AI v4.

| Item | Value |
|---|---|
| Project name | PrismForge AI |
| Current version | v4 |
| Domain | Corporate due diligence / liability risk analysis |
| Source files | **Fill in after implementation — see placeholder below** |

---

## Source Files

Replace `{SOURCE_FILES}` with the actual implemented source files before running. Expected structure based on subplans:

```
{SOURCE_FILES}
# Expected (confirm against actual implementation):
# src/schemas.py, src/state.py, src/crawler.py, src/router.py,
# src/chunker.py, src/matrix.py, src/worker.py, src/handoff.py,
# src/roundtable.py, src/graph.py, app.py
```

---

## Prompt

Rewrite `docs/GLOSSARY.md` from scratch. The current version was written during the design phase and may not reflect the implemented codebase exactly. The new glossary serves two audiences: recruiters (technical and nontechnical) reading the repository, and the developer returning to the codebase after time away.

Organize the glossary into three parts:

---

### Part 1 — Domain and System Overview

Define all corporate due diligence terms and high-level system concepts. This section should be readable by a nontechnical recruiter with no prior knowledge of due diligence or multi-agent systems. Assume the reader has already read the README.

Include:

**Domain terms:**
- Data room
- Due diligence
- Liability
- Indemnification
- Warranty
- IP ownership / intellectual property
- License compliance
- Liability cap
- Data privacy / data processing agreement
- Counterparty
- Cross-reference / contradiction (in the context of document review)

**High-level system concepts (plain English only — no implementation detail):**
- What the system does and what it produces
- What a lens is (a named area of risk the system looks for)
- What a semantic summary is and why the system generates one
- What an extraction record is and what it contains
- What a risk score is and how it is used
- What a blind spot is and why the system reports it

Do not reference specific files, functions, schemas, or implementation patterns in Part 1.

---

### Part 2 — Architecture and Execution

Define the system's logic layer. This section bridges the domain overview and the implementation reference — a recruiter reading the architecture diagram or the README's pipeline description will encounter these terms before opening any source file.

Include:

**Pipeline stages (in execution order):**
- Directory crawler
- Router (including single-call design — one call produces both summary and lens list)
- Chunking (including `chunk_size=4000` characters, `chunk_overlap=800` characters, and why overlap exists)
- Matrix fan-out / `Chunks × Lenses` cross-product
- Extraction worker pool
- Handoff node (one per sub-graph, fires after all workers complete)
- Master Round-Table Node

**Architectural patterns:**
- LangGraph sub-graph sandbox (one per document, parallel execution)
- `Send` dispatch (how LangGraph fans out parallel jobs)
- Dynamic Semantic Topology (DST) — the adaptive per-document lens selection that defines this version
- Merge reducer (why `summary_store` uses it, what happens without it)
- Append reducer (`add`) on `global_inbox` and `local_inbox`
- Module-level singletons (`structured_router`, `structured_llm`)
- `max_concurrency: 50` and why it replaces a module-level semaphore
- Structured output (how Pydantic schemas constrain LLM responses at the API level)

**Safety and correctness mechanisms:**
- Binary file filtering in the crawler
- Worker `try/except` (returns `{"local_inbox": []}` on failure)
- `detect_blind_spots()` — what it checks, where it runs, what it produces
- `compress_inbox()` — the 500-record ceiling, sort order (risk score descending), and truncation warning
- `nest_asyncio` bridge — why it is needed and what `asyncio.run()` breaks

---

### Part 3 — Implementation Reference

File-by-file breakdown of implementation-specific terms. Organize by source file in execution order. For terms that span multiple files, define them at their source file and note where else they appear.

Cover these files in order:
`{SOURCE_FILES}`

For each file, define only the terms that are non-obvious to a developer reading it for the first time. Skip terms that are self-explanatory from the code. For each non-obvious term, cross-reference the invariant identifier from `docs/INTERFACE_CONTRACT.md` where applicable (e.g., "Governed by Invariant X1 — see interface contract").

Priority terms to define in Part 3 (at minimum):

- `RouterOutput` — schema shape, which node produces it, which nodes consume it
- `UniversalForm` — schema shape, the `implied_liability_score` range and meaning
- `ExtractionRecord` — the unit of the inbox channels; why it wraps `UniversalForm` rather than being flat
- `WorkerPayload` — why `semantic_summary` is a required field carried inside the payload (Invariant W2)
- `ParentState` vs. `DocumentSubState` — what each holds, which nodes read/write each, when `DocumentSubState` is discarded
- `route_matrix_to_workers` — why it has a single `state` parameter (Invariant E1) and why it emits `.model_dump()` dicts rather than Pydantic instances (Invariant E3)
- The `extraction_worker` single-parameter signature — why there is no `state` parameter (Invariant X1)
- The `await ainvoke()` requirement in `extraction_worker` — why sync `.invoke()` is a violation (Invariant X3)

---

## Constraints

- Do not carry over definitions from the current `docs/GLOSSARY.md` without verifying them against the actual implementation.
- Do not define terms that are fully explained in the README — reference the README instead.
- Write Part 1 for a nontechnical reader. Write Parts 2 and 3 for a technical reader.
- Cross-reference invariant identifiers from `docs/INTERFACE_CONTRACT.md` wherever a term is governed by a binding constraint.
- Output the full glossary as a single `docs/GLOSSARY.md` file.

Reference documents:
- `plans/00_MASTERPLAN.md` — authoritative for non-negotiable invariants and build sequence
- `docs/DESIGN.md` — authoritative for design decisions and rejected alternatives
- `docs/INTERFACE_CONTRACT.md` — authoritative for all signatures, schemas, reducers, and invariants
