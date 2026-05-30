"""
PrismForge AI v4 — Streamlit Frontend
Async bridge: pipeline runs in a dedicated thread with a fresh event loop (Decision 3.23).
Progress feed: pipeline log messages streamed to UI via queue.SimpleQueue.
"""

import asyncio
import concurrent.futures
import os
import queue
import re
import time
from pathlib import Path

import streamlit as st

import pipeline as _pipeline
from pipeline import run_graph


# ── Progress formatting ───────────────────────────────────────────────────────

def _fmt(raw: str) -> str:
    """Format a pipeline log line for the progress display."""
    # [directory_crawler] Found 3 readable files: [...]
    m = re.match(r"\[directory_crawler\] Found (\d+) readable files: (.+)", raw)
    if m:
        return f"  Files found: {m.group(2)}"

    # [dispatch_subgraphs] Dispatching N sub-graphs
    m = re.match(r"\[dispatch_subgraphs\] Dispatching (\d+) sub-graphs", raw)
    if m:
        return f"\nDispatching {m.group(1)} document sub-graphs in parallel...\n"

    # [router_node] file.txt: N lenses: [...]
    m = re.match(r"\[router_node\] (.+?): (\d+) lenses: (.+)", raw)
    if m:
        lenses = m.group(3).strip("[]").replace("'", "")
        return f"  {m.group(1)}\n    Lenses assigned: {lenses}"

    # [chunk_node] file.txt: N chunks
    m = re.match(r"\[chunk_node\] (.+?): (\d+) chunks", raw)
    if m:
        return f"    Chunks: {m.group(2)}"

    # [route_matrix_to_workers] file.txt: dispatching N workers (X chunks x Y lenses)
    m = re.match(r"\[route_matrix_to_workers\] (.+?): dispatching (\d+) workers \((.+)\)", raw)
    if m:
        return f"    Workers dispatched: {m.group(2)}  ({m.group(3)})"

    # [extraction_worker] Rate limited — retrying...
    if "Rate limited" in raw and "retrying" in raw:
        return f"    [rate limited — retrying with backoff]"

    # [extraction_worker] FAILED ...
    if "[extraction_worker] FAILED" in raw:
        return f"    [worker failed after retries — skipped]"

    # [master_round_table_node] Synthesizing: N records from M files
    m = re.match(r"\[master_round_table_node\] Synthesizing: (\d+) records from (\d+) files", raw)
    if m:
        return f"\nSynthesizing {m.group(1)} extraction records from {m.group(2)} files..."

    # [master_round_table_node] Report: N characters
    m = re.match(r"\[master_round_table_node\] Report: (\d+) characters", raw)
    if m:
        return f"Report generated ({int(m.group(1)):,} characters)"

    # [master_round_table_node] Blind spots: [...]
    if "[master_round_table_node] Blind spots" in raw:
        return f"  Coverage gaps detected: {raw.split(':', 1)[1].strip()}"

    # suppress internal/noisy lines
    if any(x in raw for x in ["[dispatch_subgraphs] Could not", "Item 1", "Extracting lines"]):
        return None

    return None   # suppress unrecognised lines


# ── Pipeline runner ───────────────────────────────────────────────────────────

def _run_pipeline(directory_path: str, progress_q) -> str:
    """Run pipeline in a fresh event loop, routing logs to the progress queue."""
    _pipeline._log_fn = progress_q.put_nowait
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(run_graph(directory_path))
        finally:
            loop.close()
    finally:
        _pipeline._log_fn = print   # restore for any subsequent non-UI use


# ── Streamlit UI ──────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="PrismForge AI — Due Diligence Risk Report",
    page_icon="🔍",
    layout="wide",
)

st.title("PrismForge AI v4")
st.caption("Dynamic Semantic Topology Engine — Corporate Due Diligence Risk Analysis")

st.divider()

col_cfg, col_report = st.columns([1, 2])

with col_cfg:
    st.subheader("Configuration")

    default_path = str(Path(__file__).parent / "data_room")
    data_room_path = st.text_input(
        "Data Room Directory",
        value=default_path,
        help="Path to a directory containing plain-text due diligence documents.",
    )

    st.caption(
        "Required environment variables:\n"
        "- `ANTHROPIC_API_KEY` (Claude Sonnet — extraction + synthesis)\n"
        "- `GOOGLE_API_KEY` (Gemini Flash — document routing)"
    )

    missing_keys = []
    if not os.environ.get("ANTHROPIC_API_KEY"):
        missing_keys.append("ANTHROPIC_API_KEY")
    if not os.environ.get("GOOGLE_API_KEY"):
        missing_keys.append("GOOGLE_API_KEY")
    if missing_keys:
        st.warning(f"Missing environment variables: {', '.join(missing_keys)}")

    run_button = st.button(
        "Generate Risk Report",
        type="primary",
        disabled=bool(missing_keys),
    )

    if run_button:
        target = Path(data_room_path)
        if not target.exists():
            st.error(f"Directory not found: {data_room_path}")
        elif not target.is_dir():
            st.error(f"Not a directory: {data_room_path}")
        else:
            progress_q = queue.SimpleQueue()

            with st.status("Running pipeline...", expanded=True) as status:
                st.markdown("**Pipeline progress**")
                log_placeholder = st.empty()
                lines = []

                try:
                    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                        future = ex.submit(_run_pipeline, data_room_path, progress_q)

                        while not future.done():
                            changed = False
                            for _ in range(50):
                                try:
                                    raw = progress_q.get_nowait()
                                    fmt = _fmt(raw)
                                    if fmt is not None:
                                        lines.append(fmt)
                                        changed = True
                                except queue.Empty:
                                    break
                            if changed:
                                log_placeholder.code(
                                    "\n".join(lines), language=None
                                )
                            time.sleep(0.15)

                        # drain remaining messages
                        while True:
                            try:
                                raw = progress_q.get_nowait()
                                fmt = _fmt(raw)
                                if fmt is not None:
                                    lines.append(fmt)
                            except queue.Empty:
                                break
                        log_placeholder.code("\n".join(lines), language=None)

                        report = future.result(timeout=600)

                    st.session_state["report"] = report
                    st.session_state["report_path"] = data_room_path
                    status.update(label="Analysis complete", state="complete", expanded=False)

                except Exception as exc:
                    status.update(label=f"Pipeline error: {exc}", state="error")
                    st.error(str(exc))
                    raise

with col_report:
    st.subheader("Risk Report")
    if "report" in st.session_state:
        st.caption(f"Source: `{st.session_state.get('report_path', '')}`")
        st.markdown(st.session_state["report"])

        st.download_button(
            label="Download Report (.md)",
            data=st.session_state["report"],
            file_name="prismforge_risk_report.md",
            mime="text/markdown",
        )
    else:
        st.info(
            "Set the data room path and click **Generate Risk Report** to begin. "
            "The pipeline will crawl documents, run parallel extraction workers, "
            "and synthesize a cross-referenced liability risk report."
        )
