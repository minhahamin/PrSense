"""Centralised runtime configuration (pydantic-settings)."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # LLM
    openai_api_key: str = ""
    llm_model: str = "gpt-4o-mini"
    llm_temperature: float = 0.1
    embedding_model: str = "text-embedding-3-small"

    # GitHub
    github_token: str = ""
    github_webhook_secret: str = "change-me"
    allowed_repos: str = ""  # comma separated "owner/repo"

    # RAG
    chroma_dir: str = "/data/chroma"
    chroma_collection: str = "prsense_code"
    rag_top_k: int = 5
    confidence_threshold: float = 0.6

    # App
    log_level: str = "INFO"
    frontend_origin: str = "http://localhost:5173"
    mock_llm: bool = False

    # Database — Railway injects DATABASE_URL when Postgres is added.
    # Empty → SQLite fallback (local dev / tests).
    database_url: str = ""
    sqlite_path: str = ""

    @property
    def allowed_repo_set(self) -> set[str]:
        if not self.allowed_repos.strip():
            return set()
        return {r.strip() for r in self.allowed_repos.split(",") if r.strip()}


@lru_cache
def get_settings() -> Settings:
    return Settings()
