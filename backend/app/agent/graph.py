"""LangGraph workflow: classify → fan-out analyze → aggregate → rewrite.

Graph shape:
    classify ─▶ fanout (Send per file) ─▶ analyze_file × N ─▶ aggregate ─▶ rewrite ─▶ END
"""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from app.agent.nodes import (
    aggregate_node,
    analyze_file_node,
    classify_node,
    rewrite_node,
)
from app.agent.state import ReviewState


def _fanout(state: ReviewState) -> list[Send]:
    files = state["pr"].files
    # skip removed files / empty patches
    sends: list[Send] = []
    for f in files:
        if f.status == "removed" or not (f.patch or "").strip():
            continue
        sends.append(
            Send(
                "analyze_file",
                {
                    "filename": f.filename,
                    "patch": f.patch,
                    "status": f.status,
                },
            )
        )
    return sends


def _aggregate_entry(state: ReviewState) -> dict[str, Any]:
    # aggregate_node expects full state; thin wrapper for clarity
    return aggregate_node(state)


def _finalize(state: ReviewState) -> dict[str, Any]:
    # comments reducer already holds per-file findings; final list lives in
    # final_comments (written by aggregate, polished by rewrite).
    # Don't touch "comments" here to avoid duplicating via the add-reducer.
    return {"progress": ["done"]}


def build_graph():
    builder = StateGraph(ReviewState)
    builder.add_node("classify", classify_node)
    builder.add_node("analyze_file", analyze_file_node)
    builder.add_node("aggregate", _aggregate_entry)
    builder.add_node("rewrite", rewrite_node)
    builder.add_node("finalize", _finalize)

    builder.add_edge(START, "classify")
    builder.add_conditional_edges("classify", _fanout, ["analyze_file"])
    builder.add_edge("analyze_file", "aggregate")
    builder.add_edge("aggregate", "rewrite")
    builder.add_edge("rewrite", "finalize")
    builder.add_edge("finalize", END)
    return builder.compile()


_graph = None


def get_graph():
    global _graph
    if _graph is None:
        _graph = build_graph()
    return _graph
