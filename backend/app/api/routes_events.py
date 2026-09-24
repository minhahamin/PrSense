"""GET /events/{run_id} — SSE stream of graph progress + final result.

Design: subscribers poll the append-only rec.events list (no queue stealing),
so any number of frontend clients can attach at any time.
"""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter
from sse_starlette.sse import EventSourceResponse

from app.services.review_service import get_service

router = APIRouter()


@router.get("/{run_id}")
async def stream_events(run_id: str):
    service = get_service()
    rec = await service.get_or_load(run_id)

    async def generator():
        if rec is None:
            yield {"event": "error", "data": json.dumps({"message": "unknown run_id"})}
            return
        seen = 0
        while True:
            while seen < len(rec.events):
                evt = rec.events[seen]
                seen += 1
                yield {"event": evt.get("type", "message"), "data": json.dumps(evt, default=str)}
            if rec.status in ("done", "error"):
                yield {"event": "end", "data": "{}"}
                break
            await asyncio.sleep(0.3)

    return EventSourceResponse(generator())
