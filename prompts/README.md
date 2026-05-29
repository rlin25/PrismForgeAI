# prompts/ — Design Prompts Index

This folder contains the prompts that produced PrismForge AI v4's design artifacts, documentation, and this README. They are published alongside the code because they are part of the work.

## Why this folder exists

A design-first process leaves evidence. The code in `pipeline.py` is the last artifact in this project, not the first. Before any node was written, there was a Socratic design phase, an interface contract, a masterplan with invariants, and a decision ledger with documented rationale for every architectural choice.

The prompts in this folder are the mechanism by which that process was recorded and driven. They show — in executable form — what questions were asked, what phase of the project each prompt belongs to, and what it produced. The design is not post-hoc documentation: it preceded and constrained the code.

Claude was used as a Socratic design partner throughout. The prompts directed Claude to challenge assumptions, surface inconsistencies, and force precision. All architectural judgment — the invariants, the schema choices, the decision to use a flat graph instead of LangGraph sub-graphs, the monolithic `pipeline.py` — belongs to the developer. The prompts are the record of how that judgment was exercised.

## How to read this folder

Each prompt corresponds to a phase of the project. Read them in the order they were run — that order is the story of how PrismForge AI v4 went from a problem statement to a deployed pipeline.

| Step | File | Phase | Produced |
|---|---|---|---|
| 1 | `01_design_methodology.md` | Design (Phases 1–3) | Behavioral instructions governing human-AI collaboration — the rules under which Claude participated in the design process, including how to challenge the developer, when to push back, and how to treat open questions |
| 2 | `02_feedback_loop.md` | Phase 7 | Updated design documents reconciled against the actual implementation — `DESIGN.md` decisions 3.17–3.22 documenting every structural deviation from the spec, and `setup_notes.md` capturing all runtime issues encountered during deployment |
| 3 | `03_rewrite_glossary.md` | Post-implementation | `docs/GLOSSARY.md` — a three-part term reference written for two audiences: nontechnical readers (Part 1) and developers returning to the codebase (Parts 2–3) |
| 4 | `04_generate_walkthrough.md` | Post-implementation | `walkthrough/` directory — architecture walkthrough files explaining why the code is written as it is, not what each line does |
| 5 | `05_generate_diagrams.md` | Post-implementation | Mermaid diagrams added to `walkthrough/README.md` and `README.md` — the file-flow diagram and the high-level architecture diagram |
| 6 | `06_readme_generation.md` | Post-implementation | `README.md` and this file — the public-facing project README and this prompts index |

## The argument

Code is the least durable artifact in a software project. It changes with every refactor, every dependency upgrade, every architectural revision. What persists is the reasoning: why the system is shaped the way it is, what was considered and rejected, what constraints are non-negotiable and why.

This project's `docs/` folder contains that reasoning in full: `DESIGN.md` with 22 documented decisions in Problem / Selected / Rejected / Rationale format, `INTERFACE_CONTRACT.md` with every invariant stated as a binding constraint, and `GLOSSARY.md` that defines what every term means to both a recruiter reading a resume and a developer modifying the codebase.

The `prompts/` folder is the layer above that: it shows how those documents were produced. A project where only the code is visible is a project where only the conclusions are visible. The prompts are the reasoning made legible.
