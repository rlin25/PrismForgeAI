"""
PrismForge AI v4 — Streamlit Frontend
Async bridge: nest_asyncio.apply() + get_event_loop().run_until_complete()
Never asyncio.run() inside Streamlit (Decision 3.11, Invariant I2).
"""

import asyncio
import os
from pathlib import Path

import nest_asyncio
nest_asyncio.apply()  # patch Streamlit's running event loop before any async calls

import streamlit as st

from pipeline import run_graph

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
                    report = asyncio.get_event_loop().run_until_complete(
                        run_graph(data_room_path)
                    )
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
