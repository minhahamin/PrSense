"""LLM factory + deterministic mock (for tests / no-key dev).

운영 정책: 무료 모델 우선, 소진 시 최저가 유료 모델로 폴백.
- LLM_MODEL: 1순위 (예: cohere/north-mini-code:free)
- LLM_FALLBACK_MODEL: 무료가 429/모델없음/과부하로 죽을 때만 사용 (예: openai/gpt-4o-mini)
"""

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


def _is_unavailable(e: BaseException) -> bool:
    """무료 모델이 '지금 못 씀' 상태인지: 429, 엔드포인트 없음, 과부하/5xx."""
    if _is_rate_limit(e):
        return True
    msg = str(e)[:800].lower()
    name = type(e).__name__.lower()
    markers = (
        "no endpoints found",
        "temporarily",
        "overloaded",
        "overload",
        "529",
        "503",
        "502",
        "500",
        "internalservererror",
        "serviceunavailable",
        "badgateway",
    )
    return any(m in msg or m in name for m in markers)


def get_chat_model(temperature: float | None = None, model: str | None = None) -> ChatOpenAI:
    s = get_settings()
    kwargs: dict = {
        "model": model or s.llm_model,
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
    """Structured output: 무료 우선 → 소진 시 유료 폴백.

    1) 1순위 모델로 tool calling 시도, 실패 시 JSON 모드 폴백.
    2) 429/모델없음/과부하가 계속되면 LLM_FALLBACK_MODEL로 같은 절차 반복.
       (출력 파싱 실패 같은 '모델은 살아있음' 에러에는 폴백하지 않음 — 비용 보호)
    """
    s = get_settings()
    primary = s.llm_model
    fallback = (s.llm_fallback_model or "").strip()

    def _attempt(model: str) -> T:
        @retry(
            retry=retry_if_exception(_is_rate_limit),
            stop=stop_after_attempt(1),
            wait=wait_exponential(multiplier=1, min=1, max=5),
            reraise=True,
        )
        def _call() -> T:
            llm = get_chat_model(model=model)
            try:
                return llm.with_structured_output(schema).invoke(messages)
            except Exception as e:  # noqa: BLE001
                if _is_rate_limit(e):
                    raise
                log.warning("tool-calling failed, trying JSON mode",
                            schema=schema.__name__, model=model, error=str(e)[:200])

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

    try:
        return _attempt(primary)
    except Exception as e:  # noqa: BLE001
        if fallback and fallback != primary and _is_unavailable(e):
            log.warning("primary model unavailable, switching to fallback",
                        primary=primary, fallback=fallback, error=str(e)[:200])
            return _attempt(fallback)
        raise
