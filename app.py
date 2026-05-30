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

import streamlit.components.v1 as components

import streamlit as st

import pipeline as _pipeline
from pipeline import run_graph


# ── Animated stage diagram ────────────────────────────────────────────────────

STAGES = ["CRAWL", "ROUTE", "CHUNK", "EXTRACT", "SYNTHESIZE", "REPORT"]

_STAGE_TIPS = {
    "CRAWL":     "Scans the data room directory and reads every .txt file. Binary or unreadable files are silently skipped. Produces the file list for parallel sub-graph dispatch.",
    "ROUTE":     "Sends each document to Gemini Flash in a single call that returns both a 200-400 word semantic summary and a tailored set of 3–7 extraction lenses specific to that document's content.",
    "CHUNK":     "Splits each document into 4,000-character overlapping segments (800-char overlap) using LangChain's RecursiveCharacterTextSplitter — one chunk per extraction worker call.",
    "EXTRACT":   "Dispatches one Claude Haiku worker per Chunk × Lens pair. All workers run concurrently. Each returns a structured finding: entity, verbatim evidence quote, risk score 1–10, and cross-document dependency links.",
    "SYNTHESIZE":"Claude Sonnet receives all extraction records sorted by risk score, identifies files with zero coverage, and generates a structured Markdown report in a single long-context call.",
    "REPORT":    "The finished risk report — cross-referenced contradictions named with evidence quotes, critical findings by score, executive summary, and prioritised recommendations.",
}

def _diagram_html(stage_states: dict) -> str:
    STYLE = {
        "idle":     ("background:#f3f4f6;color:#9ca3af;border:1.5px solid #e5e7eb", ""),
        "active":   ("background:#dbeafe;color:#1d4ed8;border:1.5px solid #3b82f6;animation:pulse 1.5s ease-in-out infinite", "▶"),
        "complete": ("background:#dcfce7;color:#166534;border:1.5px solid #16a34a", "✓"),
    }
    BOX = "width:100px;height:56px;box-sizing:border-box;"
    TIP_CSS = """
    <style>
    @keyframes pulse{0%,100%{opacity:1}50%{opacity:0.6}}
    .ua-tip{position:relative;display:inline-flex;flex-shrink:0}
    .ua-tip .ua-tiptext{
        visibility:hidden;opacity:0;
        background:#1f2937;color:#f9fafb;
        font-size:11px;font-weight:400;font-family:sans-serif;
        line-height:1.4;white-space:normal;text-align:left;
        width:200px;padding:8px 10px;border-radius:7px;
        position:absolute;bottom:calc(100% + 6px);left:50%;
        transform:translateX(-50%);z-index:9999;
        pointer-events:none;transition:opacity 0.15s;
        box-shadow:0 4px 12px rgba(0,0,0,0.25);
    }
    .ua-tip:hover .ua-tiptext{visibility:visible;opacity:1}
    </style>
    """
    parts = [TIP_CSS,
             '<div style="padding:12px 16px;background:#f9fafb;border-radius:10px;'
             'border:1px solid #e5e7eb;white-space:nowrap;overflow-x:auto;'
             'display:flex;align-items:center;gap:0">']
    for i, name in enumerate(STAGES):
        s = stage_states.get(name, {"status": "idle", "detail": ""})
        style, icon = STYLE[s["status"]]
        detail = s.get("detail", "")
        detail_div = (f'<div style="font-size:9px;margin-top:2px;font-weight:normal;'
                      f'white-space:nowrap;overflow:hidden;text-overflow:ellipsis">'
                      f'{detail}</div>') if detail else ""
        tip = _STAGE_TIPS.get(name, "")
        parts.append(
            f'<div class="ua-tip">'
            f'<div style="{BOX}{style};display:inline-flex;flex-direction:column;'
            f'align-items:center;justify-content:center;border-radius:7px;'
            f'font-family:monospace;font-size:12px;font-weight:700;'
            f'padding:4px 6px;text-align:center;cursor:default">'
            f'<div>{"" if not icon else icon + " "}{name}</div>{detail_div}</div>'
            f'<span class="ua-tiptext">{tip}</span>'
            f'</div>'
        )
        if i < len(STAGES) - 1:
            parts.append('<span style="padding:0 4px;color:#d1d5db;font-size:18px;'
                         'flex-shrink:0;line-height:1">→</span>')
    parts.append("</div>")
    return "".join(parts)


# ── Topology HTML (per-document lens assignments) ────────────────────────────

# Lens category → chip color
_LENS_COLORS = {
    "IP_Ownership":    ("#dbeafe", "#1d4ed8"),
    "IP_Warranty":     ("#dbeafe", "#1d4ed8"),
    "License_Compliance": ("#dcfce7", "#166534"),
    "Liability_Cap":   ("#fef3c7", "#92400e"),
    "Indemnification": ("#f3e8ff", "#6b21a8"),
    "Change_of_Control": ("#ffe4e6", "#9f1239"),
    "Data_Privacy":    ("#e0f2fe", "#0369a1"),
    "Regulatory_Approval": ("#f0fdf4", "#15803d"),
}
_DEFAULT_LENS_COLOR = ("#f3f4f6", "#374151")

_LENS_TIPS = {
    "IP_Ownership":       "Who owns the intellectual property? Looks for ownership assignments, work-for-hire clauses, and title transfer language.",
    "IP_Warranty":        "Does the licensor warrant they have clean title? Flags warranties claiming no third-party IP encumbrances — often contradicted by open-source disclosures.",
    "License_Compliance": "Are all software licenses being honoured? Surfaces GPL/LGPL obligations, open-source component disclosures, and compliance representations.",
    "Liability_Cap":      "What is the ceiling on damages? Identifies aggregate liability limits and carve-outs (e.g. IP infringement claims that are often uncapped).",
    "Indemnification":    "Who covers whom for what losses? Extracts indemnification obligations, exclusions, and the gap between what is indemnified and what is not.",
    "Change_of_Control":  "What happens in an acquisition? Flags consent requirements, termination triggers, and assignment restrictions that activate on a change of control.",
    "Data_Privacy":       "What data-processing obligations exist? Identifies GDPR/CCPA compliance warranties, data breach liability, and processor agreements.",
    "Regulatory_Approval":"Are there regulatory conditions? Surfaces approvals required for the transaction to close or for the product to be sold.",
}
_DEFAULT_LENS_TIP = "Domain-specific extraction lens applied to each document chunk."

def _topology_html(file_topologies: dict) -> str:
    if not file_topologies:
        return ""
    header_tip = ("Each document gets a unique set of lenses chosen by the router based on its content. "
                  "This is the Dynamic Semantic Topology (DST) feature — the pipeline adapts to each "
                  "document rather than applying a fixed schema to all files.")
    rows = [
        '<div style="margin-top:10px;padding:12px 16px;background:#f9fafb;'
        'border-radius:10px;border:1px solid #e5e7eb;font-family:monospace">',
        f'<div class="ua-tip" style="display:inline-block;margin-bottom:8px">'
        f'<span style="font-size:11px;font-weight:700;color:#6b7280;'
        f'letter-spacing:0.05em;cursor:default">DYNAMIC LENS SELECTION ⓘ</span>'
        f'<span class="ua-tiptext" style="width:240px">{header_tip}</span>'
        f'</div>',
    ]
    for fname, lenses in file_topologies.items():
        short = fname.replace("_", " ").replace(".txt", "")
        rows.append(f'<div style="margin-bottom:6px">'
                    f'<span style="font-size:11px;color:#374151;font-weight:600">{short}</span>'
                    f'<br style="line-height:4px">')
        for lens in lenses:
            bg, fg = _LENS_COLORS.get(lens, _DEFAULT_LENS_COLOR)
            tip = _LENS_TIPS.get(lens, _DEFAULT_LENS_TIP)
            rows.append(
                f'<span class="ua-tip" style="display:inline-block;margin:3px 3px 0 0">'
                f'<span style="display:inline-block;padding:2px 8px;border-radius:12px;'
                f'font-size:11px;font-weight:600;background:{bg};color:{fg};cursor:default">'
                f'{lens}</span>'
                f'<span class="ua-tiptext">{tip}</span>'
                f'</span>'
            )
        rows.append('</div>')
    rows.append('</div>')
    return "".join(rows)


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


# ── Progress log HTML renderer with per-line tooltips ─────────────────────────

_LOG_TIPS = [
    (r"Files found:",
     "The directory crawler successfully read these files. Binary and unreadable files are silently skipped."),
    (r"Dispatching \d+ document sub-graphs",
     "One isolated LangGraph sub-graph per file — they run in parallel. Each sub-graph owns its own router → chunk → worker → handoff pipeline."),
    (r"Lenses assigned:",
     "The router's output: Gemini Flash read the full document in a single call and selected these extraction lenses based on the document's specific content. Different documents get different lenses — this is the Dynamic Semantic Topology (DST) feature."),
    (r"Chunks:",
     "The document was split into overlapping 4,000-character segments (800-char overlap). One Claude Haiku worker will be dispatched per Chunk × Lens pair."),
    (r"Workers:",
     "One Claude Haiku API call per Chunk × Lens combination. All workers run concurrently. The counter updates as each call completes, retries on rate limits, or permanently fails."),
    (r"Synthesizing \d+ extraction records",
     "All worker results collected. Records are sorted by risk score descending, capped at 500, and passed to Claude Sonnet in a single long-context call that produces the final cross-referenced report."),
    (r"Report generated",
     "Synthesis complete. The Markdown report appears below — cross-document contradictions, critical findings by risk score, executive summary, and recommendations."),
    (r"Coverage gaps:",
     "Files that were crawled but produced zero extraction records — either the content was empty or all workers failed. Named explicitly in the report rather than silently omitted."),
    (r"\[rate limited",
     "A worker received a 429 rate-limit error from the API. It will retry with exponential backoff (15s then 30s) before giving up."),
    (r"\[worker failed",
     "A worker exhausted all retries and returned no finding for that Chunk × Lens pair. The remaining workers continue — the pool never crashes on individual failures."),
]

def _log_line_tip(line: str) -> str:
    """Return tooltip text for a log line, or empty string."""
    stripped = line.strip()
    for pattern, tip in _LOG_TIPS:
        if re.search(pattern, stripped):
            return tip
    return ""

def _log_html(lines: list) -> str:
    """Render the progress log as HTML with per-line hover tooltips."""
    if not lines:
        return ""
    rows = ['<div style="font-family:monospace;font-size:12px;line-height:1.7;'
            'background:#f8f9fa;border:1px solid #e5e7eb;border-radius:8px;'
            'padding:10px 14px;overflow-x:auto;white-space:pre-wrap">']
    for line in lines:
        tip = _log_line_tip(line)
        escaped = line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        if tip:
            rows.append(
                f'<span class="ua-tip" style="display:block">'
                f'<span style="cursor:default;display:block">{escaped}</span>'
                f'<span class="ua-tiptext" style="width:260px;white-space:normal;'
                f'top:auto;bottom:calc(100% + 4px)">{tip}</span>'
                f'</span>'
            )
        else:
            rows.append(f'<span style="display:block">{escaped}</span>')
    rows.append("</div>")
    return "".join(rows)


def _fmt(raw: str):
    m = re.match(r"\[directory_crawler\] Found (\d+) readable files: (.+)", raw)
    if m:
        return f"  Files found: {m.group(2)}"
    m = re.match(r"\[dispatch_subgraphs\] Dispatching (\d+) sub-graphs", raw)
    if m:
        return f"\nDispatching {m.group(1)} document sub-graphs in parallel...\n"
    m = re.match(r"\[router_node\] (.+?): (\d+) lenses: (.+)", raw)
    if m:
        return None  # handled by topology widget; suppress from text log
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

# JS tooltip: position:fixed follows mouse — escapes all overflow constraints.
# Runs in an iframe (st.components.v1.html) and attaches to window.parent.document.
components.html("""
<script>
(function(){
  if(window.parent._ua_tt_init) return;
  window.parent._ua_tt_init = true;
  var doc = window.parent.document;
  var tt = doc.createElement('div');
  tt.style.cssText = [
    'position:fixed','background:#1f2937','color:#f9fafb',
    'font-size:11px','font-family:sans-serif','line-height:1.5',
    'padding:8px 11px','border-radius:7px','max-width:260px',
    'white-space:normal','z-index:99999','pointer-events:none',
    'box-shadow:0 4px 14px rgba(0,0,0,.3)','display:none',
    'transition:opacity .12s'
  ].join(';');
  doc.body.appendChild(tt);

  function pos(e){
    var x=e.clientX+14, y=e.clientY-10;
    var w=tt.offsetWidth, h=tt.offsetHeight;
    var vw=window.parent.innerWidth, vh=window.parent.innerHeight;
    tt.style.left=(x+w>vw ? e.clientX-w-14 : x)+'px';
    tt.style.top =(y+h>vh ? e.clientY-h-10 : y)+'px';
  }
  doc.addEventListener('mouseover',function(e){
    var el=e.target.closest('.ua-tip');
    if(el){
      var tip=el.querySelector('.ua-tiptext');
      if(tip && tip.textContent.trim()){
        tt.textContent=tip.textContent.trim();
        tt.style.display='block';
        pos(e);
      }
    }
  });
  doc.addEventListener('mousemove',function(e){
    if(tt.style.display!=='none') pos(e);
  });
  doc.addEventListener('mouseout',function(e){
    var el=e.target.closest('.ua-tip');
    if(el && !el.contains(e.relatedTarget)) tt.style.display='none';
  });
})();
</script>
""", height=0)

st.title("PrismForge AI v4")
st.caption("Dynamic Semantic Topology Engine — Corporate Due Diligence Risk Analysis")
st.divider()

# Sticky expander header — activates only when details is open so the
# collapse button stays visible while scrolling through document content.
st.markdown("""
<style>
/* Sticky expander header while scrolling through open document content */
details[open] > summary {
    position: sticky;
    top: 3.5rem;
    z-index: 999;
    background-color: var(--background-color, #ffffff);
    border-bottom: 1px solid var(--secondary-background-color, #e6e6e6);
    padding-bottom: 6px;
    backdrop-filter: blur(6px);
    -webkit-backdrop-filter: blur(6px);
}
/* Hide CSS tooltip spans — JS fixed-position tooltip handles display */
.ua-tiptext { display: none !important; }
</style>
""", unsafe_allow_html=True)

with st.container():
    st.subheader("Configuration")
    default_path = str(Path(__file__).parent / "data_room")
    data_room_path = st.text_input(
        "Data Room Directory",
        value=default_path,
        help=(
            "Path to a directory of plain-text (.txt) due diligence documents. "
            "The pipeline reads every .txt file here, skipping binary files. "
            "Run preprocess.py first to convert raw EDGAR .htm filings into .txt."
        ),
    )
    st.caption(
        "Required environment variables:\n"
        "- `ANTHROPIC_API_KEY` (Claude Haiku — extraction · Claude Sonnet — synthesis)\n"
        "- `GOOGLE_API_KEY` (Gemini Flash — document routing)"
    )
    missing_keys = [k for k in ("ANTHROPIC_API_KEY", "GOOGLE_API_KEY") if not os.environ.get(k)]
    if missing_keys:
        st.warning(f"Missing: {', '.join(missing_keys)}")

    # Document preview
    _preview_dir = Path(data_room_path)
    if _preview_dir.exists() and _preview_dir.is_dir():
        _docs = sorted(_preview_dir.glob("*.txt"))
        if _docs:
            st.divider()
            st.caption(f"**Data room** — {len(_docs)} document(s)")
            for _doc in _docs:
                with st.expander(_doc.name):
                    try:
                        _text = _doc.read_text(encoding="utf-8", errors="replace")
                        st.code(_text, language=None)
                        st.caption(f"{len(_text):,} characters")
                    except Exception:
                        st.error("Could not read file.")
        else:
            st.caption("No .txt files found in data room directory.")

    st.divider()
    run_button = st.button(
        "Generate Risk Report",
        type="primary",
        disabled=bool(missing_keys),
        help=(
            "Runs the full pipeline: crawl → route (Gemini Flash assigns lenses per document) → "
            "chunk → extract (Claude Haiku workers, one per Chunk × Lens pair) → "
            "synthesize (Claude Sonnet produces the final cross-referenced report). "
            "Takes 1–3 minutes for the current two-document data room."
        ),
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

        # Per-document lens assignments (populated as routing completes)
        file_topologies = {}

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
            nonlocal_flag = [False]  # use list to avoid nonlocal in nested scope
            # Capture router output for topology widget
            m = re.match(r"\[router_node\] (.+?): \d+ lenses: (.+)", raw)
            if m:
                fname = m.group(1)
                lenses = [l.strip().strip("'") for l in m.group(2).strip("[]").split(",")]
                file_topologies[fname] = lenses
                topology_ph.markdown(_topology_html(file_topologies), unsafe_allow_html=True)

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
            topology_ph = st.empty()
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
                            log_ph.markdown(_log_html(lines), unsafe_allow_html=True)
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
                    log_ph.markdown(_log_html(lines), unsafe_allow_html=True)

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
