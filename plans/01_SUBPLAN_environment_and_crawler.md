# SUBPLAN 01 — Environment Baseline & Crawler [Hours 1–2]

Parent: `00_MASTERPLAN.md` · Spec: Decisions 3.6, 3.14; Phase 1.

## Goal

Standing Python environment, an adversarial mock data room, and a crash-proof
directory crawler that populates `ParentState["crawled_files"]`.

## Tasks

### 1. Dependencies (`requirements.txt`)
```
langgraph
pydantic>=2
langchain
langchain-text-splitters
langchain-google-genai
langchain-anthropic
nest_asyncio
streamlit
```
**Do not** add `chromadb` or any vector store. Its presence is a build error.

### 2. Mock data room (`/data_room/`)
Exactly three `.txt` files with embedded cross-document contradictions:
- `file_a.txt` — proprietary code warranty (asserts full IP ownership).
- `file_b.txt` — GPL v3 upstream dependency declaration (contradicts A).
- `file_c.txt` — liability cap clause (interacts with both).
This dataset is the contradiction-linkage test fixture for later phases.

### 3. Directory crawler node
Defensive read loop — skip unreadable/binary files silently:
```python
for file_path in directory.iterdir():
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
    except (UnicodeDecodeError, IsADirectoryError, PermissionError):
        continue
```
Crawler must populate `ParentState["crawled_files"]` with every successfully
read filename **before** any sub-graph runs. `crawled_files` is a plain
`List[str]`, single-write, **no reducer**.

## Verification
- Drop a `.DS_Store` / binary file in `/data_room/` → crawler skips it, no crash.
- `crawled_files` contains exactly the three text filenames.

## Gate to Phase 2
`crawled_files` is populated and the crawler survives a binary file. Stop here
until both hold.
