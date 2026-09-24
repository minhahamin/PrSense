"""GitHub API client (PyGithub + httpx for diffs) and posting helpers."""

from __future__ import annotations

import base64
import hashlib
import hmac

import httpx
from github import Github
from github.PullRequest import PullRequest

from app.config import get_settings
from app.schemas import PRContext, PRFileDiff, ReviewComment


def verify_webhook_signature(payload: bytes, signature: str | None) -> bool:
    """Validate X-Hub-Signature-256. Empty secret config → accept (dev)."""
    secret = get_settings().github_webhook_secret
    if not secret or secret == "change-me":
        return True
    if not signature or not signature.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest("sha256=" + expected, signature)


def _gh() -> Github:
    return Github(get_settings().github_token)


def fetch_pr_context(repo: str, pr_number: int) -> PRContext:
    """Fetch PR metadata + per-file unified diffs."""
    gh = _gh()
    repo_obj = gh.get_repo(repo)
    pr: PullRequest = repo_obj.get_pull(pr_number)

    files: list[PRFileDiff] = []
    for f in pr.get_files():
        files.append(
            PRFileDiff(
                filename=f.filename,
                status=f.status or "modified",
                additions=f.additions or 0,
                deletions=f.deletions or 0,
                patch=f.patch or "",
                previous_filename=getattr(f, "previous_filename", None),
            )
        )
    return PRContext(
        repo=repo,
        pr_number=pr_number,
        title=pr.title or "",
        body=pr.body or "",
        base_sha=pr.base.sha,
        head_sha=pr.head.sha,
        files=files,
    )


def post_inline_comments(
    repo: str, pr_number: int, comments: list[ReviewComment], head_sha: str
) -> int:
    """Create a review with inline comments. Returns # posted."""
    if not comments:
        return 0
    gh = _gh()
    pr = gh.get_repo(repo).get_pull(pr_number)
    body = f"PrSense 자동 리뷰 — {len(comments)}건의 지적을 남겼습니다."
    gh_comments = [
        {
            "path": c.file,
            "line": c.line,
            "side": "RIGHT",
            "body": _format_comment(c),
        }
        for c in comments
    ]
    # PyGithub: create_review(commit, body, event, comments)
    pr.create_review(head_sha, body, "COMMENT", gh_comments)
    return len(gh_comments)


def _format_comment(c: ReviewComment) -> str:
    from app.config import get_settings as _gs

    low = c.confidence < _gs().confidence_threshold
    prefix = "🔍 **확인 필요** (낮은 신뢰도)\n\n" if low else ""
    sev = {"critical": "🔴", "warning": "🟡", "nit": "⚪"}.get(c.severity.value, "")
    fix = f"\n\n**제안:**\n```suggestion\n{c.suggested_fix}\n```" if c.suggested_fix else ""
    return (
        f"{prefix}{sev} **[{c.severity.value} · {c.category.value}]** "
        f"(신뢰도 {c.confidence:.2f})\n\n{c.comment}{fix}\n\n<sub>— PrSense 🤖</sub>"
    )


def fetch_file_at_ref(repo: str, path: str, ref: str) -> str:
    """Raw file content for RAG seeding (best-effort)."""
    token = get_settings().github_token
    url = f"https://api.github.com/repos/{repo}/contents/{path}?ref={ref}"
    headers = {"Accept": "application/vnd.github.raw"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    r = httpx.get(url, headers=headers, timeout=30)
    if r.status_code == 200:
        return r.text
    # fallback: base64 json
    headers["Accept"] = "application/vnd.github+json"
    r = httpx.get(url, headers=headers, timeout=30)
    if r.status_code == 200 and "content" in r.json():
        return base64.b64decode(r.json()["content"]).decode("utf-8", "ignore")
    return ""
