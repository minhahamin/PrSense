"""PR list / detail / publish endpoints (used by the frontend)."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app import github_client as gh
from app.services.review_service import get_service

router = APIRouter()


@router.get("/")
async def list_prs():
    return {"prs": await get_service().list_prs()}


@router.get("/{repo:path}/{pr_number:int}")
async def pr_detail(repo: str, pr_number: int):
    service = get_service()
    rec = await service.latest_for_pr(repo, pr_number)
    if rec is None:
        return JSONResponse(
            status_code=404,
            content={"detail": "no review yet", "status": "missing", "run_id": None},
        )
    # 실행 중에도 run_id/status는 반환 → 프론트가 새로고침 없이 SSE 구독 가능
    res = rec.result
    files = []  # frontend fetches diffs separately when needed
    return {
        "repo": repo,
        "pr_number": pr_number,
        "run_id": rec.run_id,
        "status": rec.status,
        "classification": res.classification.model_dump() if res else None,
        "comments": [c.model_dump() for c in res.comments] if res else [],
        "recommendation": res.recommendation if res else None,
        "low_confidence_count": res.low_confidence_count if res else 0,
        "files": files,
    }


@router.get("/{repo:path}/{pr_number:int}/diff")
async def pr_diff(repo: str, pr_number: int):
    """Return file diffs (patch text) for the diff viewer."""
    try:
        ctx = gh.fetch_pr_context(repo, pr_number)
    except Exception as e:  # noqa: BLE001
        return JSONResponse(status_code=502, content={"detail": f"fetch failed: {e}"})
    return {"repo": repo, "pr_number": pr_number, "files": [f.model_dump() for f in ctx.files]}


@router.post("/{repo:path}/{pr_number:int}/publish")
async def publish(repo: str, pr_number: int):
    service = get_service()
    rec = await service.latest_for_pr(repo, pr_number)
    if rec is None or rec.result is None:
        return JSONResponse(status_code=404, content={"detail": "no review to publish"})
    try:
        ctx = gh.fetch_pr_context(repo, pr_number)
        n = gh.post_inline_comments(repo, pr_number, rec.result.comments, ctx.head_sha)
    except Exception as e:  # noqa: BLE001
        return JSONResponse(status_code=502, content={"detail": f"publish failed: {e}"})
    return {"ok": True, "posted": n}
