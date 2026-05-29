"""
PrismForge AI v4 — Streamlit Frontend
Async bridge: pipeline runs in a dedicated thread with a fresh event loop.
This avoids "Future attached to a different loop" errors that occur when
LangGraph's concurrent Send dispatch interacts with Streamlit's internal loop.
"""

import asyncio
import concurrent.futures
import os
from pathlib import Path

import streamlit as st

from pipeline import run_graph


def _run_pipeline(directory_path: str) -> str:
    """Run the async pipeline in a fresh event loop on a dedicated thread."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(run_graph(directory_path))
    finally:
        loop.close()

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
            with st.spinner("Analyzing documents… This may take several minutes."):
                try:
                    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                        report = ex.submit(_run_pipeline, data_room_path).result(timeout=600)
                    st.session_state["report"] = report
                    st.session_state["report_path"] = data_room_path
                    st.success("Analysis complete.")
                except Exception as exc:
                    st.error(f"Pipeline error: {exc}")
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
