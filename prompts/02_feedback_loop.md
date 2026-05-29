# Prompt: Phase 7 — Feedback Loop Documentation Update

**Phase:** Post-implementation feedback loop
**When to use:** After all subplans are complete and all acceptance gates pass. Run this before beginning v5 design.
**Produces:** Updated versions of all design documents, reconciled against the implemented codebase.

---

## Before Running This Prompt

The source file list, test file list, and first new decision number must be filled in once implementation is complete. All interface checks and decision checks are pre-filled from the v4 design documents.

| Item | Value |
|---|---|
| Project name | PrismForge AI |
| Current version | v4 |
| Next version | v5 |
| Source files | **Fill in after implementation** |
| Test files | **Fill in after implementation** |
| First new decision number | **Count locked decisions in `docs/DESIGN.md` and add 1** |

---

## What This Prompt Does

The design documents were written before the code. This prompt reconciles them with what was actually built. It does not redesign anything — it records reality. Every update must be traceable to something observable in the codebase.

The output is a set of fully integrated updated documents, not bolt-ons. Each document is regenerated as a complete, clean file. Nothing is appended to the end.

---

## Inputs

Read every file in the following locations before doing anything else:

**Source files (the implemented codebase):**
`{SOURCE_FILES}`

**Test files:**
`{TEST_FILES}`

**Design documents (the plan):**
- `plans/00_MASTERPLAN.md`
- `docs/DESIGN.md`
- `docs/GLOSSARY.md`
- `docs/INTERFACE_CONTRACT.md`
- `docs/setup_notes.md` *(create this file if it does not exist yet — see Output Documents section)*
- `prompts/01_design_methodology.md`

Read all of them before forming any conclusions. Do not update any document until all source files have been read.

---

## Inspection Pass

Before writing any updates, work through the following four inspection categories systematically. For each finding, note: which document it affects, what the discrepancy is, and whether it is a correction (the plan was wrong), a gap (the plan was silent), or a status update (the plan was right but the status language is stale).

Do not skip categories because they seem unlikely to have findings. Every category must be checked.

---

### Category 1 — Interface Drift

Compare every specification in `docs/INTERFACE_CONTRACT.md` against the actual implemented code. Check each of the following explicitly:

**Schema shapes:**
- `RouterOutput`: does the implementation have exactly `semantic_summary: str` and `dynamic_topology: List[str]`? No extra or missing fields?
- `DependencyLink`: does it have exactly `target_file: str`, `target_concept: str`, `nature_of_contradiction: str`?
- `UniversalForm`: does it have `entity_or_concept: str`, `factual_evidence_quote: str`, `implied_liability_score: int` (ge=1, le=10), `cross_reference_dependencies: List[DependencyLink]` (default [])?
- `ExtractionRecord`: does it have `lens_name: str`, `source_file: str`, `chunk_index: int`, `payload: UniversalForm`?
- `WorkerPayload`: does it have exactly `lens_name: str`, `source_file: str`, `chunk_index: int`, `target_chunk_text: str`, `semantic_summary: str`? No extra fields?

**State schemas:**
- `ParentState`: does `summary_store` use the merge reducer (`lambda a, b: {**a, **b}`)? Does `global_inbox` use `operator.add`? Does `crawled_files` have no reducer?
- `DocumentSubState`: is `gap_detected` absent? Is `blind_spots` absent? (Both were removed in v6 of the design.)

**Node signatures:**
- `directory_crawler`: single `ParentState` parameter, returns `{"crawled_files": List[str]}`?
- `router_node`: `async def router_node(state: DocumentSubState)`, returns `{"semantic_summary": str, "dynamic_topology": List[str]}`?
- `route_matrix_to_workers`: single `state: DocumentSubState` parameter — NOT a two-parameter signature?
- `extraction_worker`: single `payload_dict: Dict[str, Any]` parameter — NO `state` parameter?

**Singleton invariants:**
- Are `router_llm`, `structured_router`, `llm`, `structured_llm` all defined at module scope, not inside any function?
- Is there any `asyncio.Semaphore` at module scope? (Invariant S2 forbids it.)
- Is there any Chroma import anywhere? (Invariant S3 forbids it.)

**Concurrency:**
- Is `max_concurrency: 50` passed at graph invocation? Is it the only concurrency control?

**Chunking:**
- Is `RecursiveCharacterTextSplitter` called with `chunk_size=4000` and `chunk_overlap=800`?

**Handoff:**
- Is there exactly one handoff node per sub-graph? Does it fire after workers complete? Does it write both `summary_store` and `global_inbox` in a single return dict?

**Streamlit bridge:**
- Is `nest_asyncio.apply()` called once at startup? Is `asyncio.run()` absent? Is `get_event_loop().run_until_complete()` the invocation pattern?

Flag any discrepancy, no matter how small. A field renamed from `implied_liability_score` to `risk_score` is a discrepancy.

---

### Category 2 — Decisions That Changed Under Implementation Pressure

Read through `docs/DESIGN.md`. For each locked decision, ask: does the implemented code actually reflect this decision, or was it quietly adjusted during the build?

Pay particular attention to:
- The single-call router (Invariant R1) — was there any pressure to split summary and lens list into two separate calls?
- The `Send` primitive-dict constraint (Invariant E3 / W1) — was any Pydantic instance passed directly?
- The pre-fan-out handoff removal (Invariant in masterplan §5) — did a pre-fan-out handoff reappear?
- The `semantic_summary` travel path (Invariant W2) — does it travel inside `WorkerPayload`, or was it accessed from state somewhere?
- The Chroma / vector store constraint (Invariant S3) — was any vector store code introduced and then removed, or does any dead import remain?
- The `asyncio.run()` prohibition — was it used anywhere, even in a commented block?

If any decision was modified, record the modification as a new decision addendum with the same format: what changed, why it changed, and what was rejected.

---

### Category 3 — Implementation Details That Became Decisions

The interface contract explicitly defers the following to implementation. Read the relevant source files and record what was actually decided for each:

- **LLM prompt templates for `router_node`** — the exact prompt structure, system message, and human message format used to elicit `RouterOutput` in a single call.
- **LLM prompt template for `extraction_worker`** — the prompt structure used to elicit `UniversalForm` from a chunk + lens + semantic summary, including how the lens name is communicated to the model.
- **LLM prompt template for `master_round_table_node`** — the synthesis prompt structure, including how `detect_blind_spots()` output and `compress_inbox()` output are formatted before being handed to the LLM.
- **Error handling specificity** — does the `try/except` in `extraction_worker` catch all exceptions, or specific ones? What is logged on failure?
- **Streamlit UI structure** — how does the user specify the data room path? Is there a progress indicator during pipeline execution? How is the final report rendered?
- **Docker base image and exposed port** — what image is used, what port is exposed, how are API keys injected.

Each of these should be added to `docs/DESIGN.md` as new decisions (Decision {FIRST_NEW_DECISION_NUMBER} onward) using the standard format: Decision, Reasoning, Rejected option. They are not new design choices — they are implementation choices that need to be recorded before they are forgotten.

---

### Category 4 — New Known Issues

Read `requirements.txt` (or equivalent) and note the actual pinned versions of all dependencies. Then check:

- Were there any dependency conflicts, version issues, or import errors encountered during the build?
- Did `langchain-google-genai` or `langchain-anthropic` require any version pinning to avoid breaking changes?
- Did `nest_asyncio` introduce any unexpected behavior with the Streamlit version in use?
- Do any test files contain comments about workarounds, unexpected behavior, or deferred fixes?
- Were there any issues with the Docker build or EC2 deployment that are not documented?

Add any new issues to `docs/setup_notes.md` in the Known Issues format.

---

## Output Documents

Generate fully integrated updated versions of all documents. Do not append to existing documents — regenerate each one clean.

### 1. `docs/DESIGN.md`

- Update the status header to reflect implementation complete.
- Update "Next phase" to "v5 design."
- Record any decisions that changed (Category 2 findings) as addenda to the relevant existing decisions, clearly marked as implementation-phase updates.
- Add all Category 3 findings as new numbered decisions ({FIRST_NEW_DECISION_NUMBER} onward) using the standard format: Decision, Reasoning, Rejected option.
- Do not alter any existing decision text. Additions only.

### 2. `docs/INTERFACE_CONTRACT.md`

- Update the status header to reflect implementation complete.
- Correct any interface drift found in Category 1. For each correction, add a one-line note directly below the corrected specification: `[Updated post-implementation: <what changed and why>]`
- Do not alter specifications that matched the implementation.

### 3. `plans/00_MASTERPLAN.md`

- Update all status headers to reflect implementation complete.
- Update the folder structure section if the actual folder structure differs from the plan.
- Update component descriptions if any component behaves differently than described.
- Do not redesign anything — only correct descriptions that no longer match the code.

### 4. `docs/setup_notes.md`

If this file does not exist, create it with the following structure:

```markdown
# Setup Notes — PrismForge AI v4

## Status
Implementation complete. Phase 7 reconciliation in progress.

## Install

[Fill in from requirements.txt and actual install commands used]

## Pinned Versions

[Table of all pinned dependency versions from requirements.txt]

## Environment Variables

| Variable | Required | Purpose |
|---|---|---|
| ANTHROPIC_API_KEY | Yes | Authenticates Claude Sonnet for extraction workers and synthesis |
| GOOGLE_API_KEY | Yes | Authenticates Gemini Flash for the router |

## Running Locally

[Fill in from app.py entry point and actual run command]

## Docker Build and Run

[Fill in from Dockerfile and actual docker commands used]

## Known Issues

[Fill in from Category 4 inspection findings]
```

If the file exists, update it with: pinned versions table from `requirements.txt`, any new known issues from Category 4, and a status update.

### 5. `docs/GLOSSARY.md`

- Update any term definitions that no longer match the implementation. Cross-reference with the actual source files, not the design documents.
- Do not add new terms — that is the job of `03_rewrite_glossary.md`.
- Do not alter definitions that remain accurate.

### 6. `prompts/01_design_methodology.md`

- Update the status line at the top of the document to reflect Phase 7 complete.
- Do not alter any other section.

---

## Constraints

- Every update must be traceable to something in the source files. Do not infer, assume, or invent.
- If a source file is ambiguous, flag the ambiguity explicitly rather than guessing.
- If a design document section has no corresponding discrepancy, reproduce it unchanged.
- Generate all documents in a single pass after completing the full inspection. Do not generate documents mid-inspection.
- Use the pending changes list method: maintain a running list of all findings as you inspect, then generate documents from the list at the end.
