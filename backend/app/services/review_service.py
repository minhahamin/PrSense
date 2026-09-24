"""Orchestration: run the LangGraph, stream progress via SSE, keep in-memory store.

Design notes:
- `runs`: run_id → RunRecord (status, events, result). In-memory on purpose
  (portfolio scope); swap for Redis/DB in production.
- Progress events are plain strings: "classify:done", "analyze:<file>:done", ...
  Frontend maps them to the 4-step indicator.
- `run_review_stream` is an async generator yielding SSE-ready dicts.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field

import structlog

from app.agent.graph import get_graph
from app.config import get_settings
from app.schemas import (
    AggregatedReview,
    FinalReviewResponse,
    PRClassification,
    PRContext,
)

log = structlog.get_logger()


@dataclass
class RunRecord:
    run_id: str
    repo: str
    pr_number: int
    status: str = "running"  # running | done | error
    events: list[dict] = field(default_factory=list)
    result: FinalReviewResponse | None = None
    error: str = ""
    created_at: float = field(default_factory=time.time)
    _queue: asyncio.Queue = field(default_factory=asyncio.Queue, repr=False)


class ReviewService:
    def __init__(self):
        self.runs: dict[str, RunRecord] = {}

    # -- lifecycle -------------------------------------------------- #
    def create_run(self, pr: PRContext) -> RunRecord:
        run_id = f"{pr.repo.replace('/', '_')}#{pr.pr_number}-{uuid.uuid4().hex[:8]}"
        rec = RunRecord(run_id=run_id, repo=pr.repo, pr_number=pr.pr_number)
        self.runs[run_id] = rec
        return rec

    def get(self, run_id: str) -> RunRecord | None:
        return self.runs.get(run_id)

    def latest_for_pr(self, repo: str, pr_number: int) -> RunRecord | None:
        cands = [r for r in self.runs.values()
                 if r.repo == repo and r.pr_number == pr_number]
        return max(cands, key=lambda r: r.created_at) if cands else None

    def list_prs(self) -> list[dict]:
        """Distinct PRs seen so far (for the list page)."""
        seen: dict[tuple[str, int], RunRecord] = {}
        for r in self.runs.values():
            key = (r.repo, r.pr_number)
            if key not in seen or r.created_at > seen[key].created_at:
                seen[key] = r
        out = []
        for (repo, num), r in sorted(seen.items(), key=lambda kv: kv[1].created_at, reverse=True):
            res = r.result
            out.append({
                "repo": repo,
                "pr_number": num,
                "run_id": r.run_id,
                "status": r.status,
                "title": getattr(res, "classification", None) and res.classification.summary[:80] or "",
                "risk_level": res.classification.risk_level.value if res else None,
                "comment_count": len(res.comments) if res else 0,
                "recommendation": res.recommendation if res else None,
            })
        return out

    # -- execution -------------------------------------------------- #
    async def run_review_stream(self, rec: RunRecord, pr: PRContext):
        """Run graph with astream, pushing node progress into rec._queue + events."""
        q = rec._queue
        graph = get_graph()
        await q.put({"type": "started", "run_id": rec.run_id})
        rec.events.append({"type": "started"})

        final_state: dict = {"comments": []}
        try:
            async for chunk in graph.astream(
                {"pr": pr}, stream_mode="updates"
            ):
                for node, payload in chunk.items():
                    if not isinstance(payload, dict):
                        continue
                    if node == "analyze_file":
                        # fan-out returns per-file progress entries
                        for p in payload.get("progress", []):
                            evt = {"type": "progress", "node": "analyze", "detail": p}
                            rec.events.append(evt)
                            await q.put(evt)
                    elif node in ("classify", "aggregate", "rewrite", "finalize"):
                        evt = {"type": "progress", "node": node, "detail": f"{node}:done"}
                        rec.events.append(evt)
                        await q.put(evt)
                    # reducer-aware merge: append lists, overwrite scalars
                    for k, v in payload.items():
                        if k == "comments" and isinstance(v, list):
                            final_state.setdefault("comments", []).extend(v)
                        elif k == "progress":
                            continue
                        else:
                            final_state[k] = v

            result = self._to_response(pr, final_state)
            rec.result = result
            rec.status = "done"
            evt = {"type": "result", "result": result.model_dump()}
            rec.events.append(evt)
            await q.put(evt)
        except Exception as e:  # noqa: BLE001
            log.exception("review run failed", run_id=rec.run_id)
            rec.status = "error"
            rec.error = str(e)
            await q.put({"type": "error", "message": str(e)})
        finally:
            await q.put({"type": "end"})

    def _to_response(self, pr: PRContext, state: dict) -> FinalReviewResponse:
        threshold = get_settings().confidence_threshold
        classification: PRClassification = state.get("classification") or PRClassification(
            change_type="mixed", risk_level="medium",
            summary=pr.title, focus_areas=[], reasoning="fallback",
        )
        # aggregate writes the deduped list to final_comments; fall back to
        # raw per-file comments if that's missing (e.g. partial failure).
        raw = state.get("final_comments") or state.get("comments", [])
        # dedupe defensively (graph already does)
        seen, dedup = set(), []
        for c in raw:
            key = (c.file, c.line, c.comment[:60])
            if key not in seen:
                seen.add(key)
                dedup.append(c)
        low = sum(1 for c in dedup if c.confidence < threshold)
        rec = state.get("recommendation", "comment")
        if rec not in ("approve", "comment", "request_changes"):
            rec = "comment"
        agg = AggregatedReview(
            classification=classification, comments=dedup, recommendation=rec  # type: ignore[arg-type]
        )
        return FinalReviewResponse(
            **agg.model_dump(), pr_number=pr.pr_number, repo=pr.repo,
            low_confidence_count=low,
        )


_service: ReviewService | None = None


def get_service() -> ReviewService:
    global _service
    if _service is None:
        _service = ReviewService()
    return _service
