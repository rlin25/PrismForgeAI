# Prompt: README and Documentation Generation
**Phase:** Post-implementation documentation
**Produced by:** Rubber duck specification pass → Socratic pass → locked decisions
**Produces:** README.md, docs/DESIGN.md, docs/INTERFACE_CONTRACT.md, docs/GLOSSARY.md, prompts/README.md

---

## Context

This prompt is pre-filled for PrismForge AI v4. All project-specific values have been resolved from the design documents; no placeholder substitution is required before running.

---

## Inputs

The following project files must be read in full and cross-referenced when generating all documents:

- `docs/INTERFACE_CONTRACT.md`
- `docs/DESIGN.md`
- `plans/00_MASTERPLAN.md`
- `docs/GLOSSARY.md`
- `docs/setup_notes.md` *(generated during Phase 7; if not yet present, flag the gap and continue)*
- `prompts/01_design_methodology.md`

Do not invent details not present in the source documents. Flag any gap where the source documents are insufficient to complete a section.

---

## Project Identity

**Project name:** PrismForge AI
**Current version:** v4
**One-sentence description:** A multi-agent LangGraph pipeline that ingests a directory of corporate due diligence documents, runs a parallel extraction matrix across semantic chunks and domain-specific lenses, and synthesizes a single cross-referenced liability risk report.
**Target audience:** Technical and nontechnical recruiters evaluating a candidate for an AI engineering role.
**Role emphasis:** Multi-agent system design, async Python, LLM orchestration, structured output, production deployment.

**Design advance this version represents:** Dynamic Semantic Topology (DST) — the pipeline selects a document-specific set of extraction lenses per file by calling the router once per document, rather than applying a fixed schema to all documents uniformly. This means a patent filing gets IP-oriented lenses while a data-processing agreement gets privacy-oriented ones. The architecture is adaptive without requiring any code changes between runs.

---

## Context and Audience

You are generating documentation artifacts for a portfolio project called PrismForge AI, targeting technical and nontechnical recruiters for an AI engineering role. The role emphasizes multi-agent orchestration, async Python, LLM API integration (Anthropic Claude, Google Gemini), structured output with Pydantic, and production deployment with Docker.

The core argument this documentation must make is this: **in the age of AI, code is disposable — design principles are not.** This project was built design-first. The interface contract and locked design decisions all preceded the code. That methodology is the primary signal this documentation should convey, above the technical stack.

The development methodology involved structured human-AI collaboration throughout the design phase — Claude was used as a Socratic design partner to stress-test decisions, surface gaps, and formalize specifications. All architectural judgment and design choices belonged to the developer. This should be stated transparently and framed as a demonstration of AI fluency, not apologized for.

The specific design advance this version represents is the Dynamic Semantic Topology (DST) engine: adaptive per-document lens selection that makes the extraction matrix context-aware rather than static.

---

## Document 1 — README.md

**Audience:** both technical and nontechnical readers. Nontechnical readers should get full value from the first third and be able to stop. Technical readers should be pulled deeper.

**Structure:**

### 1. Opening statement
Direct and opinionated, not a generic project description. Lead with the design-first philosophy and what it means for how this project was built. This is the developer's voice and point of view, not a neutral description. Do not open with "PrismForge AI is a [technology] that..." or any equivalent generic opener.

### 2. What PrismForge AI does
Plain English, no jargon. What problem it solves (corporate due diligence is slow, manual, and misses cross-document contradictions), what the user input is (a folder of documents), and what the system produces (a structured liability risk report with cross-referenced findings). Two to three short paragraphs maximum.

### 3. Why the design matters
Surface the key architectural decisions as deliberate choices, not implementation details:
- Dynamic Semantic Topology: why adaptive lens selection matters for due diligence specifically (document types vary widely; a fixed schema misses domain-specific risk signals)
- The `Chunks × Lenses` extraction matrix: why cross-product fan-out produces better coverage than sequential processing
- Single-call router: why the summary and lens list are generated in one call rather than two (latency, coherence, the summary is already rich enough to drive lens selection)
- No vector store: why chunking on raw text is sufficient and why the Chroma dependency was removed (undefined dependency, vestigial architecture from a prior design)
- Blind spot detection: why surfacing zero-output files explicitly is a correctness requirement, not a feature

### 4. How it was built
Describe the development methodology: domain learning, Socratic design, interface contract, masterplan with four atomic subplans, implementation, feedback loop. Frame the AI collaboration explicitly — Claude as Socratic partner during design, all architectural judgment belonging to the developer. Note that `docs/INTERFACE_CONTRACT.md` and `docs/DESIGN.md` were both written and locked before any code was produced. Note that the design artifacts are version-stable while the code is intentionally disposable.

### 5. Companion documents
Link all companion documents with one-line descriptions framing who should read each and why:

- **docs/DESIGN.md** — consolidated architecture, design decisions, and locked choices with rejected alternatives. Start here if you want to understand how the system thinks.
- **docs/INTERFACE_CONTRACT.md** — every component's inputs, outputs, data types, and binding invariants. The stable contract the code was built against.
- **docs/GLOSSARY.md** — domain and technical terms defined for two audiences: nontechnical readers in Part 1, technical readers in Parts 2–3.

### 6. Tech stack
Clean table, no commentary needed.

| Layer | Technology |
|---|---|
| Orchestration | LangGraph |
| Schema validation | Pydantic v2 |
| LLM integration | LangChain, `langchain-anthropic`, `langchain-google-genai` |
| Text splitting | `langchain-text-splitters` |
| Concurrency | asyncio, `nest_asyncio` |
| Extraction LLM | Anthropic Claude Sonnet (`claude-sonnet-4-20250514`) |
| Routing LLM | Google Gemini Flash (`gemini-2.0-flash`) |
| UI | Streamlit |
| Deployment | Docker, AWS EC2 |

### 7. Setup and demo
Instructions to get the system running and the key interactions that tell the full demo story:
1. Clone the repo
2. Build and run the Docker container (with API key injection via `-e` flags — no keys in code or files)
3. Open the Streamlit UI, point it at a data room directory
4. Walk through: router assigns lenses per document → parallel extraction matrix runs → blind spot block prepended if any files produced no output → final risk report rendered in Markdown

**Tone:** direct, confident, opinionated. This README opens with a position.

---

## Document 2 — docs/DESIGN.md

**Audience:** technical readers who want architectural depth.

**Structure:**

### 1. System overview
Use the plain English mission paragraph from `plans/00_MASTERPLAN.md` verbatim as the opening.

### 2. The components
Each component described with its responsibility, its boundaries, and what it explicitly does not do. Draw from `docs/INTERFACE_CONTRACT.md`. Cover in pipeline order:
- Directory Crawler
- Router Node
- Chunking + Contextual Anchoring
- Matrix Fan-Out (`route_matrix_to_workers`)
- Extraction Worker Pool
- Handoff Node
- Master Round-Table Node (including `detect_blind_spots()` preamble and `compress_inbox()` guard)

### 3. Key architectural patterns
Describe the core patterns with the reasoning for why each exists as a distinct pattern:
- LangGraph sub-graph sandbox per document (why: parallel isolation, private state, clean handoff)
- `Chunks × Lenses` cross-product fan-out (why: exhaustive coverage without sequential bottleneck)
- Single-call router (why: latency, coherence — summary and lens list produced in one atomic response)
- Merge reducer on `summary_store` (why: parallel sub-graphs must accumulate, not overwrite)
- `Send` with primitive dicts only (why: LangGraph serialization constraint — Pydantic instances fail silently)
- Module-level singletons for LLM bindings (why: avoid redundant setup overhead across 50 concurrent workers)

### 4. Key design decisions
Surface the most interview-worthy decisions from `docs/DESIGN.md` with their reasoning and rejected alternatives. Prioritize:
- Dynamic Semantic Topology vs. fixed lens schema
- Chroma removal and the "no vector store" constraint
- One handoff per sub-graph (not two) — why the pre-fan-out handoff was a design error
- `max_concurrency: 50` at graph invocation vs. module-level `asyncio.Semaphore`
- `nest_asyncio` bridge for Streamlit (vs. `asyncio.run()`, which raises inside Streamlit's event loop)
- `compress_inbox()` guard at 500 records (vs. unbounded synthesis)

### 5. What this version deliberately excludes
The explicit out-of-scope list, framed as evidence of scope discipline:
- No vector store or semantic retrieval
- No user authentication or session management
- No incremental / resumable runs (full pipeline re-run on each invocation)
- No fine-grained per-lens concurrency limits (governed only by global `max_concurrency`)
- No PDF or binary file parsing (text-only input)

---

## Document 3 — docs/INTERFACE_CONTRACT.md

Use the existing `docs/INTERFACE_CONTRACT.md` as the source. Reproduce it with the following additions only:

- A one-paragraph introduction at the top explaining what an interface contract is, why it was written before the code, and how to use it as a reader.
- A one-line note at the top of each component section indicating which design decisions or invariants govern it.

Do not alter any existing specifications. The contract is locked.

---

## Document 4 — docs/GLOSSARY.md

Use the existing `docs/GLOSSARY.md` as the source. The glossary was written post-design and is already organized for two audiences (Part 1 for nontechnical readers, Parts 2–6 for technical readers). Reproduce it with the following addition only:

- A one-paragraph introduction explaining the two-audience structure and how to navigate it.

Do not rewrite or alter any existing definitions. They reflect the implemented architecture.

---

## Document 5 — prompts/README.md

Generate a one-page index for the `prompts/` folder explaining:
- What this folder is and why it exists
- The core argument: in AI-assisted development, the prompts and methodology that produce the code are as significant as the code itself
- How to read the folder — each prompt file listed with a one-line description of what phase it belongs to and what it produced

Frame this around the design-first philosophy established throughout the project. The prompts folder is evidence that the thinking happened before the code.

**Prompt file index to document:**

| File | Phase | Produced |
|---|---|---|
| `01_design_methodology.md` | Design phase (Phases 1–3) | Behavioral instructions and methods governing human-AI collaboration throughout design |
| `02_readme_generation.md` | Post-implementation (Phase 7+) | README.md, docs/DESIGN.md, docs/INTERFACE_CONTRACT.md, docs/GLOSSARY.md, prompts/README.md |
| `03_generate_walkthrough.md` | Post-implementation (Phase 7+) | `walkthrough/` directory of annotated design rationale for every source file |
| `04_rewrite_glossary.md` | Post-implementation (Phase 7+) | Polished glossary written for two audiences: recruiter and returning developer |
| `05_feedback_loop.md` | Phase 7 | Updated design documents reconciled against the implemented codebase |
| `06_generate_diagrams.md` | Post-implementation (Phase 7+) | Mermaid architecture diagram for README, Mermaid file flow diagram for walkthrough |

---

## Output Checklist

Before finishing, verify:

- [ ] README opens with a position statement, not a system description
- [ ] README serves nontechnical readers in the first third without requiring technical knowledge
- [ ] AI collaboration is framed transparently and offensively in the README
- [ ] README surfaces the DST design advance specifically
- [ ] DESIGN.md key decisions are drawn from the current design documents
- [ ] INTERFACE_CONTRACT.md specifications are unaltered
- [ ] GLOSSARY.md definitions are unaltered
- [ ] All companion documents are linked from the README with one-line descriptions
- [ ] prompts/README.md indexes all six prompt files with phase and output noted
- [ ] No details invented that are not present in the source documents
- [ ] Any gaps where source documents are insufficient are flagged explicitly
