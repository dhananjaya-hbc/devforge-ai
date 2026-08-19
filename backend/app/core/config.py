from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: str = "development"

    database_url: str = "postgresql+psycopg://devforge:devforge@localhost:5432/devforge"
    host_workspace_path: str = "/Users/dhananjaya/Desktop/devforge-ai"

    # Only open-weight models are permitted as the core intelligence layer.
    llm_provider: str = "groq"
    llm_model: str = "qwen/qwen3.6-27b"
    groq_api_key: str | None = None
    ollama_base_url: str = "http://localhost:11434"


@lru_cache
def get_settings() -> Settings:
    return Settings()
