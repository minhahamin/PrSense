"""LangGraph state definition."""

from __future__ import annotations

import operator
from typing import Annotated, TypedDict

from app.schemas import PRClassification, PRContext, ReviewComment


class ReviewState(TypedDict, total=False):
    pr: PRContext
    classification: PRClassification
    # fan-out results: each analyze_file appends via reducer
    comments: Annotated[list[ReviewComment], operator.add]
    # aggregate/rewrite write the deduplicated final list here (plain overwrite)
    final_comments: list[ReviewComment]
    # progress events pushed to SSE subscribers (node name strings)
    progress: Annotated[list[str], operator.add]
    recommendation: str
    summary_card: dict
