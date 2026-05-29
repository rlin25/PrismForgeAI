# Prompt: Generate Architecture Diagrams
**Phase:** Post-implementation documentation
**When to use:** After the feedback loop is complete and all design documents are reconciled.
**Run order:** Step 5 of 6 — see `prompts/BATCH.md` for the full sequence.
**Produces:** A Mermaid architecture diagram for the README and a Mermaid file flow diagram for the walkthrough directory.

---

## Before Running This Prompt

The source file list must be updated once implementation is complete. All other values are pre-filled for PrismForge AI v4.

| Item | Value |
|---|---|
| Project name | PrismForge AI |
| Current version | v4 |
| Source files | **Fill in after implementation — in logical execution order** |

---

## Inputs

Read the following documents in full before generating either diagram:

- `docs/INTERFACE_CONTRACT.md` — authoritative source for component inputs, outputs, and data flow
- `docs/DESIGN.md` — authoritative source for why components are structured the way they are
- `plans/00_MASTERPLAN.md` — authoritative source for component responsibilities and build sequence

Do not invent relationships not present in the source documents. If a relationship is ambiguous, flag it explicitly rather than guessing.

---

## Diagram 1 — Architecture Diagram (for README.md)

### Purpose
A high-level system diagram showing the major components of PrismForge AI, their relationships, and the direction of data flow. This diagram appears in the README and is the first technical artifact a recruiter or hiring manager sees. It must be readable by both technical and nontechnical audiences.

### Required components to show
All of the following must appear as nodes. Do not add nodes that are not in this list unless the implementation introduced a component not planned in the interface contract (flag if so):

- User / data room directory (entry point)
- Directory Crawler
- Router Node (label: "Router — Gemini Flash")
- Chunker + Anchoring
- Matrix Fan-Out (`Chunks × Lenses`)
- Extraction Worker Pool (label: "Extraction Workers — Claude Sonnet")
- Handoff Node
- `ParentState` inbox (accumulation point)
- Master Round-Table Node (label: "Round-Table — Claude Sonnet")
- `detect_blind_spots()` (show as a step inside or adjacent to the Round-Table node)
- `compress_inbox()` guard (show as a step inside or adjacent to the Round-Table node)
- Final Risk Report (output)
- Streamlit UI (output layer)

### Edge labels
Label each edge with what is being passed. Minimum required labels:
- User → Directory Crawler: "data room path"
- Directory Crawler → Sub-graph: "source_material per file"
- Router → DocumentSubState: "semantic_summary + dynamic_topology"
- Matrix Fan-Out → Worker Pool: "WorkerPayload (chunk + lens + summary)"
- Worker Pool → Handoff: "local_inbox (ExtractionRecords)"
- Handoff → ParentState: "summary_store + global_inbox"
- Round-Table → Final Report: "Markdown risk report"

### Grouping
Use Mermaid subgraphs to group:
- **"Per-Document Sub-Graph (runs in parallel per file)"** — Router, Chunker, Matrix Fan-Out, Worker Pool, Handoff
- **"Synthesis Layer"** — Master Round-Table, blind spot detection, compress guard
- **"Output Layer"** — Final Report, Streamlit UI

### Requirements
- Use Mermaid `flowchart TD` syntax
- Do not show internal implementation details — nodes represent components, not functions or classes
- Keep the diagram shallow enough that a nontechnical reader can trace the flow from input to output in one read

### Output
Embed the diagram directly in `README.md` using a fenced Mermaid code block. Place it after the "What PrismForge AI does" section and before the "Why the design matters" section.

---

## Diagram 2 — File Flow Diagram (for walkthrough/README.md)

### Purpose
A diagram showing the order in which source files are described in the walkthrough directory and how they relate to each other in terms of dependency and execution flow. Orients a developer reading the walkthrough for the first time.

### Requirements
- Use Mermaid `flowchart TD` syntax
- Show every source file covered by the walkthrough as a node
- Use the actual filename as the node label
- Show dependency relationships as directed edges (A → B means A is imported by B, or A feeds into B in execution order)
- Show execution order where dependency alone does not determine sequence
- Do not show external libraries as nodes — only project source files
- The diagram must match the order in which walkthrough files are listed in `walkthrough/README.md`

Source files to show as nodes:
`{SOURCE_FILES}`

### Output
Embed the diagram at the top of `walkthrough/README.md` using a fenced Mermaid code block, before the file index. Follow it immediately with: *"Arrows show import dependencies and execution order. Each node links to its walkthrough file."*

---

## Styling

Color-code nodes by component type using `classDef`. Apply classes inline with `:::className`. Every diagram must use this pattern — unstyled diagrams are not acceptable.

**Color palette for PrismForge AI:**

| Component type | fill | stroke | color | font-weight | When to apply |
|---|---|---|---|---|---|
| Claude Sonnet API call | `#FEF3C7` | `#D97706` | `#92400E` | bold | Extraction workers, Round-Table Node |
| Gemini Flash API call | `#FEF3C7` | `#D97706` | `#92400E` | bold | Router Node (same amber — both are LLM calls) |
| LangGraph state / accumulation | `#FDF4FF` | `#A855F7` | `#6B21A8` | — | ParentState inbox, DocumentSubState |
| User input / entry point | `#DBEAFE` | `#2563EB` | `#1E3A8A` | bold | Data room directory, Streamlit UI |
| Output / report | `#D1FAE5` | `#059669` | `#065F46` | bold | Final Risk Report |
| Processing node (no LLM) | `#DBEAFE` | `#2563EB` | `#1E3A8A` | bold | Directory Crawler, Chunker, Matrix Fan-Out, Handoff |
| Safety / guard | `#EDE9FE` | `#7C3AED` | `#4C1D95` | — | detect_blind_spots(), compress_inbox() |

Add a one-line caption below each diagram (outside the code block) naming the color meanings in italic:
*Amber = LLM API call (Claude Sonnet / Gemini Flash) · Purple = LangGraph state · Blue = processing node or user entry · Green = output · Lavender = safety guard*

**Node shape conventions:**
- User entry / data room: `([Text])` rounded stadium
- LangGraph state accumulation: `[(Text)]` cylindrical
- Safety guard / decision: `{Text}` rhombus
- All other nodes: `[Text]` rectangle

**classDef syntax example:**
```
classDef llm fill:#FEF3C7,stroke:#D97706,color:#92400E,font-weight:bold
classDef state fill:#FDF4FF,stroke:#A855F7,color:#6B21A8
classDef entry fill:#DBEAFE,stroke:#2563EB,color:#1E3A8A,font-weight:bold
classDef output fill:#D1FAE5,stroke:#059669,color:#065F46,font-weight:bold
classDef guard fill:#EDE9FE,stroke:#7C3AED,color:#4C1D95
```

Apply with `:::llm`, `:::state`, `:::entry`, `:::output`, `:::guard` inline on node definitions.

---

## Constraints

- Both diagrams must render correctly in standard Mermaid renderers (GitHub, VS Code Mermaid preview)
- Do not use Mermaid features that are not widely supported — avoid subgraph nesting beyond two levels, avoid custom themes, avoid HTML labels
- Node labels must be concise — three to five words maximum per node
- Edge labels must be concise — two to four words maximum per edge
- If a component relationship is too complex to represent cleanly in one diagram, split it into two diagrams rather than producing one unreadable diagram
- Every node in Diagram 1 must correspond to a component described in the interface contract
- Every node in Diagram 2 must correspond to a source file in `{SOURCE_FILES}`
- Do not produce unstyled diagrams — every node must have a `classDef` applied

---

## Notes

- The architecture diagram is the first technical artifact most readers will see — prioritize clarity over completeness
- The sub-graph sandbox is the most important structural concept to convey: parallel execution per document, private state, single handoff
- The file flow diagram is for developers, not recruiters — prioritize accuracy over simplicity
- The walkthrough directory must exist before running this prompt (step 4 in `prompts/BATCH.md`)
- Design documents must be reconciled before running this prompt (step 2 in `prompts/BATCH.md`)
