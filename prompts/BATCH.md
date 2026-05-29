# Batch Run Order — PrismForge AI v4 Prompts

Run these prompts in sequence after all four subplans are implemented and all acceptance gates pass. Each step depends on the output of the step before it.

| Step | File | Purpose |
|---|---|---|
| 1 | `01_design_methodology.md` | Read first — methodology reference that informs how all subsequent prompts should be executed |
| 2 | `05_feedback_loop.md` | Reconcile all design documents against the implemented codebase. All later steps depend on the reconciled docs this produces. |
| 3 | `04_rewrite_glossary.md` | Rewrite the glossary against the actual implementation. Depends on reconciled docs from step 2. |
| 4 | `03_generate_walkthrough.md` | Generate the `walkthrough/` directory. Depends on reconciled docs from step 2. |
| 5 | `06_generate_diagrams.md` | Generate Mermaid diagrams for README and walkthrough. Depends on reconciled docs (step 2) and walkthrough directory (step 4). |
| 6 | `02_readme_generation.md` | Generate README and all documentation artifacts. Depends on reconciled docs (step 2), walkthrough (step 4), and diagrams (step 5). |

## Prerequisites before running

- All four subplans implemented and acceptance gates confirmed:
  - `plans/01_SUBPLAN_environment_and_crawler.md` gate passed
  - `plans/02_SUBPLAN_schemas_router_handoff.md` gate passed
  - `plans/03_SUBPLAN_matrix_and_workers.md` gate passed
  - `plans/04_SUBPLAN_synthesis_blindspot_deploy.md` gate passed
- `{SOURCE_FILES}` placeholder filled in prompts 03, 04, 05, and 06 with the actual implemented source file list
- `{TEST_FILES}` placeholder filled in prompt 05
- `{FIRST_NEW_DECISION_NUMBER}` filled in prompt 05 (count locked decisions in `docs/DESIGN.md` and add 1)
