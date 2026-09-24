"""Graph nodes: classify → analyze_file (fan-out) → aggregate → rewrite."""

from __future__ import annotations

import re
import time
from contextlib import contextmanager

import structlog
from pydantic import BaseModel, Field

from app.agent import prompts
from app.agent.llm import invoke_structured, is_mock_mode
from app.agent.state import ReviewState
from app.schemas import (
    AggregatedReview,
    FileReview,
    PRClassification,
    PRContext,
    ReviewComment,
)

log = structlog.get_logger()


@contextmanager
def _timed(node: str, detail: str = ""):
    t0 = time.time()
    try:
        yield
    finally:
        log.info("node done", node=node, detail=detail,
                 elapsed_s=round(time.time() - t0, 1))


# structured list wrappers (LangChain requires a single BaseModel)
class _FileReviewList(BaseModel):
    comments: list[ReviewComment] = Field(default_factory=list)


class _RewriteList(BaseModel):
    comments: list[ReviewComment] = Field(default_factory=list)


# ---------------------------------------------------------------- classify
def classify_node(state: ReviewState) -> dict:
    pr: PRContext = state["pr"]
    if is_mock_mode():
        return {"classification": _mock_classify(pr), "progress": ["classify:done"]}

    file_stats = "\n".join(
        f"- {f.filename} | {f.status} | +{f.additions} -{f.deletions}" for f in pr.files
    ) or "(no files)"
    excerpt = "\n".join(f.patch[:800] for f in pr.files[:5])[:4000]
    # invoke_structured: tool calling → JSON 폴백 (무료 모델 대응)
    with _timed("classify", pr.title[:60]):
        out: PRClassification = invoke_structured(
            PRClassification,
            [
                ("system", prompts.CLASSIFY_SYSTEM),
                (
                    "user",
                    prompts.CLASSIFY_USER.format(
                        title=pr.title, body=(pr.body or "")[:2000],
                        file_stats=file_stats, diff_excerpt=excerpt,
                    ),
                ),
            ],
        )
    return {"classification": out, "progress": ["classify:done"]}


def _mock_classify(pr: PRContext) -> PRClassification:
    from app.schemas import ChangeType, RiskLevel

    names = " ".join(f.filename for f in pr.files).lower()
    if "auth" in names or "migration" in names or "payment" in names:
        risk = RiskLevel.HIGH
    elif len(pr.files) > 5 or sum(f.additions for f in pr.files) > 300:
        risk = RiskLevel.MEDIUM
    else:
        risk = RiskLevel.LOW
    ctype = ChangeType.MIXED
    if all(f.filename.endswith(".md") for f in pr.files):
        ctype = ChangeType.DOCS
    elif all("test" in f.filename for f in pr.files):
        ctype = ChangeType.TEST
    return PRClassification(
        change_type=ctype,
        risk_level=risk,
        summary=f"'{pr.title}' — {len(pr.files)}개 파일 변경 (mock 분류).",
        focus_areas=[f.filename for f in pr.files[:5]],
        reasoning="mock: 휴리스틱 분류",
    )


# ------------------------------------------------------------- analyze file
def analyze_file_node(payload: dict) -> dict:
    """Called via Send() per file. Returns reducer-compatible {"comments": [...]}."""
    filename: str = payload["filename"]
    patch: str = payload.get("patch", "")[:6000]
    status: str = payload.get("status", "modified")

    if not patch.strip():
        return {"comments": [], "progress": [f"analyze:{filename}:done"]}

    # RAG context (import lazily to keep graph import light)
    from app.rag.indexer import format_rag_context, retrieve_related

    hits = retrieve_related(filename, patch)
    rag_context = format_rag_context(hits)

    if is_mock_mode():
        return {
            "comments": _mock_analyze(filename, patch),
            "progress": [f"analyze:{filename}:done"],
        }

    with _timed("analyze", filename):
        llm_out: _FileReviewList = invoke_structured(
            _FileReviewList,
            [
                ("system", prompts.ANALYZE_FILE_SYSTEM),
                (
                    "user",
                    prompts.ANALYZE_FILE_USER.format(
                        filename=filename, status=status,
                        patch=patch, rag_context=rag_context,
                    ),
                ),
            ],
        )
    out = llm_out
    # harden file field (LLM sometimes drifts)
    for c in out.comments:
        c.file = filename
    return {"comments": out.comments, "progress": [f"analyze:{filename}:done"]}


def _mock_analyze(filename: str, patch: str) -> list[ReviewComment]:
    """Deterministic heuristic findings so demos/tests run without API keys."""
    from app.schemas import Category, Severity

    findings: list[ReviewComment] = []
    line_no = 1
    m = re.search(r"@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@", patch)
    base = int(m.group(1)) if m else 1

    def add(ln, sev, cat, msg, fix=None, conf=0.85):
        findings.append(
            ReviewComment(
                file=filename, line=max(1, ln), severity=sev, category=cat,
                comment=msg, confidence=conf, suggested_fix=fix,
            )
        )

    for i, raw in enumerate(patch.splitlines()):
        if raw.startswith("+") and not raw.startswith("+++"):
            code = raw[1:]
            ln = base + i
            line_no = ln
            if "except:" in code or "except Exception" in code:
                add(ln, Severity.WARNING, Category.MAINTAINABILITY,
                    "포괄적인 except는 실제 에러를 숨깁니다. 구체적인 예외를 지정해주세요.",
                    code.replace("except:", "except ValueError:"), 0.8)
            if "TODO" in code or "FIXME" in code:
                add(ln, Severity.NIT, Category.MAINTAINABILITY,
                    "TODO가 PR에 포함되어 있어요. 이슈로 분리하거나 제거해주세요.", None, 0.55)
            if "print(" in code:
                add(ln, Severity.NIT, Category.STYLE,
                    "디버그용 print가 남아있어요. 로깅으로 교체해주세요.",
                    code.replace("print(", "logger.debug("), 0.7)
            if "password" in code.lower() and ("=" in code or ":" in code):
                add(ln, Severity.CRITICAL, Category.SECURITY,
                    "하드코딩된 credential 의심 패턴입니다. 환경변수/시크릿 매니저로 분리해주세요.",
                    None, 0.65)
            if len(code) > 120:
                add(ln, Severity.NIT, Category.STYLE,
                    f"한 줄이 {len(code)}자로 깁니다. 분리해서 가독성을 높여주세요.", None, 0.5)
    if "test" not in filename and len(findings) == 0 and ("def " in patch or "function" in patch):
        add(max(1, line_no), Severity.WARNING, Category.TEST,
            "새 로직에 대한 테스트가 보이지 않아요. 단위 테스트 추가를 권장합니다.", None, 0.5)
    return findings[:8]


# --------------------------------------------------------------- aggregate
def aggregate_node(state: ReviewState) -> dict:
    comments: list[ReviewComment] = list(state.get("comments", []))
    classification: PRClassification = state["classification"]

    if is_mock_mode():
        agg = _mock_aggregate(classification, comments)
        return {
            "final_comments": agg.comments,
            "recommendation": agg.recommendation,
            "progress": ["aggregate:done"],
        }

    # serialize compactly to save tokens
    blob = "\n".join(
        f"- {c.file}:{c.line} [{c.severity.value}/{c.category.value} conf={c.confidence:.2f}] {c.comment}"
        for c in comments
    )[:8000]
    with _timed("aggregate", f"{len(comments)} findings"):
        out: AggregatedReview = invoke_structured(
            AggregatedReview,
            [
                ("system", prompts.AGGREGATE_SYSTEM),
                (
                    "user",
                    f"Classification: {classification.model_dump_json()}\n\nFindings:\n{blob or '(none)'}",
                ),
            ],
        )
    return {
        "final_comments": out.comments,
        "recommendation": out.recommendation,
        "progress": ["aggregate:done"],
    }


def _mock_aggregate(
    classification: PRClassification, comments: list[ReviewComment]
) -> AggregatedReview:
    seen: set[tuple] = set()
    dedup: list[ReviewComment] = []
    for c in comments:
        key = (c.file, c.line, c.comment[:40])
        if key in seen:
            continue
        seen.add(key)
        dedup.append(c)
    order = {"critical": 0, "warning": 1, "nit": 2}
    dedup.sort(key=lambda c: (order[c.severity.value], -c.confidence))
    dedup = dedup[:30]
    if any(c.severity.value == "critical" for c in dedup):
        rec = "request_changes"
    elif any(c.severity.value == "warning" for c in dedup):
        rec = "comment"
    else:
        rec = "approve"
    return AggregatedReview(
        classification=classification, comments=dedup, recommendation=rec  # type: ignore[arg-type]
    )


# ----------------------------------------------------------------- rewrite
def rewrite_node(state: ReviewState) -> dict:
    final_comments: list[ReviewComment] = state.get("final_comments") or list(state.get("comments", []))

    if is_mock_mode() or not final_comments:
        return {"final_comments": final_comments, "progress": ["rewrite:done"]}

    blob = "\n".join(
        f"- {c.file}:{c.line} [{c.severity.value}] {c.comment} | fix={c.suggested_fix or '-'}"
        for c in final_comments
    )[:8000]
    try:
        with _timed("rewrite", f"{len(final_comments)} comments"):
            out: _RewriteList = invoke_structured(
                _RewriteList,
                [("system", prompts.REWRITE_SYSTEM), ("user", f"Rewrite these:\n{blob}")],
            )
        if len(out.comments) == len(final_comments):
            # preserve structured fields, only swap comment text
            for dst, src in zip(final_comments, out.comments):
                dst.comment = src.comment
    except Exception:
        pass
    return {"final_comments": final_comments, "progress": ["rewrite:done"]}
