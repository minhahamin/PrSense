"""실제 오픈소스 PR로 파이프라인을 테스트하는 스크립트.

사용법:
    cd backend
    set MOCK_LLM=true            # (Windows) API 키 없이 휴리스틱으로 실행
    python ../eval/test_real_prs.py --repo psf/requests --pr 1234
    python ../eval/test_real_prs.py --sample   # 내장 샘플 diff로 오프라인 실행

실제 GitHub API를 쓰려면 GITHUB_TOKEN과 OPENAI_API_KEY를 .env에 설정하세요.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from app.schemas import PRContext  # noqa: E402
from app.services.review_service import ReviewService  # noqa: E402

SAMPLE_PR = {
    "repo": "demo/app",
    "pr_number": 7,
    "title": "Add login + fix payment validation",
    "body": "로그인 추가 및 결제 검증 수정",
    "base_sha": "base",
    "head_sha": "head",
    "files": [
        {
            "filename": "app/auth.py",
            "status": "modified",
            "additions": 12,
            "deletions": 2,
            "patch": (
                "@@ -10,6 +10,12 @@ def login(user):\n"
                "     token = make_token(user)\n"
                "+    password = \"hardcoded-secret-123\"\n"
                "+    print(\"debug login\", user)\n"
                "     try:\n"
                "         verify(token)\n"
                "-    except AuthError:\n"
                "+    except:\n"
                "+        pass\n"
                "     return token\n"
                "+# TODO: rate limit 추가 필요\n"
            ),
        },
        {
            "filename": "app/payments.py",
            "status": "modified",
            "additions": 5,
            "deletions": 1,
            "patch": (
                "@@ -1,4 +1,8 @@ def charge(amount):\n"
                "+    if amount > 0:\n"
                "+        process(amount)  # this line is intentionally way too long " + "x" * 90 + "\n"
                "     return True\n"
            ),
        },
    ],
}


async def run(pr_ctx: PRContext) -> dict:
    service = ReviewService()
    rec = service.create_run(pr_ctx)
    # run to completion (consume stream internally via events list)
    await service.run_review_stream(rec, pr_ctx)
    # drain queue leftovers
    while not rec._queue.empty():
        rec._queue.get_nowait()
    assert rec.result is not None, f"run failed: {rec.error}"
    return rec.result.model_dump()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default="")
    ap.add_argument("--pr", type=int, default=0)
    ap.add_argument("--sample", action="store_true")
    ap.add_argument("--out", default="eval/last_result.json")
    args = ap.parse_args()

    os.environ.setdefault("MOCK_LLM", "true")

    if args.sample or not args.repo:
        pr_ctx = PRContext(**SAMPLE_PR)
    else:
        from app.github_client import fetch_pr_context

        pr_ctx = fetch_pr_context(args.repo, args.pr)

    result = asyncio.run(run(pr_ctx))
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"✅ {pr_ctx.repo}#{pr_ctx.pr_number}: "
          f"{len(result['comments'])} findings, "
          f"risk={result['classification']['risk_level']}, "
          f"rec={result['recommendation']}")
    print(f"   saved → {args.out}")


if __name__ == "__main__":
    main()
