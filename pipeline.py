"""
PrismForge AI v4 — Dynamic Semantic Topology (DST) Engine
Multi-agent LangGraph pipeline for corporate due diligence risk analysis.

Architecture: Directory Crawler → per-file sub-graph (Router → Chunk → Fan-out Workers → Handoff)
              → Master Round-Table Node → Final Risk Report
"""

import asyncio
import json
from pathlib import Path
from operator import add
from typing import Annotated, Any, Dict, List, Tuple

from langchain_anthropic import ChatAnthropic
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langgraph.graph import StateGraph, START, END
from langgraph.types import Send
from pydantic import BaseModel, Field
from typing_extensions import TypedDict


# ── Pydantic Schemas (§2) ─────────────────────────────────────────────────────

class RouterOutput(BaseModel):
    semantic_summary: str = Field(
        description=(
            "A dense, high-information profile of the document's primary subject matter, "
            "key entities, contractual obligations, and risk domains. 200-400 words."
        )
    )
    dynamic_topology: List[str] = Field(
        description=(
            "Array of domain-specific extraction lens identifiers applicable to this "
            "document (e.g. 'IP_Ownership', 'License_Compliance', 'Liability_Cap', "
            "'Change_of_Control', 'Data_Privacy'). 3-7 lenses per document."
        )
    )


class DependencyLink(BaseModel):
    target_file: str = Field(
        description="The precise filename or entity ID being contradicted or complemented."
    )
    target_concept: str = Field(
        description="The explicit contractual clause, open-source license, or operational liability field."
    )
    nature_of_contradiction: str = Field(
        description="Detailed technical evaluation of the variance between the source documents."
    )


class UniversalForm(BaseModel):
    entity_or_concept: str = Field(
        description="Primary target asset, liability, or operational vector identifier."
    )
    factual_evidence_quote: str = Field(
        description="Verbatim text string extracted directly from the source material."
    )
    implied_liability_score: int = Field(
        ge=1, le=10,
        description="Risk quantification weight score."
    )
    cross_reference_dependencies: List[DependencyLink] = Field(
        default=[],
        description="Structured array of identified links to outside files or domains."
    )


class ExtractionRecord(BaseModel):
    lens_name: str
    source_file: str
    chunk_index: int
    payload: UniversalForm


class WorkerPayload(BaseModel):
    lens_name: str
    source_file: str
    chunk_index: int
    target_chunk_text: str
    semantic_summary: str  # stamped at dispatch time from DocumentSubState["semantic_summary"]


# ── LLM Singletons (Invariant S1) ────────────────────────────────────────────
# Instantiated once at module scope — never inside a node, edge function, or worker.

router_llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash")
structured_router = router_llm.with_structured_output(RouterOutput)

llm = ChatAnthropic(model="claude-sonnet-4-20250514")
structured_llm = llm.with_structured_output(UniversalForm)

# Chunker singleton (Decision 3.5): chunk_size in characters, not tokens
splitter = RecursiveCharacterTextSplitter(chunk_size=4000, chunk_overlap=800)


# ── State Schemas ─────────────────────────────────────────────────────────────

class ParentState(TypedDict):
    directory_path: str
    # merge reducer — parallel sub-graph handoffs accumulate, never overwrite (Invariant P1)
    summary_store: Annotated[Dict[str, str], lambda a, b: {**a, **b}]
    crawled_files: List[str]           # single write by crawler, no reducer (Invariant P2)
    global_inbox: Annotated[List[ExtractionRecord], add]
    master_risk_report: str


class DocumentSubState(TypedDict):
    source_material: str
    file_name: str
    semantic_summary: str
    dynamic_topology: List[str]
    document_chunks: List[str]
    local_inbox: Annotated[List[ExtractionRecord], add]
    # gap_detected and blind_spots intentionally absent (removed v6 — Decision 3.16)


# ── LLM Prompts ───────────────────────────────────────────────────────────────

ROUTER_SYSTEM_PROMPT = """You are a corporate due diligence document analyst.
Given the full text of a document, you must produce:
1. A dense semantic summary (200-400 words) covering key entities, obligations, and risk domains.
2. A list of 3-7 extraction lens identifiers that are directly applicable to this document.

Valid lens identifiers include but are not limited to:
IP_Ownership, License_Compliance, Liability_Cap, Indemnification,
Change_of_Control, Data_Privacy, Employment_Obligations, Revenue_Share,
Regulatory_Approval, IP_Warranty.

Return only the structured RouterOutput object. No preamble."""

EXTRACTION_SYSTEM_PROMPT = """You are a corporate due diligence risk extraction specialist.

You will receive:
1. GLOBAL FILE CONTEXT: a dense semantic summary of the entire document
2. TARGET CHUNK: a specific text segment from that document

Your task: apply the specified extraction lens to the TARGET CHUNK and extract the most significant
risk-bearing finding. The GLOBAL FILE CONTEXT gives you awareness of the full document so you can
identify cross-document contradictions and dependencies.

Extract ONE primary finding per call. Focus on concrete, evidence-backed liability risks.
Cross-reference dependencies should name specific OTHER files when contradictions or interactions exist.
Use implied_liability_score 1-10 where 9-10 = existential/critical risk, 7-8 = major risk,
5-6 = significant risk, 3-4 = moderate risk, 1-2 = minor/informational."""

SYNTHESIS_SYSTEM_PROMPT = """You are a senior corporate due diligence risk analyst preparing a final investment risk report.

You have received structured extraction records from a multi-document due diligence analysis.
Each record contains: entity/concept, verbatim evidence quote, implied liability score (1-10),
and cross-reference dependencies linking to other documents.

Synthesize ALL records into a comprehensive cross-referenced liability risk report in Markdown.

REQUIRED REPORT STRUCTURE:
# Due Diligence Risk Report — PrismForge AI Analysis

## Executive Summary
(3-5 sentences: overall risk posture, highest risks, recommendation)

## Critical Findings (Score 8-10)
(All findings with implied_liability_score >= 8, with evidence quotes and cross-document links)

## Cross-Document Contradictions
(Explicitly name every contradiction identified across documents — e.g. File A's IP warranty vs
File B's GPL dependency disclosure. Quote both sides. Explain the legal/financial consequence.)

## Risk Analysis by Category
(Group remaining findings by lens_name/risk domain)

## Coverage Gaps
(Populated automatically — do not invent gaps)

## Recommendations
(Actionable items, ordered by priority)

---
Rules:
- Name specific files for every cross-document contradiction
- Include verbatim evidence quotes for all critical findings
- Do NOT omit any finding with implied_liability_score >= 7
- Be specific, technical, and legally precise
- Format tables where helpful for comparison"""


# ── Pure Functions ────────────────────────────────────────────────────────────

def detect_blind_spots(
    crawled_files: List[str],
    global_inbox: List[ExtractionRecord]
) -> List[str]:
    """Returns filenames present in crawled_files but absent from global_inbox. Decision 3.16."""
    covered = {record.source_file for record in global_inbox}
    return [f for f in crawled_files if f not in covered]


SYNTHESIS_RECORD_LIMIT = 500


def compress_inbox(
    global_inbox: List[ExtractionRecord],
    limit: int = SYNTHESIS_RECORD_LIMIT
) -> Tuple[List[ExtractionRecord], str]:
    """
    Guard: if > limit records, keep top-N by implied_liability_score. Decision 3.10.
    Returns (records_for_synthesis, truncation_warning_block).
    """
    if len(global_inbox) <= limit:
        return global_inbox, ""

    sorted_records = sorted(
        global_inbox,
        key=lambda r: r.payload.implied_liability_score,
        reverse=True
    )
    truncated = sorted_records[:limit]
    dropped = len(global_inbox) - limit
    warning = (
        f"\n\n## ⚠️ Synthesis Truncation Warning\n"
        f"{dropped} lower-priority extraction records were dropped to fit the synthesis "
        f"context window. Only the top {limit} records by implied liability score are included. "
        f"High-risk signals are preserved; low-risk signals may be underrepresented.\n\n"
    )
    return truncated, warning


# ── Fan-Out Matrix Builder (Decision 3.7) ─────────────────────────────────────

def route_matrix_to_workers(
    file_name: str,
    document_chunks: List[str],
    dynamic_topology: List[str],
    semantic_summary: str,
) -> List[Dict[str, Any]]:
    """
    Builds the Chunks × Lenses cross-product execution matrix.
    Stamps semantic_summary into every WorkerPayload at dispatch time.
    Returns primitive dicts only (never Pydantic instances) — Invariant E3.
    """
    execution_matrix = []
    for chunk_idx, chunk_text in enumerate(document_chunks):
        for lens in dynamic_topology:
            worker_config = WorkerPayload(
                lens_name=lens,
                source_file=file_name,
                chunk_index=chunk_idx,
                target_chunk_text=chunk_text,
                semantic_summary=semantic_summary,  # stamped once per dispatch batch
            )
            execution_matrix.append(worker_config.model_dump())  # primitive dict, not Pydantic
    return execution_matrix


# ── Async Extraction Worker (Decision 3.2, 3.9) ───────────────────────────────

async def extraction_worker(payload_dict: Dict[str, Any]) -> Dict[str, Any]:
    """
    Exactly one parameter (payload_dict). No state parameter — LangGraph does not
    inject parent state into Send-dispatched nodes (Invariant X1).
    Entire body wrapped in try/except (Invariant X4) — any failure returns empty list.
    """
    try:
        payload = WorkerPayload(**payload_dict)
        # Assemble anchored prompt in volatile memory (Decision 3.2)
        anchored_prompt = (
            f"EXTRACTION LENS: {payload.lens_name}\n\n"
            f"GLOBAL FILE CONTEXT:\n{payload.semantic_summary}\n\n"
            f"TARGET CHUNK (chunk {payload.chunk_index} of {payload.source_file}):\n"
            f"{payload.target_chunk_text}"
        )
        result: UniversalForm = await structured_llm.ainvoke([
            {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
            {"role": "user", "content": anchored_prompt},
        ])
        record = ExtractionRecord(
            lens_name=payload.lens_name,
            source_file=payload.source_file,
            chunk_index=payload.chunk_index,
            payload=result,
        )
        return {"local_inbox": [record]}
    except Exception as e:
        label = (
            f"{payload_dict.get('lens_name', '?')}/"
            f"{payload_dict.get('source_file', '?')}/"
            f"{payload_dict.get('chunk_index', '?')}"
        )
        print(f"[extraction_worker] FAILED {label}: {e}")
        return {"local_inbox": []}  # Invariant X4: never crashes pool


# ── LangGraph Nodes ───────────────────────────────────────────────────────────

def directory_crawler(state: ParentState) -> Dict[str, Any]:
    """
    Defensive read loop — skips unreadable/binary files silently. Decision 3.6.
    Populates crawled_files before any sub-graph runs (Invariant P2).
    """
    directory = Path(state["directory_path"])
    crawled_files = []
    for file_path in sorted(directory.iterdir()):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                f.read()
            crawled_files.append(file_path.name)
        except (UnicodeDecodeError, IsADirectoryError, PermissionError):
            continue
    print(f"[directory_crawler] Found {len(crawled_files)} readable files: {crawled_files}")
    return {"crawled_files": crawled_files}


async def process_document(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Per-document sub-graph (Decisions 3.1–3.7, 3.15):
      router_node → chunk_node → route_matrix_to_workers → extraction_worker pool → handoff_node

    Receives {source_material, file_name} via Send dispatch.
    Returns {global_inbox, summary_store} for parent state accumulation via reducers.
    """
    source_material: str = state["source_material"]
    file_name: str = state["file_name"]

    print(f"[process_document] Starting: {file_name}")

    # ── Router node: single combined call (Decision 3.15, Invariant R1) ──────
    router_result: RouterOutput = await structured_router.ainvoke([
        {"role": "system", "content": ROUTER_SYSTEM_PROMPT},
        {"role": "user", "content": source_material},
    ])
    print(
        f"[process_document] {file_name}: router complete, "
        f"{len(router_result.dynamic_topology)} lenses: {router_result.dynamic_topology}"
    )

    # ── Chunk node (Decision 3.5, Invariant C1) ───────────────────────────────
    document_chunks = splitter.split_text(source_material)
    print(f"[process_document] {file_name}: {len(document_chunks)} chunks")

    # ── Fan-out matrix (Decision 3.7) ─────────────────────────────────────────
    payloads = route_matrix_to_workers(
        file_name=file_name,
        document_chunks=document_chunks,
        dynamic_topology=router_result.dynamic_topology,
        semantic_summary=router_result.semantic_summary,
    )
    print(f"[process_document] {file_name}: dispatching {len(payloads)} workers")

    # ── Async worker pool (Decision 3.4) ──────────────────────────────────────
    # asyncio.gather provides concurrent execution within the sub-graph.
    # max_concurrency at graph invocation caps parallel document pipelines.
    worker_results = await asyncio.gather(
        *[extraction_worker(p) for p in payloads],
        return_exceptions=True,
    )

    # ── Collect results ────────────────────────────────────────────────────────
    local_inbox: List[ExtractionRecord] = []
    for r in worker_results:
        if isinstance(r, dict) and r.get("local_inbox"):
            local_inbox.extend(r["local_inbox"])

    print(
        f"[process_document] {file_name}: {len(local_inbox)}/{len(payloads)} "
        f"workers produced records"
    )

    # ── Handoff node (Decisions 3.1, 3.3, Invariants H1, H2) ─────────────────
    # Single atomic return dict — no pre-fan-out handoff exists.
    # global_inbox accumulated via add reducer; summary_store via merge reducer.
    return {
        "global_inbox": local_inbox,
        "summary_store": {file_name: router_result.semantic_summary},
    }


async def master_round_table_node(state: ParentState) -> Dict[str, Any]:
    """
    Terminal synthesis node (Decisions 3.10, 3.16):
    Preamble: detect_blind_spots() → compress_inbox()
    Synthesis: single-shot long-context Markdown report.
    """
    print(
        f"[master_round_table_node] Starting synthesis: "
        f"{len(state['global_inbox'])} total records from "
        f"{len(state['crawled_files'])} crawled files"
    )

    # ── Preamble 1: detect blind spots (Decision 3.16, Invariant M3) ─────────
    blind_spots = detect_blind_spots(state["crawled_files"], state["global_inbox"])
    blind_spot_block = ""
    if blind_spots:
        blind_spot_block = (
            "\n\n## ⚠️ Coverage Gaps Detected\n"
            "The following files produced no extraction records and are excluded from the analysis:\n"
            + "\n".join(f"- `{f}`" for f in blind_spots)
            + "\n"
        )
        print(f"[master_round_table_node] Blind spots detected: {blind_spots}")

    # ── Preamble 2: compress inbox (Decision 3.10, Invariant M2) ─────────────
    records_for_synthesis, truncation_warning = compress_inbox(state["global_inbox"])

    # ── Synthesis prompt assembly ─────────────────────────────────────────────
    inbox_payload = json.dumps(
        [r.model_dump() for r in records_for_synthesis],
        indent=2,
    )
    synthesis_prompt = (
        blind_spot_block
        + truncation_warning
        + f"\n\nTotal extraction records: {len(records_for_synthesis)}\n"
        + f"Files analyzed: {list(state['summary_store'].keys())}\n\n"
        + "EXTRACTION RECORDS:\n"
        + inbox_payload
    )

    # ── Single-shot synthesis (Decision 3.10, Invariant M1) ──────────────────
    response = await llm.ainvoke([
        {"role": "system", "content": SYNTHESIS_SYSTEM_PROMPT},
        {"role": "user", "content": synthesis_prompt},
    ])

    # Extract text content from AIMessage (handles both str and list content)
    content = response.content
    if isinstance(content, str):
        report = content
    elif isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict) and "text" in part:
                parts.append(part["text"])
        report = "".join(parts)
    else:
        report = str(content)

    print(f"[master_round_table_node] Synthesis complete: {len(report)} characters")
    return {"master_risk_report": report}


# ── Conditional Edge: document dispatcher ─────────────────────────────────────

def dispatch_documents(state: ParentState) -> List[Send]:
    """
    After directory_crawler completes, dispatch one process_document node per file.
    Re-reads file content here so crawled_files stays as List[str] per spec.
    """
    directory = Path(state["directory_path"])
    sends = []
    for filename in state["crawled_files"]:
        file_path = directory / filename
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception as e:
            print(f"[dispatch_documents] Could not re-read {filename}: {e}")
            continue
        sends.append(
            Send("process_document", {
                "source_material": content,
                "file_name": filename,
            })
        )
    print(f"[dispatch_documents] Dispatching {len(sends)} document sub-graphs")
    return sends


# ── Graph Construction ────────────────────────────────────────────────────────

_builder = StateGraph(ParentState)

_builder.add_node("directory_crawler", directory_crawler)
_builder.add_node("process_document", process_document)
_builder.add_node("master_round_table_node", master_round_table_node)

_builder.add_edge(START, "directory_crawler")
_builder.add_conditional_edges("directory_crawler", dispatch_documents, ["process_document"])
_builder.add_edge("process_document", "master_round_table_node")
_builder.add_edge("master_round_table_node", END)

graph = _builder.compile()


# ── Run Function ──────────────────────────────────────────────────────────────

async def run_graph(directory_path: str) -> str:
    """
    Invokes the compiled graph with max_concurrency=50 (Invariant I1, Decision 3.4).
    Never asyncio.run() — caller must use nest_asyncio + get_event_loop().run_until_complete()
    from Streamlit (Invariant I2, Decision 3.11).
    """
    inputs: ParentState = {
        "directory_path": str(directory_path),
        "summary_store": {},
        "crawled_files": [],
        "global_inbox": [],
        "master_risk_report": "",
    }
    config = {"max_concurrency": 50}
    result = await graph.ainvoke(inputs, config=config)
    return result.get("master_risk_report", "No report generated.")
