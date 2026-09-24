"""LLM factory + deterministic mock (for tests / no-key dev)."""

from __future__ import annotations

import json
from typing import TypeVar

import structlog
from pydantic import BaseModel
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from langchain_openai import ChatOpenAI, OpenAIEmbeddings

from app.config import get_settings

log = structlog.get_logger()
T = TypeVar("T", bound=BaseModel)


def _is_rate_limit(e: BaseException) -> bool:
    name = type(e).__name__.lower()
    msg = str(e)[:500].lower()
    return "429" in name or "ratelimit" in name or "rate-limit" in msg or "rate limit" in msg


def get_chat_model(temperature: float | None = None) -> ChatOpenAI:
    s = get_settings()
    kwargs: dict = {
        "model": s.llm_model,
        "temperature": s.llm_temperature if temperature is None else temperature,
        "api_key": s.openai_api_key,
        # hang 방지: 무료 티어 429/무응답 시 빠르게 실패하고 재시도
        "request_timeout": s.llm_timeout,
        "max_retries": s.llm_max_retries,
    }
    if s.llm_base_url:
        kwargs["base_url"] = s.llm_base_url
    if s.llm_max_tokens > 0:
        # OpenRouter 무료 크레딧처럼 예산이 빡빡할 때 예약 토큰 상한을 제한
        kwargs["max_tokens"] = s.llm_max_tokens
    return ChatOpenAI(**kwargs)


def get_embedding_model() -> OpenAIEmbeddings:
    s = get_settings()
    kwargs: dict = {"model": s.embedding_model, "api_key": s.openai_api_key}
    if s.llm_base_url:
        # OpenAIEmbeddings uses openai_api_base in this langchain-openai version
        kwargs["openai_api_base"] = s.llm_base_url
    return OpenAIEmbeddings(**kwargs)


def is_mock_mode() -> bool:
    s = get_settings()
    return s.mock_llm or not s.openai_api_key


def invoke_structured(schema: type[T], messages: list) -> T:
    """Structured output that also works with free/tool-call-less models.

    1) Try native tool calling (OpenAI, GPT-mini, Qwen, GLM with tools…).
    2) Fall back to "JSON only" prompt + salvage parsing (Gemma-style models).
    429 rate limits are retried with backoff (free-tier upstream is flaky).
    Raises the last error if all fail.
    """

    @retry(
        retry=retry_if_exception(_is_rate_limit),
        stop=stop_after_attempt(6),
        wait=wait_exponential(multiplier=10, min=15, max=120),
        reraise=True,
    )
    def _call() -> T:
        llm = get_chat_model()
        try:
            return llm.with_structured_output(schema).invoke(messages)
        except Exception as e:  # noqa: BLE001
            if _is_rate_limit(e):
                raise
            log.warning("tool-calling failed, trying JSON mode",
                        schema=schema.__name__, error=str(e)[:200])

        schema_hint = json.dumps(schema.model_json_schema(), ensure_ascii=False)[:4000]
        json_messages = list(messages) + [
            ("user",
             "Respond with ONLY a valid JSON object matching this JSON Schema. "
             "No markdown fences, no prose, no explanation:\n" + schema_hint)
        ]
        raw = llm.invoke(json_messages).content
        if not isinstance(raw, str):
            raw = str(raw)
        text = raw.strip()
        # strip ```json fences if present
        if text.startswith("```"):
            text = text.strip("`").lstrip("json").strip()
        # salvage: first { … last }
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            raise ValueError(f"no JSON object in model output: {text[:300]}")
        return schema.model_validate(json.loads(text[start : end + 1]))

    return _call()
