"""
PrismForge AI v4 — Streamlit Frontend
Async bridge: ThreadPoolExecutor + fresh event loop (Decision 3.23).
Progress feed: queue.SimpleQueue. Animated stage diagram via inline HTML.
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


# ── Animated stage diagram ────────────────────────────────────────────────────

STAGES = ["CRAWL", "ROUTE", "CHUNK", "EXTRACT", "SYNTHESIZE", "REPORT"]

def _diagram_html(stage_states: dict) -> str:
    STYLE = {
        "idle":     ("background:#f3f4f6;color:#9ca3af;border:1.5px solid #e5e7eb", ""),
        "active":   ("background:#dbeafe;color:#1d4ed8;border:1.5px solid #3b82f6;animation:pulse 1.5s ease-in-out infinite", "▶"),
        "complete": ("background:#dcfce7;color:#166534;border:1.5px solid #16a34a", "✓"),
    }
    parts = ['<style>@keyframes pulse{0%,100%{opacity:1}50%{opacity:0.6}}</style>',
             '<div style="padding:12px 16px;background:#f9fafb;border-radius:10px;'
             'border:1px solid #e5e7eb;white-space:nowrap;overflow-x:auto">']
    for i, name in enumerate(STAGES):
        s = stage_states.get(name, {"status": "idle", "detail": ""})
        style, icon = STYLE[s["status"]]
        detail = s.get("detail", "")
        detail_div = (f'<div style="font-size:10px;margin-top:3px;font-weight:normal">'
                      f'{detail}</div>') if detail else ""
        parts.append(
            f'<div style="display:inline-block;{style};padding:7px 12px;border-radius:7px;'
            f'min-width:85px;text-align:center;font-family:monospace;font-size:12px;'
            f'font-weight:700;vertical-align:top">'
            f'{"" if not icon else icon + " "}{name}{detail_div}</div>'
        )
        if i < len(STAGES) - 1:
            parts.append('<span style="padding:0 5px;color:#d1d5db;font-size:20px;'
                         'vertical-align:middle;line-height:52px">→</span>')
    parts.append("</div>")
    return "".join(parts)


# ── Progress parsing ──────────────────────────────────────────────────────────

def _parse_worker_event(raw: str):
    m = re.match(r"\[route_matrix_to_workers\] .+?: dispatching (\d+) workers", raw)
    if m:
        return ("dispatch", int(m.group(1)))
    if re.match(r"\[extraction_worker\] OK ", raw):
        return ("ok", 0)
    if "Rate limited" in raw and "retrying" in raw:
        return ("retry", 0)
    if re.match(r"\[extraction_worker\] FAILED", raw):
        return ("failed", 0)
    return None


def _fmt(raw: str):
    m = re.match(r"\[directory_crawler\] Found (\d+) readable files: (.+)", raw)
    if m:
        return f"  Files found: {m.group(2)}"
    m = re.match(r"\[dispatch_subgraphs\] Dispatching (\d+) sub-graphs", raw)
    if m:
        return f"\nDispatching {m.group(1)} document sub-graphs in parallel...\n"
    m = re.match(r"\[router_node\] (.+?): (\d+) lenses: (.+)", raw)
    if m:
        lenses = m.group(3).strip("[]").replace("'", "")
        return f"  {m.group(1)}\n    Lenses assigned: {lenses}"
    m = re.match(r"\[chunk_node\] (.+?): (\d+) chunks", raw)
    if m:
        return f"    Chunks: {m.group(2)}"
    m = re.match(r"\[handoff_node\] (.+?): complete \((\d+) records\)", raw)
    if m:
        return f"  {m.group(1)}: {m.group(2)} records captured"
    m = re.match(r"\[master_round_table_node\] Synthesizing: (\d+) records from (\d+) files", raw)
    if m:
        return f"\nSynthesizing {m.group(1)} extraction records from {m.group(2)} files..."
    m = re.match(r"\[master_round_table_node\] Report: (\d+) characters", raw)
    if m:
        return f"Report generated ({int(m.group(1)):,} characters)"
    if "[master_round_table_node] Blind spots" in raw:
        return f"  Coverage gaps: {raw.split(':', 1)[1].strip()}"
    return None


def _update_stages(raw: str, stages: dict) -> bool:
    """Map a log message to a stage-state transition. Returns True if anything changed."""
    if re.match(r"\[directory_crawler\] Found", raw):
        stages["CRAWL"]  = {"status": "complete", "detail": ""}
        stages["ROUTE"]  = {"status": "active",   "detail": ""}
        return True
    if re.match(r"\[router_node\]", raw):
        stages["ROUTE"] = {"status": "active", "detail": "assigning lenses"}
        return True
    if re.match(r"\[chunk_node\]", raw):
        stages["ROUTE"] = {"status": "complete", "detail": ""}
        stages["CHUNK"] = {"status": "active",   "detail": ""}
        return True
    if re.match(r"\[route_matrix_to_workers\]", raw):
        stages["CHUNK"]   = {"status": "complete", "detail": ""}
        stages["EXTRACT"] = {"status": "active",   "detail": "dispatching workers"}
        return True
    if re.match(r"\[handoff_node\]", raw):
        return True  # worker counter update will reflect in EXTRACT detail
    if re.match(r"\[master_round_table_node\] Synthesizing", raw):
        stages["EXTRACT"]   = {"status": "complete", "detail": ""}
        stages["SYNTHESIZE"] = {"status": "active",  "detail": ""}
        return True
    if re.match(r"\[master_round_table_node\] Report", raw):
        stages["SYNTHESIZE"] = {"status": "complete", "detail": ""}
        stages["REPORT"]     = {"status": "active",   "detail": ""}
        return True
    return False


# ── Pipeline runner ───────────────────────────────────────────────────────────

def _run_pipeline(directory_path: str, progress_q) -> str:
    _pipeline._log_fn = progress_q.put_nowait
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(run_graph(directory_path))
        finally:
            loop.close()
    finally:
        _pipeline._log_fn = print


# ── Streamlit UI ──────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="PrismForge AI — Due Diligence Risk Report",
    page_icon="🔍",
    layout="wide",
)

st.title("PrismForge AI v4")
st.caption("Dynamic Semantic Topology Engine — Corporate Due Diligence Risk Analysis")
st.divider()

# Config — left third, right stays empty until report is ready
col_cfg, _ = st.columns([1, 2])

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
    missing_keys = [k for k in ("ANTHROPIC_API_KEY", "GOOGLE_API_KEY") if not os.environ.get(k)]
    if missing_keys:
        st.warning(f"Missing: {', '.join(missing_keys)}")

    run_button = st.button(
        "Generate Risk Report",
        type="primary",
        disabled=bool(missing_keys),
    )

# Generation ──────────────────────────────────────────────────────────────────
if run_button:
    target = Path(data_room_path)
    if not target.exists() or not target.is_dir():
        st.error(f"Directory not found: {data_room_path}")
    else:
        progress_q = queue.SimpleQueue()

        # Diagram state
        stage_states = {s: {"status": "idle", "detail": ""} for s in STAGES}
        stage_states["CRAWL"] = {"status": "active", "detail": ""}

        # Log lines
        lines = []

        # Worker counter (mutable dict — no nonlocal needed)
        w = {"total": 0, "done": 0, "failed": 0, "retrying": 0, "line_idx": None}

        def worker_summary():
            s = f"    Workers: {w['done']}/{w['total']} complete"
            if w["retrying"]: s += f"  |  {w['retrying']} retrying..."
            if w["failed"]:   s += f"  |  {w['failed']} failed"
            return s

        def process_msg(raw):
            diag_changed = _update_stages(raw, stage_states)
            evt = _parse_worker_event(raw)
            log_changed = False
            if evt:
                kind, count = evt
                if kind == "dispatch":
                    w["total"] += count
                    if w["line_idx"] is None:
                        lines.append(worker_summary())
                        w["line_idx"] = len(lines) - 1
                    else:
                        lines[w["line_idx"]] = worker_summary()
                elif kind == "ok":
                    w["done"] += 1
                    if w["line_idx"] is not None:
                        lines[w["line_idx"]] = worker_summary()
                        # update EXTRACT detail with live count
                        if stage_states["EXTRACT"]["status"] == "active":
                            stage_states["EXTRACT"]["detail"] = f'{w["done"]}/{w["total"]} workers'
                            diag_changed = True
                elif kind == "retry":
                    w["retrying"] += 1
                    if w["line_idx"] is not None:
                        lines[w["line_idx"]] = worker_summary()
                elif kind == "failed":
                    w["failed"] += 1
                    w["retrying"] = max(0, w["retrying"] - 1)
                    if w["line_idx"] is not None:
                        lines[w["line_idx"]] = worker_summary()
                log_changed = True
            else:
                fmt = _fmt(raw)
                if fmt is not None:
                    lines.append(fmt)
                    log_changed = True
            return diag_changed or log_changed

        with st.status("Running pipeline...", expanded=True) as status:
            st.markdown("**Pipeline**")
            diagram_ph = st.empty()
            st.markdown("**Progress log**")
            log_ph = st.empty()

            diagram_ph.markdown(_diagram_html(stage_states), unsafe_allow_html=True)

            try:
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                    future = ex.submit(_run_pipeline, data_room_path, progress_q)

                    while not future.done():
                        changed = False
                        for _ in range(50):
                            try:
                                if process_msg(progress_q.get_nowait()):
                                    changed = True
                            except queue.Empty:
                                break
                        if changed:
                            diagram_ph.markdown(_diagram_html(stage_states), unsafe_allow_html=True)
                            log_ph.code("\n".join(lines), language=None)
                        time.sleep(0.15)

                    # Drain remaining
                    while True:
                        try:
                            process_msg(progress_q.get_nowait())
                        except queue.Empty:
                            break

                    # Final diagram state
                    stage_states["REPORT"] = {"status": "complete", "detail": ""}
                    diagram_ph.markdown(_diagram_html(stage_states), unsafe_allow_html=True)
                    log_ph.code("\n".join(lines), language=None)

                    report = future.result(timeout=600)

                st.session_state["report"] = report
                st.session_state["report_path"] = data_room_path
                status.update(label="Analysis complete", state="complete", expanded=False)

            except Exception as exc:
                status.update(label=f"Error: {exc}", state="error")
                st.error(str(exc))
                raise

# Report — only appears after generation ─────────────────────────────────────
if "report" in st.session_state:
    st.divider()
    st.subheader("Risk Report")
    st.caption(f"Source: `{st.session_state.get('report_path', '')}`")
    st.markdown(st.session_state["report"])
    st.download_button(
        label="Download Report (.md)",
        data=st.session_state["report"],
        file_name="prismforge_risk_report.md",
        mime="text/markdown",
    )
