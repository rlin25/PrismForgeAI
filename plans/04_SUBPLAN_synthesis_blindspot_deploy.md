# SUBPLAN 04 — Synthesis, Blind Spots & Deployment [Hours 8–10]

Parent: `00_MASTERPLAN.md` · Spec: Decisions 3.10, 3.11, 3.12, 3.13, 3.16; Phase 4.

## Goal

Master Round-Table Node (blind-spot scan → record-count guard → single-shot
streaming synthesis), Streamlit render, and Docker/EC2 deploy.

## Tasks

### 1. Blind-spot detection (Decision 3.16) — Python filter, NOT a graph node
```python
def detect_blind_spots(crawled_files, global_inbox) -> List[str]:
    covered = {record.source_file for record in global_inbox}
    return [f for f in crawled_files if f not in covered]
```
Runs in the Round-Table preamble. Build a `blind_spot_block` Markdown string
naming any zero-record files and prepend it to the synthesis prompt so gaps are
acknowledged, not silently dropped. No conditional routing node, no
`gap_detected` field.

### 2. Record-count guard (Decision 3.10)
```python
SYNTHESIS_RECORD_LIMIT = 500
def compress_inbox(global_inbox, limit=SYNTHESIS_RECORD_LIMIT):
    if len(global_inbox) <= limit:
        return global_inbox, ""
    sorted_records = sorted(global_inbox,
        key=lambda r: r.payload.implied_liability_score, reverse=True)
    truncated = sorted_records[:limit]
    dropped = len(global_inbox) - limit
    warning = (f"\n\n## ⚠️ Synthesis Truncation Warning\n{dropped} lower-priority "
               f"records dropped; top {limit} by implied liability score kept.\n\n")
    return truncated, warning
```
Runs immediately after blind-spot detection. Pass the **compressed** records to
synthesis — never the raw `global_inbox`.

### 3. Synthesis (Decision 3.10)
Single-shot long-context streaming Markdown. Build prompt as
`blind_spot_block + truncation_warning + "\n\n" + json.dumps(compressed records)`.
No map-reduce hierarchy. Stream output for fast TTFT.

### 4. Streamlit bridge (Decision 3.11)
```python
import nest_asyncio; nest_asyncio.apply()   # module load
report = asyncio.get_event_loop().run_until_complete(run_graph(inputs, config))
st.markdown(report)
```
Never `asyncio.run()` inside Streamlit. Ensure `nest_asyncio` is in
`requirements.txt`.

### 5. Docker + EC2 (Decisions 3.12, 3.13)
Single-container `python:3.11-slim`, `EXPOSE 8501`,
`CMD streamlit run app.py --server.port=8501 --server.address=0.0.0.0`.
Inject keys at runtime with `-e ANTHROPIC_API_KEY=... -e GOOGLE_API_KEY=...`.
No `.env` volume mount. No Chroma in the image.

## Verification
- Zero-record file appears under "Coverage Gaps Detected".
- >500 records → truncation warning present, top-risk records preserved.
- Report streams to `st.markdown` with no "event loop already running" error.
- `docker build` succeeds; container runs locally and on EC2 with `-e` keys.

## Definition of Done (whole system)
All four subplan gates green; end-to-end run on the three-file data room yields a
cross-referenced report naming the A↔B IP/GPL contradiction.
