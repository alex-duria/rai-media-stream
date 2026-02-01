"""Application configuration using pydantic-settings."""
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    # OpenAI
    openai_api_key: str = ""
    openai_embedding_model: str = "text-embedding-3-small"

    # Recall.ai
    recall_api_key: str = ""
    recall_region: str = "us-west-2"

    # Public URL for output media page (use ngrok URL for testing)
    client_url: str = "http://localhost:5173"

    # Public URL for server WebSocket (use ngrok URL for testing)
    server_url: str = "http://localhost:8000"

    # Data paths
    data_dir: str = "data"

    # RAG settings
    rag_similarity_threshold: float = 0.20
    rag_top_k: int = 5
    chunk_size: int = 500
    chunk_overlap: int = 50


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
