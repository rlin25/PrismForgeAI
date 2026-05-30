# app.py — Walkthrough

`app.py` is the Streamlit frontend. Its sole responsibility is to bridge the async LangGraph
pipeline in `pipeline.py` to Streamlit's synchronous rendering model and to present the
generated report to the user.

---

## 1. Purpose

`app.py` exists because the pipeline produces a Markdown string that must be displayed in a
browser. It handles:

1. Patching the running event loop so async pipeline calls work inside Streamlit.
2. Collecting user input (data room directory path).
3. Validating environment variables before the pipeline runs.
4. Calling `run_graph` and storing the result in Streamlit session state.
5. Rendering the report via `st.markdown` and providing a download button.

`app.py` contains no pipeline logic. It imports only `run_graph` from `pipeline.py`. If
`pipeline.py` is replaced entirely, only the import line in `app.py` needs to change.

---

## 2. Relationships

- **Imports from:** `pipeline` (only `run_graph`); standard library (`asyncio`,
  `concurrent.futures`, `os`, `pathlib`); `streamlit`.
- **Imported by:** nothing. It is the Streamlit entry point — invoked by
  `streamlit run app.py`.
- **Deliberately does not touch:** LangGraph, Pydantic, LLM clients, file I/O beyond path
  validation, or any pipeline internals.

---

## 3. The ThreadPoolExecutor Async Bridge (Invariant I2, Decision 3.23)

```python
def _run_pipeline(directory_path: str) -> str:
    """Run the async pipeline in a fresh event loop on a dedicated thread."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(run_graph(directory_path))
    finally:
        loop.close()

# In the button handler:
with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
    report = ex.submit(_run_pipeline, data_room_path).result(timeout=600)
```

The dedicated thread owns a completely isolated event loop. LangGraph's task scheduler,
the httpx clients inside LangChain's LLM wrappers, and all async futures are created and
resolved within the same loop — no cross-loop future references are possible.

**Why not `nest_asyncio` (the original prescription)?**

The original spec (Decision 3.11) prescribed `nest_asyncio.apply()` at module load
followed by `asyncio.get_event_loop().run_until_complete(run_graph(...))`. This was
the correct approach when the pipeline used a flat `process_document` node with
`asyncio.gather` for workers. After the rewrite to spec-compliant LangGraph sub-graphs
with `Send`-dispatched workers, this produced:

```
RuntimeError: Task got Future <Future pending> attached to a different loop
```

`nest_asyncio` patches the running loop to allow nested `run_until_complete` calls,
but it does not prevent LangGraph from creating tasks that reference different loop
instances when running dozens of parallel extraction workers via Send dispatch. The
`ThreadPoolExecutor` bridge provides full loop isolation without patching (Decision 3.23).

`nest_asyncio` remains in `requirements.txt` as a declared dependency but
`nest_asyncio.apply()` is no longer called at module load.

---

## 4. Why Streamlit (Decision 3.11)

Streamlit was chosen over a FastAPI + JavaScript + SSE stack because it eliminates the
frontend layer entirely. All code remains in Python. The alternative would introduce
JavaScript context switching, CORS configuration, SSE chunk-encoding debugging, and CSS layout
overhead at the worst possible time in a sprint. The async bridge (whether `nest_asyncio`
or `ThreadPoolExecutor`) is a small amount of boilerplate. The SSE approach is a non-trivial
debugging surface.

---

## 5. Layout Rationale

The UI uses a narrow config column on the left (`st.columns([1, 2])`, left third only) and
renders the report below the full-width pipeline status block, appearing only after generation
completes. The two-column split is declared at page level so the config panel keeps its
narrow footprint, but the right column is left intentionally empty — the report is rendered
as a full-width section below the `st.status` block after the run completes.

This differs from the earlier two-column design (documented in v4 initial commit) where the
report appeared in the right column alongside the config panel. The new layout was chosen
because the animated stage diagram and topology widget require the full page width to be
legible — compressing them into a right column at weight-2 would truncate the diagram and
overflow the topology chips horizontally.

The report section only renders after `st.session_state["report"]` is populated. There is no
placeholder or info message in the right column before the first run — an empty right column
is simpler than a placeholder, and placeholders tend to mislead users about the expected
output location.

---

## 5a. Animated Pipeline Stage Diagram

The `_diagram_html` function produces a single-line HTML string rendered via
`st.empty().markdown(..., unsafe_allow_html=True)`. The 6 stages are:

```
CRAWL → ROUTE → CHUNK → EXTRACT → SYNTHESIZE → REPORT
```

**Why inline HTML/CSS instead of `st.graphviz_chart` or `st.pyplot`:**

- `st.graphviz_chart` produces a static SVG that cannot animate and requires Graphviz to be
  installed in the container. More importantly, it cannot be updated in-place during a live
  run — each update would re-render the full chart, producing visible flash.
- `st.pyplot` requires a Matplotlib figure, which has no first-class concept of animated
  state chips. Keeping a figure in memory across 50+ progress events and calling
  `plt.draw()` repeatedly is brittle and produces Streamlit thread-safety warnings.
- `st.empty()` with inline HTML gives exact control over color, animation, and chip sizing.
  The placeholder can be updated in-place (`diagram_ph.markdown(...)`) with no flash because
  Streamlit diffs the HTML content before writing.

**Stage granularity:** The 6 stages map exactly to the 6 LangGraph pipeline phases that emit
distinct log messages: `[directory_crawler]` → CRAWL complete, `[router_node]` → ROUTE
active, `[chunk_node]` → CHUNK active, `[route_matrix_to_workers]` → EXTRACT active,
`[master_round_table_node] Synthesizing` → SYNTHESIZE active, `[master_round_table_node]
Report` → SYNTHESIZE complete / REPORT active. Each stage corresponds to a unique log prefix,
so `_update_stages` can detect transitions without ambiguity.

**CSS pulse animation:** The `active` stage uses
`animation:pulse 1.5s ease-in-out infinite` defined in the embedded `<style>` block.
A stage that is visually indistinguishable from idle when active would give no feedback
during the longest phase (EXTRACT can run for several minutes while 50 workers are
in-flight). The pulse communicates "the pipeline is running and this stage is live" without
requiring a separate spinner widget. For demo credibility, a static diagram that never
changes until the report appears is harder to read than one where the currently-executing
stage is visually distinct.

**EXTRACT detail line:** While EXTRACT is active, the diagram chip shows a live
`N/total workers` counter updated from the worker event parser. This uses the same
`diagram_ph.markdown(...)` update path; no separate DOM element is needed.

---

## 5b. Dynamic Lens Selection Topology Widget

The `_topology_html` function produces a block of colored chips, one chip per lens per
document, rendered via `topology_ph.markdown(..., unsafe_allow_html=True)`. The widget
appears below the stage diagram and is populated incrementally as `[router_node]` log
messages arrive during the ROUTE stage.

**Why colored chips (not a table or text list):**

The Dynamic Semantic Topology (DST) feature — that the router selects a per-document lens
set rather than applying a fixed set to every document — is the central architectural claim
of PrismForge AI. Without a visual representation, a demo viewer has no direct evidence that
routing happened or that different documents received different lens assignments. A colored
chip grid makes the per-document assignment visible without requiring any explanation: the
viewer sees that `hp_product_purchase_agreement.txt` received `IP_Ownership`, `IP_Warranty`,
and `Liability_Cap` while `dot_hill_10k_2006.txt` received `Change_of_Control` and
`Regulatory_Approval`, and the asymmetry is immediately obvious.

A plain text list (`st.text`) or a table (`st.dataframe`) could convey the same information
but would require the viewer to read and parse rows. Chips are scannable in under two seconds.

**`_LENS_COLORS` mapping rationale:**

```python
_LENS_COLORS = {
    "IP_Ownership":       ("#dbeafe", "#1d4ed8"),   # blue  — IP cluster
    "IP_Warranty":        ("#dbeafe", "#1d4ed8"),   # blue  — IP cluster
    "License_Compliance": ("#dcfce7", "#166534"),   # green — compliance cluster
    "Liability_Cap":      ("#fef3c7", "#92400e"),   # amber — financial risk cluster
    "Indemnification":    ("#f3e8ff", "#6b21a8"),   # purple — indemnification cluster
    "Change_of_Control":  ("#ffe4e6", "#9f1239"),   # red   — high-stakes events
    "Data_Privacy":       ("#e0f2fe", "#0369a1"),   # sky   — regulatory cluster
    "Regulatory_Approval":("#f0fdf4", "#15803d"),   # light green — regulatory cluster
}
```

Lenses within the same risk domain share a hue family (IP lenses are both blue; regulatory
lenses are both green). This means a document heavy in IP lenses appears predominantly blue,
giving an immediate visual fingerprint of the document's risk profile. Lenses not in the dict
fall back to `_DEFAULT_LENS_COLOR` (gray) so unknown or future lenses do not crash the
renderer.

The colors are drawn from the Tailwind CSS palette used by the stage diagram, ensuring
visual consistency without a CSS framework dependency.

---

## 5c. Document Preview

The config panel includes collapsible `st.expander` blocks, one per `.txt` file found in
the data room directory. Each expander shows the first 1,500 characters of the file, followed
by a character count caption.

**Why 1,500 character truncation:**

1,500 characters is approximately the first two to four paragraphs of an EDGAR filing or
legal agreement — enough to identify the document type (e.g., "EXHIBIT 10.1 — PRODUCT
PURCHASE AGREEMENT between HP and Dot Hill") and the parties involved, without displaying
so much text that the config panel becomes a scrollable document viewer. The truncation
marker `[... truncated ...]` is appended only when the file is longer than 1,500 characters,
so short documents display in full.

**Why `st.expander` (not `st.text` inline):**

The config panel must remain compact by default so the run button and key warnings are
visible above the fold. An expander collapses to a single title line by default, preserving
vertical space. The user can expand any document they want to inspect before running. Inline
`st.text` blocks for multiple large files would push the run button off screen, which would
be especially problematic on smaller displays during a demo.

---

## 5d. Worker Counter (Mutable Dict Pattern)

During the EXTRACT stage, the progress log shows a single updating line:

```
    Workers: 23/50 complete  |  2 retrying...
```

This line is not appended on each event — it is mutated in-place by tracking its index in
the `lines` list. The state is held in a mutable dict `w`:

```python
w = {"total": 0, "done": 0, "failed": 0, "retrying": 0, "line_idx": None}
```

**Why a mutable dict instead of nonlocal variables:**

`process_msg` is a nested function defined inside the `if run_button:` block. In Python,
`nonlocal` requires the variable to be explicitly declared in an enclosing function scope.
The `if run_button:` block is a conditional block, not a function scope, so `nonlocal` cannot
be used to rebind integers (`done += 1` inside `process_msg` would require `nonlocal done`
which is unavailable here). Assigning mutable state to a dict (`w["done"] += 1`) bypasses
this restriction — dict mutation does not require `nonlocal` because the binding (`w`) is not
being rebound, only a value inside it is being modified.

**How the line update works:**

When the first `dispatch` event arrives (from a `[route_matrix_to_workers]` log message),
`worker_summary()` is called and the result is appended to `lines`. The index of that
appended line is stored as `w["line_idx"]`. On every subsequent `ok`, `retry`, or `failed`
event, `lines[w["line_idx"]]` is overwritten with the new `worker_summary()` string. When
`log_ph.code("\n".join(lines), ...)` re-renders, the worker line updates in place rather than
growing a new line per event.

**Retrying counter:** When a `Rate limited — retrying` log message arrives, `w["retrying"]`
is incremented. When a `FAILED` message arrives (which follows a final failed retry), the
retrying counter is decremented by one (`max(0, ...)` guards against underflow from event
ordering). This gives a live "N retrying..." count that reflects in-progress backoff workers,
not permanently failed ones.

---

## 6. Environment Variable Pre-Check

Before the run button becomes active, `app.py` checks for `ANTHROPIC_API_KEY` and
`GOOGLE_API_KEY` via `os.environ.get`. If either is missing, a warning is displayed and the
button is disabled (`disabled=bool(missing_keys)`).

This check exists to surface the most common failure mode before the pipeline runs, rather
than after a multi-minute wait. Without it, the pipeline would start, the LangGraph graph
would initialize, and the first LLM call would raise an authentication error after the user
has already waited for the crawler to complete. The warning makes the requirement visible in
the UI rather than in server logs.

The check is advisory, not a security enforcement mechanism. It reads from the process
environment, which is set at container start time via `-e` flags (Decision 3.13). See
`dockerfile.md` for how keys are injected.

---

## 7. Session State for the Report

The report is stored in `st.session_state["report"]` after a successful pipeline run. This
is why the report persists when the user changes the text input or scrolls the page —
Streamlit re-runs the script on every interaction, and without session state the report would
be lost on the next re-render. The session state also holds `report_path` so the caption
below the report shows which directory was analyzed.

The report is written to session state only on success. If `run_graph` raises an exception,
`st.error` displays the error and the previous report (if any) remains visible. `raise` is
called after `st.error` so the full stack trace appears in the server logs for debugging.

---

## 8. Download Button

```python
st.download_button(
    label="Download Report (.md)",
    data=st.session_state["report"],
    file_name="prismforge_risk_report.md",
    mime="text/markdown",
)
```

The download button serves the report as a `.md` file. It is rendered only when a report
exists in session state — there is no download button before the first successful run. The
MIME type `text/markdown` is set so that browsers recognize the file format, though `.md`
files are plain text and the MIME type has no functional effect on the download itself.

---

## 9. What `app.py` Does NOT Do

- Does not implement any pipeline logic. No LangGraph, Pydantic, or LLM code here.
- Does not handle chunking, routing, extraction, or synthesis.
- Does not write output files to disk (the download is served from memory).
- Does not manage concurrency. `max_concurrency=50` is set inside `run_graph`.
- Does not validate document content — only that the path exists and is a directory.
- Does not stream the report token by token. The report is collected in full inside
  `run_graph` before `st.markdown` is called.

---

## 10. v5 Touch Points

The following items were listed as v5 work in the initial walkthrough. Progress feedback
(animated diagram, topology widget, worker counter, document preview) was implemented in the
v4 UI rebuild and is no longer a v5 item.

- **Streaming render:** The current design collects the full report before rendering.
  v5 would call `graph.astream(...)` inside `run_graph` and yield tokens back to `app.py`.
  `app.py` would use `st.empty()` with incremental `markdown()` updates to show the report
  as it is generated. This requires `run_graph` to become an async generator and `app.py`
  to drive the stream via `run_until_complete` on a collecting coroutine. (Still v5 — report
  streaming is separate from pipeline-stage progress streaming.)
- **Multi-run history:** Session state currently stores only the most recent report. A list
  of past runs with their paths and timestamps would let the user compare reports without
  re-running the pipeline.
- **Configurable parameters:** `max_concurrency`, `compress_inbox` limit, and model names are
  hardcoded in `pipeline.py`. Exposing them as `st.sidebar` controls would let users tune the
  pipeline without editing source code.
