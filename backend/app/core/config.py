from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: str = "development"

    database_url: str = "postgresql+psycopg://devforge:devforge@localhost:5432/devforge"
    host_workspace_path: str = "/Users/dhananjaya/Desktop/devforge-ai"

    llm_provider: str = "bedrock"
    llm_model: str = "llama3"
    aws_region: str = "us-east-1"
    bedrock_model_id: str = "meta.llama3-1-70b-instruct-v1:0"


@lru_cache
def get_settings() -> Settings:
    return Settings()
