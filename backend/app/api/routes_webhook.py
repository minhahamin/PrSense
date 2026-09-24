"""POST /webhook/github — handles pull_request opened/synchronize."""

from __future__ import annotations

import asyncio
import json

import structlog
from fastapi import APIRouter, BackgroundTasks, Header, Request
from fastapi.responses import JSONResponse

from app import github_client as gh
from app.config import get_settings
from app.schemas import PRContext, WebhookAck
from app.services.review_service import get_service

router = APIRouter()
log = structlog.get_logger()


@router.post("/github", response_model=WebhookAck)
async def github_webhook(
    request: Request,
    background: BackgroundTasks,
    x_hub_signature_256: str | None = Header(default=None),
    x_github_event: str | None = Header(default=None),
):
    raw = await request.body()
    if not gh.verify_webhook_signature(raw, x_hub_signature_256):
        return JSONResponse(status_code=401, content={"detail": "bad signature"})

    try:
        payload = json.loads(raw.decode())
    except ValueError:
        return JSONResponse(status_code=400, content={"detail": "invalid json"})

    if x_github_event == "ping":
        return WebhookAck(ok=True, run_id="ping", message="pong")

    if x_github_event != "pull_request":
        return WebhookAck(ok=True, run_id="ignored", message=f"ignored event {x_github_event}")

    action = payload.get("action")
    if action not in ("opened", "synchronize", "reopened"):
        return WebhookAck(ok=True, run_id="ignored", message=f"ignored action {action}")

    repo = payload["repository"]["full_name"]
    allowed = get_settings().allowed_repo_set
    if allowed and repo not in allowed:
        return WebhookAck(ok=True, run_id="ignored", message=f"repo {repo} not allowed")

    pr_number = int(payload["number"])
    log.info("webhook pr event", repo=repo, pr=pr_number, action=action)

    try:
        pr_ctx = gh.fetch_pr_context(repo, pr_number)
    except Exception as e:  # noqa: BLE001
        log.exception("fetch pr failed")
        return JSONResponse(status_code=502, content={"detail": f"fetch failed: {e}"})

    service = get_service()
    rec = service.create_run(pr_ctx)
    # run in background so webhook ACKs fast
    background.add_task(service.run_review_stream, rec, pr_ctx)
    # drain queue in background too (avoids unbounded growth when nobody listens)
    background.add_task(_drain, rec.run_id)
    return WebhookAck(ok=True, run_id=rec.run_id)


async def _drain(run_id: str):
    service = get_service()
    rec = service.get(run_id)
    if rec is None:
        return
    # consume until end so producers never block; SSE subscribers get own replay
    while True:
        evt = await rec._queue.get()
        if evt.get("type") == "end":
            break


@router.post("/review/{repo:path}/{pr_number:int}", response_model=WebhookAck)
async def trigger_review_manual(repo: str, pr_number: int, background: BackgroundTasks,
                                body: dict | None = None):
    """Manual trigger (useful for eval + frontend 'Re-review' button).

    Accepts optional {"files": [...], "title": ..., "body": ...} to run fully
    offline without hitting the GitHub API.
    """
    service = get_service()
    if body and "files" in body:
        pr_ctx = PRContext(
            repo=repo,
            pr_number=pr_number,
            title=body.get("title", ""),
            body=body.get("body", ""),
            files=body["files"],
        )
    else:
        try:
            pr_ctx = gh.fetch_pr_context(repo, pr_number)
        except Exception as e:  # noqa: BLE001
            return JSONResponse(status_code=502, content={"detail": f"fetch failed: {e}"})
    rec = service.create_run(pr_ctx)
    background.add_task(service.run_review_stream, rec, pr_ctx)
    background.add_task(_drain, rec.run_id)
    return WebhookAck(ok=True, run_id=rec.run_id)
