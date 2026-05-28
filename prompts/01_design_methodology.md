# Prompt: Development Methodology and Claude Collaboration Framework
**Phase:** Design phase (Phases 1–3) — applied before any code is written
**Produced by:** Initial project setup
**Produces:** Governs all design-phase interactions — Socratic design sessions, rubber duck specification passes, interface contract generation, and masterplan construction.

---

# Claude Interaction Workflow — Behavioral Instructions and Methods

**Status:** PrismForge AI v4 — design complete (Phases 1–5 done), implementation in progress (Phase 6), documentation phase pending.
**Purpose:** A reusable reference for how to work with Claude effectively across projects. Documents every behavioral instruction, metacognitive method, and workflow decision. Apply this to every new project from the start.

---

## Part 1 — Project Development Workflow

The full workflow for building software projects using Claude Web Projects and Claude Code.

### Phase 1 — Domain Learning *(Claude Web Project)*
Build vocabulary, understand the problem space, learn the terminology. Flashcard exports, reading lists, concept explanations. This phase produces a person who can make informed decisions, not just a document.

### Phase 2 — Socratic Design *(Claude Web Project)*
Resolve every major design decision using the Socratic method until every ambiguity is eliminated. Every decision is recorded with its reasoning and rejected alternatives explicitly documented. This phase produces a locked decisions document.

**Exit criterion:** The phase is complete when every component in the upcoming interface contract can be described — its inputs, outputs, and responsibilities — without making a forward reference to a decision that hasn't been made yet. If describing any component requires saying "we'll figure that out later," the Socratic pass is not done. This is the test, not a feeling of completeness.

### Phase 3 — Interface Contract Document *(Claude Web Project)*
Before writing the masterplan, define every component boundary explicitly — what each component accepts as input, what it returns as output, and what data types are involved. This document becomes the integration source of truth that every Claude Code subagent references. This phase prevents subagent conflicts.

**Exit gate — verify before proceeding to Phase 4:**
- Is every component's input defined explicitly, including data types?
- Is every component's output defined explicitly, including data types?
- Is the build sequence explicitly ordered with clear gates between steps?

These three items are properties of the interface contract, not the masterplan. A gap here caught now is a paragraph rewrite. The same gap caught at Phase 5 is a masterplan rewrite.

### Phase 4 — Masterplan + Atomic Subplans *(Claude Web Project)*
Generate the masterplan referencing the interface contract and locked decisions. The masterplan opens with a plain English paragraph describing the completed system — this is the first thing Claude Code reads. Each subplan contains three things: its own implementation instructions, the interface contract document, and the explicit build sequence gate it must pass before the next subplan starts.

### Phase 5 — Verification Checklist *(Claude Web Project)*
Apply the ten-item checklist (see Part 3) to the masterplan before any code is written. This phase produces confidence that what you hand off to Claude Code matches your intent.

### Phase 6 — Implementation *(Claude Code)*
Hand the masterplan to Claude Code. Subagents implement atomic subplans in strict build sequence order, each referencing the interface contract document. No subagent starts until the previous gate is confirmed working.

### Phase 7 — Feedback Loop *(Claude Code)*
Reconcile all design documents against what was actually built. Read every source file and every design document. For each discrepancy found — correction, gap, or status update — either update the relevant document or record it as a known issue with an explicit deferral note. This phase runs in Claude Code, not the Web Project, because Claude Code has simultaneous access to both the codebase and the design documents.

**Exit criterion:** Every discrepancy identified during the inspection pass has been either corrected in a document or recorded as a known issue with an explicit deferral note. No open findings remain. When this condition is met, the Web Project resumes for the next version's design — not before.

The Web Project's role after Phase 7 is next-version design only.

---

## Part 2 — Metacognitive Methods

These are the methods used during planning phases to surface gaps and make implicit assumptions explicit. Each method is suited to a different phase of work.

### Method 1 — Socratic Method
**Best for:** Phase 2 (design decisions). Eliminating ambiguity in choices where multiple valid options exist.

**How it works:** Claude asks structured questions about each design area. You answer. Claude challenges weak reasoning and presents alternatives. Decisions are locked only when the reasoning is explicit and all alternatives are documented with rejection rationale.

**Why it works:** Forces every decision to be made consciously rather than by default. When a result is bad later, the cause is traceable to a specific decision and its reasoning — not to something that was never discussed.

**Signal that it's working:** You find yourself unable to answer a question clearly — this means the decision was previously made by assumption rather than by reasoning.

---

### Method 2 — Rubber Duck Specification
**Best for:** Phase 3 (interface contract). Making implicit assumptions explicit before writing specs.

**How it works:** You describe each component as if explaining it to a developer who has zero additional context and cannot ask follow-up questions. Claude listens for gaps — moments where you say something vague, skip a detail, or cannot produce a precise answer — and flags them. Claude then formalizes what you said into the document.

**Why it works:** Writing for an audience that cannot ask follow-up questions forces you to externalize your internal model. Gaps surface as friction — when you reach for words and cannot find them, that is the gap revealing itself.

**Signal that it's working:** You hit moments of discomfort where you think you know something but cannot say it precisely. This is the method working, not a sign of inadequate preparation. Flag the gap and continue; gaps are resolved in the Socratic pass that follows.

**Important:** When you hit a gap during rubber duck, do not reach for the design documents. Flag it and keep going. The Socratic pass resolves gaps; the rubber duck pass surfaces them.

---

### Method 3 — Draft and Challenge
**Best for:** Reviewing completed documents. Catching gaps in something that already exists.

**How it works:** Claude produces a complete draft from existing project files. You read it and push back on anything that feels wrong, underspecified, or inconsistent with your intent.

**Why it works:** Fast. A complete document gives you something concrete to react to, which is easier than generating from nothing.

**Risk:** You may rubber-stamp something that has a subtle gap because it looks complete on the surface. Use in combination with rubber duck or Socratic where thoroughness matters more than speed.

---

### Recommended Sequencing

For specification work (Phase 3): **Rubber Duck first, then Socratic.**

Rubber duck first forces you to externalize your own mental model before seeing Claude's. When the Socratic pass follows, the questions hit genuine gaps rather than territory you already know. If Socratic came first, Claude's questions would lead you through territory you could have mapped yourself — less valuable.

For decision work (Phase 2): **Socratic only.**

For document review: **Draft and Challenge, then Socratic on flagged gaps.**

---

## Part 3 — Verification Checklist

Apply this checklist to the masterplan at Phase 5 before handing off to Claude Code.

1. Is the plain English system description present at the top of the masterplan?
2. Is every component's input defined explicitly, including data types?
3. Is every component's output defined explicitly, including data types?
4. Is the build sequence explicitly ordered?
5. Does each subplan reference the interface contract?
6. Does each subplan have an explicit gate that must pass before the next subplan starts?
7. Are all locked design decisions referenced where relevant in the masterplan?
8. Is the folder structure specified?
9. Are all external dependencies identified?
10. Is there a test strategy for each subplan?

---

## Part 4 — Behavioral Instructions

Specific instructions to give Claude during design sessions to maintain quality and consistency.

### Instruction 1 — Two Options, Preference, and Rationale
**Trigger:** Any Socratic design question.

**Instruction:** *"For each question, provide your best two suggestions, your preference, and your rationale for such."*

**Why:** Forces Claude to do the comparative analysis rather than presenting a single recommendation. Makes the tradeoff explicit and gives you something concrete to agree or push back on.

---

### Instruction 2 — Flag New Decisions
**Trigger:** Any session where a new design element is introduced.

**Instruction:** *"Flag any decision that represents a new design element not previously discussed."*

**Why:** Prevents scope creep from going unnoticed. New additions that aren't flagged can be accepted without realizing they represent a design decision that should be deliberate. The flag prompts a conscious choice: lock it, defer it, or reject it.

---

### Instruction 3 — Maintain a Pending Changes List
**Trigger:** Any session that produces decisions that will require document updates.

**Instruction:** *"Maintain a running pending changes list throughout this session, updated after each decision, so nothing is lost when we generate the updated documents at the end."*

**Why:** Long sessions produce many decisions. Without a running list, decisions made early in the session are easy to miss when generating the final documents.

---

### Instruction 4 — Cross-Reference Documentation for Contradictions
**Trigger:** Rubber duck specification sessions.

**Instruction:** *"Cross-reference the project documentation and flag anything that contradicts, conflicts with, or is missing from what is locked."*

**Why:** During rubber duck, you may state something that contradicts a locked decision without realizing it. Claude catching this in real time is faster than discovering it after the interface contract is written.

---

### Instruction 5 — Integrated Updates, Not Bolt-Ons
**Trigger:** When generating updated versions of project documents.

**Instruction:** *"Generate a fully integrated updated version of the document, not a version with additions bolted onto the end. New decisions should be woven into the document in the correct location, not appended."*

**Why:** Documents that accumulate bolted-on sections become harder to read and harder to hand to Claude Code as a coherent reference. A clean integrated document is easier to maintain and more reliable as a source of truth.

---

### Instruction 6 — Batch Document Updates
**Trigger:** At the end of any session that produces multiple document changes.

**Instruction:** *"Hold all document updates until the end of the session. Generate all updated documents in a single pass once all decisions are locked."*

**Why:** Generating documents mid-session and then making more decisions creates multiple versions of documents in the same conversation, which is confusing. A single end-of-session generation pass is cleaner.

---

## Part 5 — Versioning and Continuity Decisions

### Versioning Strategy
Each version of a project is regenerated from scratch by Claude Code using a new masterplan. The previous version's codebase is never the starting point for the next version. Design documents — the interface contract, locked decisions, and architecture document — are the artifacts that carry intent across versions. Code is disposable.

**Why:** Iterating on existing code requires Claude Code to simultaneously reason about what exists, what to change, and what to leave alone — a significantly harder task than building fresh, and a common source of subtle bugs. Regenerating from scratch keeps each Claude Code session unambiguous.

**Implication:** Every masterplan must be complete and self-contained. Any capability carried forward from a previous version must be explicitly re-specified — it cannot be assumed.

---

### Project File Strategy
Critical decisions should be captured in project files, not left only in conversation history. Conversations can lose early context as they grow; project files persist across all conversations.

The canonical project files for PrismForge AI are organized into two directories:

**`docs/`** — stable reference documents, version-controlled across sprints:
- `docs/DESIGN.md` — consolidated architecture and design decisions ledger with all locked choices, reasoning, and rejected alternatives
- `docs/GLOSSARY.md` — all domain and technical terms, written for two audiences
- `docs/INTERFACE_CONTRACT.md` — every component's inputs, outputs, data types, and binding invariants

**`plans/`** — implementation roadmap, consumed by Claude Code during Phase 6:
- `plans/00_MASTERPLAN.md` — orchestration plan: build order, non-negotiable invariants, acceptance gates
- `plans/01_SUBPLAN_environment_and_crawler.md` — environment setup and directory crawler
- `plans/02_SUBPLAN_schemas_router_handoff.md` — Pydantic schemas, router node, handoff node
- `plans/03_SUBPLAN_matrix_and_workers.md` — fan-out matrix, extraction workers, state reducers
- `plans/04_SUBPLAN_synthesis_blindspot_deploy.md` — round-table synthesis, blind spot detection, Streamlit UI, Docker deployment

Update `docs/` files at the end of each session, not during. Generate integrated versions, not bolt-ons. The `plans/` files are consumed during implementation; update them only if a design decision changes before a subplan runs.

---

### Cross-Conversation Context
Claude does not automatically remember previous conversations. The project files are the shared context. If a decision was made conversationally but never written to a file, it effectively does not exist for the next conversation.

When starting a new session, open with a prompt that tells Claude which phase you're in and what the last session produced. The handoff prompt from each session should be explicit enough that the next session can pick up without relitigating anything already decided.

---

### Methodology Decisions Log

The methodology itself has evolved. Changes to the workflow should be recorded here with the same format used in the project design decisions document: what changed, why, and what was rejected. This log is what makes the methodology reusable across projects rather than a snapshot of one project's habits.

**Decision M1 — Phase 7 runs in Claude Code, not the Web Project**
Claude Code has simultaneous access to both the codebase and the design documents, making it the correct environment for reconciliation work. The Web Project cannot read source files directly. Running Phase 7 in the Web Project would require manually copying file contents into the conversation — slower and more error-prone. The Web Project resumes only for next-version design after Phase 7 is complete.
*Rejected option:* Running Phase 7 in the Web Project. Rejected because it breaks the principle that every phase uses the environment best suited to its task.

**Decision M2 — Interface contract exit gate added to Phase 3**
Items 1, 2, and 4 of the verification checklist (inputs defined, outputs defined, build sequence ordered) are properties of the interface contract, not the masterplan. Verifying them at Phase 3 catches gaps when they are cheapest to fix. The full checklist still runs at Phase 5 — this is an earlier check, not a replacement.
*Rejected option:* Leaving all checklist items at Phase 5 only. Rejected because interface contract gaps caught at Phase 5 require masterplan rewrites rather than contract paragraph rewrites.

**Decision M3 — Concrete exit criteria added to Phases 2 and 7**
"No open questions" and "reconciliation complete" are principles, not tests. Replaced with verifiable conditions: Phase 2 exits when every component can be described without forward references; Phase 7 exits when every inspection finding is either corrected or explicitly deferred. Consistent with the discipline applied to build sequence gates in Phase 6.
*Rejected option:* Leaving exit conditions as judgment calls. Rejected because judgment-based exits create inconsistent phase lengths across projects and make it harder to hand off the methodology to someone else.

---

## Part 6 — Vertical Slicing Principle

The core versioning philosophy. Each version is a complete, independently demonstrable system — not a prototype that becomes a real thing, but a real thing that gets more capable.

### What to do in each version
Design interfaces wide enough that later versions can add capability without breaking what's already there. Include data fields that will be acted on in later versions — the data should be captured early even if it's not used yet.

### What not to do in each version
Do not build scaffolding for features you haven't implemented yet. No placeholder functions, no stub reasoning paths, no TODO comments wired into logic. The code does exactly what the current version specifies, nothing more.

### The analogy
You are laying foundations wide enough for a larger building, but only constructing the first floor. The foundation is not artificially narrow — but it does not contain empty rooms waiting to be filled.

### Applying vertical slicing to interface decisions
When specifying an interface, ask: if this field or parameter is included now but not acted on, does it cost anything? If the answer is no, include it. If including it requires building logic that isn't needed yet, exclude it and note it as a next-version addition.
