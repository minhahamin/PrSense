"""Orchestration: run the LangGraph, stream progress via SSE, persist to DB.

Design notes:
- Live state lives in memory (`runs`: run_id → RunRecord) because SSE
  subscribers need the Oj queue + append-only events list.
- Every run is also persisted to Postgres (Railway) / SQLite (local fallback)
  so history survives restarts. DB failures never break a review — they only
  log a warning and the run continues memory-only.
- Progress events are plain dicts: "classify:done", "analyze:<file>:done", ...
  Frontend maps them to the 4-step indicator.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field

import structlog
from sqlalchemy import desc, select

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
    title: str = ""
    created_at: float = field(default_factory=time.time)
    _queue: asyncio.Queue = field(default_factory=asyncio.Queue, repr=False)


class ReviewService:
    def __init__(self):
        self.runs: dict[str, RunRecord] = {}

    # -- lifecycle -------------------------------------------------- #
    def create_run(self, pr: PRContext) -> RunRecord:
        run_id = f"{pr.repo.replace('/', '_')}#{pr.pr_number}-{uuid.uuid4().hex[:8]}"
        rec = RunRecord(run_id=run_id, repo=pr.repo, pr_number=pr.pr_number,
                        title=pr.title or "")
        self.runs[run_id] = rec
        return rec

    def get(self, run_id: str) -> RunRecord | None:
        """Memory only (sync, for hot paths). Use get_or_load for history."""
        return self.runs.get(run_id)

    async def get_or_load(self, run_id: str) -> RunRecord | None:
        """Memory first, then DB (reconstructed records are re-cached)."""
        rec = self.runs.get(run_id)
        if rec is not None:
            return rec
        try:
            from app.db import get_session_factory
            from app.models import ReviewRun

            async with get_session_factory()() as session:
                row = await session.get(ReviewRun, run_id)
                if row is None:
                    return None
                rec = self._from_row(row)
                self.runs[run_id] = rec
                return rec
        except Exception:  # noqa: BLE001
            log.warning("db load failed", run_id=run_id, exc_info=True)
            return None

    async def latest_for_pr(self, repo: str, pr_number: int) -> RunRecord | None:
        mem_cands = [r for r in self.runs.values()
                     if r.repo == repo and r.pr_number == pr_number]
        best = max(mem_cands, key=lambda r: r.created_at) if mem_cands else None
        try:
            from app.db import get_session_factory
            from app.models import ReviewRun

            async with get_session_factory()() as session:
                q = (
                    select(ReviewRun)
                    .where(ReviewRun.repo == repo, ReviewRun.pr_number == pr_number)
                    .order_by(desc(ReviewRun.created_at))
                    .limit(1)
                )
                row = (await session.execute(q)).scalars().first()
                if row is not None:
                    db_rec = self._from_row(row)
                    db_ts = db_rec.created_at
                    if best is None or db_ts > best.created_at:
                        self.runs[db_rec.run_id] = db_rec
                        return db_rec
        except Exception:  # noqa: BLE001
            log.warning("db latest_for_pr failed", repo=repo, pr=pr_number, exc_info=True)
        return best

    async def list_prs(self) -> list[dict]:
        """Distinct PRs, memory + DB merged (newest run per repo/pr wins)."""
        merged: dict[tuple[str, int], RunRecord] = {}
        for r in self.runs.values():
            key = (r.repo, r.pr_number)
            if key not in merged or r.created_at > merged[key].created_at:
                merged[key] = r
        try:
            from app.db import get_session_factory
            from app.models import ReviewRun

            async with get_session_factory()() as session:
                q = select(ReviewRun).order_by(desc(ReviewRun.created_at)).limit(200)
                for row in (await session.execute(q)).scalars():
                    key = (row.repo, row.pr_number)
                    if key in merged:
                        continue
                    merged[key] = self._from_row(row)
        except Exception:  # noqa: BLE001
            log.warning("db list_prs failed", exc_info=True)
        out = []
        for (repo, num), r in sorted(merged.items(),
                                     key=lambda kv: kv[1].created_at, reverse=True):
            res = r.result
            out.append({
                "repo": repo,
                "pr_number": num,
                "run_id": r.run_id,
                "status": r.status,
                "title": (r.title or (res.classification.summary[:80] if res else "")),
                "risk_level": res.classification.risk_level.value if res else None,
                "comment_count": len(res.comments) if res else 0,
                "recommendation": res.recommendation if res else None,
            })
        return out

    # -- persistence -------------------------------------------------- #
    async def _save(self, rec: RunRecord) -> None:
        """Upsert run row. Never raises (DB outage must not kill reviews)."""
        try:
            from app.db import get_session_factory
            from app.models import ReviewRun

            async with get_session_factory()() as session:
                row = await session.get(ReviewRun, rec.run_id)
                payload = {
                    "repo": rec.repo,
                    "pr_number": rec.pr_number,
                    "title": rec.title,
                    "status": rec.status,
                    "events": list(rec.events),
                    "result": rec.result.model_dump() if rec.result else None,
                    "error": rec.error,
                }
                if row is None:
                    session.add(ReviewRun(run_id=rec.run_id, **payload))
                else:
                    for k, v in payload.items():
                        setattr(row, k, v)
                await session.commit()
        except Exception:  # noqa: BLE001
            log.warning("db save failed", run_id=rec.run_id, exc_info=True)

    @staticmethod
    def _from_row(row) -> RunRecord:
        result = None
        if row.result:
            try:
                result = FinalReviewResponse.model_validate(row.result)
            except Exception:  # noqa: BLE001
                log.warning("dropping corrupt result", run_id=row.run_id, exc_info=True)
        ts = row.created_at.timestamp() if row.created_at else time.time()
        return RunRecord(
            run_id=row.run_id, repo=row.repo, pr_number=row.pr_number,
            status=row.status or "running", events=list(row.events or []),
            result=result, error=row.error or "", title=row.title or "",
            created_at=ts,
        )

    # -- execution -------------------------------------------------- #
    async def run_review_stream(self, rec: RunRecord, pr: PRContext):
        """Run graph with astream, pushing node progress into rec._queue + events."""
        q = rec._queue
        graph = get_graph()
        await q.put({"type": "started", "run_id": rec.run_id})
        rec.events.append({"type": "started"})
        await self._save(rec)  # persist "running" row early for history

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
            await self._save(rec)
        except Exception as e:  # noqa: BLE001
            log.exception("review run failed", run_id=rec.run_id)
            rec.status = "error"
            rec.error = str(e)
            await q.put({"type": "error", "message": str(e)})
            await self._save(rec)
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
