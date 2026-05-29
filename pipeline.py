"""
PrismForge AI v4 — Dynamic Semantic Topology (DST) Engine
Spec-compliant implementation: LangGraph sub-graphs per document, workers dispatched
via Send from route_matrix_to_workers conditional edge.

Architecture:
  Parent: directory_crawler → dispatch_subgraphs → [doc_pipeline × N] → master_round_table_node
  Sub-graph (per file): router_node → chunk_node → route_matrix_to_workers
                        → [extraction_worker × chunks×lenses] → handoff_node
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
    semantic_summary: str  # stamped at dispatch time (Invariant W2)


# ── LLM Singletons (Invariant S1) ────────────────────────────────────────────
# All four instantiated once at module scope — never inside any node or worker.

router_llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash")
structured_router = router_llm.with_structured_output(RouterOutput)

llm = ChatAnthropic(model="claude-sonnet-4-20250514")
structured_llm = llm.with_structured_output(UniversalForm)

# Chunker singleton (Decision 3.5, Invariant C1): chunk_size is characters, not tokens
splitter = RecursiveCharacterTextSplitter(chunk_size=4000, chunk_overlap=800)


# ── State Schemas ─────────────────────────────────────────────────────────────

class ParentState(TypedDict):
    directory_path: str
    crawled_files: List[str]                                                    # no reducer — single write (Invariant P2)
    summary_store: Annotated[Dict[str, str], lambda a, b: {**a, **b}]          # merge reducer (Invariant P1)
    global_inbox: Annotated[List[ExtractionRecord], add]                        # append reducer
    master_risk_report: str


class DocumentSubState(TypedDict):
    # ── Internal processing fields ──────────────────────────────────────────
    source_material: str
    file_name: str
    semantic_summary: str
    dynamic_topology: List[str]
    document_chunks: List[str]
    local_inbox: Annotated[List[ExtractionRecord], add]                         # workers write here
    # ── Output fields ────────────────────────────────────────────────────────
    # Written by handoff_node. Keys overlap with ParentState so LangGraph
    # propagates them to the parent when the sub-graph completes. Reducers
    # match ParentState to ensure parallel sub-graphs accumulate correctly.
    global_inbox: Annotated[List[ExtractionRecord], add]                        # handoff maps local_inbox → here
    summary_store: Annotated[Dict[str, str], lambda a, b: {**a, **b}]          # handoff maps file_name:summary → here
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
Use implied_liability_score 1-10 where 9-10 = existential/critical, 7-8 = major,
5-6 = significant, 3-4 = moderate, 1-2 = minor."""

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
(Explicitly name every contradiction identified across documents. Quote both sides.
Explain the legal/financial consequence.)

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
- Be specific, technical, and legally precise"""


# ── Pure Functions ────────────────────────────────────────────────────────────

def detect_blind_spots(
    crawled_files: List[str],
    global_inbox: List[ExtractionRecord]
) -> List[str]:
    """Returns filenames in crawled_files with zero extraction records. Decision 3.16."""
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


# ── Sub-graph Nodes ───────────────────────────────────────────────────────────

async def router_node(state: DocumentSubState) -> Dict[str, Any]:
    """
    Single combined LLM call per document (Decision 3.15, Invariant R1).
    Emits semantic_summary and dynamic_topology into DocumentSubState atomically.
    """
    result: RouterOutput = await structured_router.ainvoke([
        {"role": "system", "content": ROUTER_SYSTEM_PROMPT},
        {"role": "user", "content": state["source_material"]},
    ])
    print(
        f"[router_node] {state['file_name']}: "
        f"{len(result.dynamic_topology)} lenses: {result.dynamic_topology}"
    )
    return {
        "semantic_summary": result.semantic_summary,
        "dynamic_topology": result.dynamic_topology,
    }


def chunk_node(state: DocumentSubState) -> Dict[str, Any]:
    """Chunks source_material into document_chunks (Decision 3.5, Invariant C1)."""
    chunks = splitter.split_text(state["source_material"])
    print(f"[chunk_node] {state['file_name']}: {len(chunks)} chunks")
    return {"document_chunks": chunks}


async def extraction_worker(payload_dict: Dict[str, Any]) -> Dict[str, Any]:
    """
    Exactly one parameter (payload_dict). No state parameter — LangGraph does not
    inject parent/sub-graph state into Send-dispatched nodes (Invariant X1).
    Entire body wrapped in try/except (Invariant X4) — any failure returns empty list.
    Uses await ainvoke (Invariant X3). Returns ExtractionRecord, not raw dict (Invariant X5).
    """
    try:
        payload = WorkerPayload(**payload_dict)
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
        return {"local_inbox": []}  # Invariant X4: never crashes the pool


def handoff_node(sub_state: DocumentSubState) -> Dict[str, Any]:
    """
    Single handoff per sub-graph, fires after all workers complete (Invariants H1, H2).
    Writes both summary_store and global_inbox in one atomic return dict (Decision 3.1, 3.3).
    Keys overlap with ParentState — LangGraph propagates them via parent reducers.
    """
    return {
        "global_inbox": sub_state["local_inbox"],
        "summary_store": {sub_state["file_name"]: sub_state["semantic_summary"]},
    }


# ── Conditional Edge: Fan-Out Matrix (Decision 3.7) ──────────────────────────

def route_matrix_to_workers(state: DocumentSubState) -> List[Send]:
    """
    Single state: DocumentSubState parameter only (Invariant E1).
    Reads semantic_summary from sub-graph state — always present because router_node
    ran earlier in the same sub-graph execution (Invariant E2).
    Emits Send("extraction_worker", primitive_dict) — never a Pydantic instance (Invariant E3).
    Stamps semantic_summary into every WorkerPayload at dispatch time (Invariant E4).
    """
    execution_matrix = []
    summary = state.get("semantic_summary", "")  # written by router_node; always present here
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
                Send("extraction_worker", worker_config.model_dump())  # primitive dict (Invariant W1)
            )
    print(
        f"[route_matrix_to_workers] {state['file_name']}: "
        f"dispatching {len(execution_matrix)} workers "
        f"({len(state['document_chunks'])} chunks × {len(state['dynamic_topology'])} lenses)"
    )
    return execution_matrix


# ── Parent Graph Nodes ────────────────────────────────────────────────────────

def directory_crawler(state: ParentState) -> Dict[str, Any]:
    """
    Defensive read loop — skips unreadable/binary files silently (Decision 3.6).
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


async def master_round_table_node(state: ParentState) -> Dict[str, Any]:
    """
    Terminal synthesis node (Decisions 3.10, 3.16):
    Preamble: detect_blind_spots() → compress_inbox()
    Synthesis: single-shot long-context Markdown report (Invariant M1).
    Synthesis receives compressed records, never raw global_inbox (Invariant M2).
    detect_blind_spots is a Python filter here, not a graph node (Invariant M3).
    """
    print(
        f"[master_round_table_node] Synthesizing: "
        f"{len(state['global_inbox'])} records from "
        f"{len(state['crawled_files'])} files"
    )

    # Preamble 1: detect blind spots (Decision 3.16)
    blind_spots = detect_blind_spots(state["crawled_files"], state["global_inbox"])
    blind_spot_block = ""
    if blind_spots:
        blind_spot_block = (
            "\n\n## ⚠️ Coverage Gaps Detected\n"
            "The following files produced no extraction records:\n"
            + "\n".join(f"- `{f}`" for f in blind_spots)
            + "\n"
        )
        print(f"[master_round_table_node] Blind spots: {blind_spots}")

    # Preamble 2: compress inbox (Decision 3.10)
    records_for_synthesis, truncation_warning = compress_inbox(state["global_inbox"])

    inbox_payload = json.dumps(
        [r.model_dump() for r in records_for_synthesis],
        indent=2,
    )
    synthesis_prompt = (
        blind_spot_block
        + truncation_warning
        + f"\n\nTotal records: {len(records_for_synthesis)}\n"
        + f"Files analyzed: {list(state['summary_store'].keys())}\n\n"
        + "EXTRACTION RECORDS:\n"
        + inbox_payload
    )

    response = await llm.ainvoke([
        {"role": "system", "content": SYNTHESIS_SYSTEM_PROMPT},
        {"role": "user", "content": synthesis_prompt},
    ])
    content = response.content
    if isinstance(content, str):
        report = content
    elif isinstance(content, list):
        report = "".join(
            p if isinstance(p, str) else p.get("text", "")
            for p in content
        )
    else:
        report = str(content)

    print(f"[master_round_table_node] Report: {len(report)} characters")
    return {"master_risk_report": report}


# ── Conditional Edge: Sub-graph Dispatcher ───────────────────────────────────

def dispatch_subgraphs(state: ParentState) -> List[Send]:
    """
    Dispatches one doc_pipeline sub-graph per crawled file via Send.
    Passes a fully initialized DocumentSubState so the sub-graph starts clean.
    """
    directory = Path(state["directory_path"])
    sends = []
    for filename in state["crawled_files"]:
        file_path = directory / filename
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception as e:
            print(f"[dispatch_subgraphs] Could not re-read {filename}: {e}")
            continue
        sends.append(Send("doc_pipeline", {
            "source_material": content,
            "file_name": filename,
            "semantic_summary": "",
            "dynamic_topology": [],
            "document_chunks": [],
            "local_inbox": [],
            "global_inbox": [],
            "summary_store": {},
        }))
    print(f"[dispatch_subgraphs] Dispatching {len(sends)} sub-graphs")
    return sends


# ── Sub-graph Compilation ─────────────────────────────────────────────────────
# StateGraph(DocumentSubState): internal nodes communicate through DocumentSubState.
# global_inbox and summary_store are output fields that overlap with ParentState —
# LangGraph propagates them to the parent via the parent's reducers when the sub-graph ends.

_sub_builder = StateGraph(DocumentSubState)

_sub_builder.add_node("router_node", router_node)
_sub_builder.add_node("chunk_node", chunk_node)
_sub_builder.add_node("extraction_worker", extraction_worker)
_sub_builder.add_node("handoff_node", handoff_node)

_sub_builder.add_edge(START, "router_node")
_sub_builder.add_edge("router_node", "chunk_node")
_sub_builder.add_conditional_edges("chunk_node", route_matrix_to_workers, ["extraction_worker"])
_sub_builder.add_edge("extraction_worker", "handoff_node")
_sub_builder.add_edge("handoff_node", END)

doc_pipeline = _sub_builder.compile()


# ── Parent Graph Construction ─────────────────────────────────────────────────

_builder = StateGraph(ParentState)

_builder.add_node("directory_crawler", directory_crawler)
_builder.add_node("doc_pipeline", doc_pipeline)       # compiled sub-graph as a node
_builder.add_node("master_round_table_node", master_round_table_node)

_builder.add_edge(START, "directory_crawler")
_builder.add_conditional_edges("directory_crawler", dispatch_subgraphs, ["doc_pipeline"])
_builder.add_edge("doc_pipeline", "master_round_table_node")
_builder.add_edge("master_round_table_node", END)

graph = _builder.compile()


# ── Run Function ──────────────────────────────────────────────────────────────

async def run_graph(directory_path: str) -> str:
    """
    Invokes the compiled graph with max_concurrency=50 (Invariant I1, Decision 3.4).
    Caller must use nest_asyncio + get_event_loop().run_until_complete() from Streamlit
    (Invariant I2, Decision 3.11). Never asyncio.run() inside Streamlit.
    """
    inputs: ParentState = {
        "directory_path": str(directory_path),
        "crawled_files": [],
        "summary_store": {},
        "global_inbox": [],
        "master_risk_report": "",
    }
    config = {"max_concurrency": 50}
    result = await graph.ainvoke(inputs, config=config)
    return result.get("master_risk_report", "No report generated.")
