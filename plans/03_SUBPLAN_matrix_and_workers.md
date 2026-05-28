# SUBPLAN 03 — Fan-Out Matrix & Async Extraction [Hours 6–7]

Parent: `00_MASTERPLAN.md` · Spec: Decisions 3.2, 3.4, 3.5, 3.7, 3.9; Phase 3.

## Goal

Chunk each document, build the `Chunks × Lenses` cross-product, dispatch
primitive-dict `Send` payloads, and run the async worker pool.

## Tasks

### 1. Chunking (Decision 3.5)
```python
splitter = RecursiveCharacterTextSplitter(chunk_size=4000, chunk_overlap=800)
chunks = splitter.split_text(document_text)
```
`chunk_size` is **characters**, not tokens (~4000 chars ≈ 1000 tokens). Writes
`DocumentSubState["document_chunks"]`. Do not hand-roll a token chunker.

### 2. Fan-out mapper (Decisions 3.2, 3.7)
Single-parameter conditional edge function. Read `semantic_summary` from
sub-graph state and stamp it into every payload at dispatch time:
```python
def route_matrix_to_workers(state: DocumentSubState) -> List[Send]:
    execution_matrix = []
    summary = state.get("semantic_summary", "")   # written by router_node; always present
    for chunk_idx, chunk_text in enumerate(state["document_chunks"]):
        for lens in state["dynamic_topology"]:
            worker_config = WorkerPayload(
                lens_name=lens,
                source_file=state["file_name"],
                chunk_index=chunk_idx,
                target_chunk_text=chunk_text,
                semantic_summary=summary,
            )
            execution_matrix.append(
                Send("extraction_worker", worker_config.model_dump())  # primitive dict
            )
    return execution_matrix
```
**Never** a `(state, parent_state)` signature — that is an invalid edge calling
convention and raises `TypeError` at compile time. **Never** pass a Pydantic
instance into `Send`.

### 3. Async worker (Decisions 3.2, 3.9)
Exactly one parameter; no `state`. Read summary from payload, assemble prompt in
volatile memory, `await` the structured call, wrap in `try/except`:
```python
async def extraction_worker(payload_dict: Dict[str, Any]) -> Dict[str, Any]:
    payload = WorkerPayload(**payload_dict)
    anchored_prompt_payload = (
        f"GLOBAL FILE CONTEXT:\n{payload.semantic_summary}\n\n"
        f"TARGET CHUNK:\n{payload.target_chunk_text}"
    )
    try:
        result: UniversalForm = await structured_llm.ainvoke(anchored_prompt_payload)
        record = ExtractionRecord(
            lens_name=payload.lens_name,
            source_file=payload.source_file,
            chunk_index=payload.chunk_index,
            payload=result,
        )
        return {"local_inbox": [record]}
    except Exception as e:
        print(f"[extraction_worker] FAILED {payload.lens_name}/{payload.source_file}/{payload.chunk_index}: {e}")
        return {"local_inbox": []}
```
Returns an `ExtractionRecord` object (not a raw dict). Uses `ainvoke` (sync
`.invoke()` blocks the event loop).

### 4. Concurrency (Decision 3.4)
At graph invocation only:
```python
await graph.ainvoke(inputs, config={"max_concurrency": 50})
```
No module-level `asyncio.Semaphore` (event-loop binding error risk).

## Verification
- Matrix length == chunks × lenses for a known fixture.
- Forced exception in one worker → pool continues, run completes, that
  lens/chunk simply absent from `global_inbox`.
- `Send` receives dicts only.

## Gate to Phase 4
Matrix dispatches correctly and a forced worker failure is survived.
