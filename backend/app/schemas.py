"""Shared Pydantic contracts. Every LLM output is forced through these models."""

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class Severity(str, Enum):
    CRITICAL = "critical"
    WARNING = "warning"
    NIT = "nit"


class Category(str, Enum):
    CORRECTNESS = "correctness"
    SECURITY = "security"
    PERFORMANCE = "performance"
    MAINTAINABILITY = "maintainability"
    STYLE = "style"
    TEST = "test"


class ChangeType(str, Enum):
    FEATURE = "feature"
    BUGFIX = "bugfix"
    REFACTOR = "refactor"
    DOCS = "docs"
    TEST = "test"
    CHORE = "chore"
    MIXED = "mixed"


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


# ------------------------------------------------------------------ #
# LLM structured outputs
# ------------------------------------------------------------------ #
class ReviewComment(BaseModel):
    """Single inline review finding. Structured output enforced on the LLM."""

    file: str = Field(description="Repository-relative file path, e.g. backend/app/main.py")
    line: int = Field(ge=1, description="1-based line number in the NEW file (right side of diff)")
    severity: Severity
    category: Category
    comment: str = Field(min_length=10, description="Human-readable review, Korean, concise")
    confidence: float = Field(ge=0.0, le=1.0, description="Model self-confidence 0..1")
    suggested_fix: str | None = Field(
        default=None, description="Minimal code suggestion / patch snippet, if applicable"
    )

    @property
    def needs_confirmation(self) -> bool:
        from app.config import get_settings

        return self.confidence < get_settings().confidence_threshold


class FileReview(BaseModel):
    file: str
    comments: list[ReviewComment] = Field(default_factory=list)


class PRClassification(BaseModel):
    change_type: ChangeType
    risk_level: RiskLevel
    summary: str = Field(description="2-3 sentence PR summary in Korean")
    focus_areas: list[str] = Field(
        default_factory=list, description="Files/areas reviewers should focus on"
    )
    reasoning: str = Field(default="", description="Short rationale for classification")


class AggregatedReview(BaseModel):
    classification: PRClassification
    comments: list[ReviewComment]
    recommendation: Literal["approve", "comment", "request_changes"]


class FinalReviewResponse(AggregatedReview):
    """What the API returns / what gets posted to GitHub."""

    pr_number: int
    repo: str
    low_confidence_count: int = 0


# ------------------------------------------------------------------ #
# GitHub webhook / API DTOs
# ------------------------------------------------------------------ #
class PRFileDiff(BaseModel):
    filename: str
    status: str  # added | modified | removed | renamed
    additions: int = 0
    deletions: int = 0
    patch: str = ""  # unified diff text
    previous_filename: str | None = None


class PRContext(BaseModel):
    repo: str  # "owner/name"
    pr_number: int
    title: str = ""
    body: str = ""
    base_sha: str = ""
    head_sha: str = ""
    files: list[PRFileDiff] = Field(default_factory=list)


class WebhookAck(BaseModel):
    ok: bool
    run_id: str
    message: str = ""
