"""PrSense backend — FastAPI app factory."""

from __future__ import annotations

import logging

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes_events import router as events_router
from app.api.routes_prs import router as prs_router
from app.api.routes_webhook import router as webhook_router
from app.config import get_settings

structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(
        getattr(logging, get_settings().log_level.upper(), logging.INFO)
    ),
)


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(title="PrSense", version="0.1.0",
                  description="GitHub PR auto-review agent (LangGraph + RAG)")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[s.frontend_origin, "*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    def health():
        return {
            "ok": True,
            "mock_llm": (not s.openai_api_key) or s.mock_llm,
            "model": s.llm_model,
            "chroma_dir": s.chroma_dir,
        }

    app.include_router(webhook_router, prefix="/webhook", tags=["webhook"])
    app.include_router(prs_router, prefix="/prs", tags=["prs"])
    app.include_router(events_router, prefix="/events", tags=["events"])
    return app


app = create_app()
