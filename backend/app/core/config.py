from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: str = "development"

    database_url: str = "postgresql+psycopg://devforge:devforge@localhost:5432/devforge"
    host_workspace_path: str = "/Users/dhananjaya/Desktop/devforge-ai"

    llm_provider: str = "simulator"
    llm_model: str = "llama3"


@lru_cache
def get_settings() -> Settings:
    return Settings()
