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

- **Imports from:** `pipeline` (only `run_graph`); standard library (`asyncio`, `os`,
  `pathlib`); `nest_asyncio`; `streamlit`.
- **Imported by:** nothing. It is the Streamlit entry point — invoked by
  `streamlit run app.py`.
- **Deliberately does not touch:** LangGraph, Pydantic, LLM clients, file I/O beyond path
  validation, or any pipeline internals.

---

## 3. The `nest_asyncio` Bridge (Invariant I2, Decision 3.11)

```python
import nest_asyncio
nest_asyncio.apply()
```

These two lines appear at module load, before the Streamlit import. The ordering matters.
Streamlit creates an internal event loop when it initializes. `nest_asyncio.apply()` patches
the already-running loop to allow nested coroutine scheduling.

If `asyncio.run(run_graph(...))` were called instead, it would raise:

```
RuntimeError: This event loop is already running
```

The correct call is therefore:

```python
asyncio.get_event_loop().run_until_complete(run_graph(data_room_path))
```

`nest_asyncio.apply()` must happen before any async call — which means before any Streamlit
widget code runs. Module-level execution guarantees this ordering.

This is not a workaround for a bug; it is the documented pattern for calling async code from
within an already-running event loop (Decision 3.11). `nest_asyncio` is listed in
`requirements.txt` for this reason.

---

## 4. Why Streamlit (Decision 3.11)

Streamlit was chosen over a FastAPI + JavaScript + SSE stack because it eliminates the
frontend layer entirely. All code remains in Python. The alternative would introduce
JavaScript context switching, CORS configuration, SSE chunk-encoding debugging, and CSS layout
overhead at the worst possible time in a sprint. The `nest_asyncio` bridge is two lines of
code. The SSE approach is a non-trivial debugging surface.

---

## 5. Layout Rationale

The UI uses a two-column layout (`st.columns([1, 2])`):

- The left column (weight 1) holds configuration inputs and the run button. It is narrower
  because the configuration surface is small — one text input, one button, one environment
  variable warning.
- The right column (weight 2) holds the report. It is wider because Markdown reports with
  tables, headers, and lists benefit from horizontal space.

This layout choice is not architecturally significant, but it means the report is always
visible alongside the configuration inputs — the user does not need to scroll past the
controls to see the report.

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

- **Streaming render:** The current design collects the full report before rendering.
  v5 would call `graph.astream(...)` inside `run_graph` and yield tokens back to `app.py`.
  `app.py` would use `st.empty()` with incremental `markdown()` updates to show the report
  as it is generated. This requires `run_graph` to become an async generator and `app.py`
  to drive the stream via `run_until_complete` on a collecting coroutine.
- **Progress feedback:** A spinner is shown during the entire pipeline run. v5 could replace
  this with a per-file progress bar by emitting structured progress events from the graph
  alongside the report.
- **Multi-run history:** Session state currently stores only the most recent report. A list
  of past runs with their paths and timestamps would let the user compare reports without
  re-running the pipeline.
- **Configurable parameters:** `max_concurrency`, `compress_inbox` limit, and model names are
  hardcoded in `pipeline.py`. Exposing them as `st.sidebar` controls would let users tune the
  pipeline without editing source code.
