"""Environment-based application configuration."""

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_list(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    value = os.getenv(name)
    if value is None:
        return default
    return tuple(item.strip() for item in value.split(",") if item.strip())


@dataclass(frozen=True)
class Settings:
    groq_api_key: str
    chat_model: str = "openai/gpt-oss-120b"
    embedding_model: str = "bge-m3"
    ollama_base_url: str = "http://localhost:11434"
    model_log_path: str = "logs/model_calls.jsonl"
    enrichment_cache_dir: str = ".cache/enrichment"
    embedding_cache_dir: str = ".cache/embeddings"
    llm_enrichment_enabled: bool = True
    enrichment_batch_size: int = 12
    schema_linking_enabled: bool = True
    cors_allowed_origins: tuple[str, ...] = (
        "http://localhost:25796",
        "http://127.0.0.1:25796",
        "http://localhost:5500",
        "http://127.0.0.1:5500",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    )

    @classmethod
    def from_env(cls) -> "Settings":
        groq_api_key = os.getenv("GROQ_API_KEY", "").strip()
        if not groq_api_key:
            raise RuntimeError(
                "GROQ_API_KEY is not set. Copy .env.example to .env and add "
                "a key from https://console.groq.com/keys"
            )

        return cls(
            groq_api_key=groq_api_key,
            chat_model=os.getenv("CHAT_MODEL", cls.chat_model),
            embedding_model=os.getenv("EMBEDDING_MODEL", cls.embedding_model),
            ollama_base_url=os.getenv("OLLAMA_BASE_URL", cls.ollama_base_url),
            model_log_path=os.getenv("MODEL_LOG_PATH", cls.model_log_path),
            enrichment_cache_dir=os.getenv(
                "ENRICHMENT_CACHE_DIR", cls.enrichment_cache_dir
            ),
            embedding_cache_dir=os.getenv(
                "EMBEDDING_CACHE_DIR", cls.embedding_cache_dir
            ),
            llm_enrichment_enabled=_env_bool(
                "LLM_ENRICHMENT_ENABLED", cls.llm_enrichment_enabled
            ),
            enrichment_batch_size=max(
                1, int(os.getenv("ENRICHMENT_BATCH_SIZE", cls.enrichment_batch_size))
            ),
            schema_linking_enabled=_env_bool(
                "SCHEMA_LINKING_ENABLED", cls.schema_linking_enabled
            ),
            cors_allowed_origins=_env_list(
                "CORS_ALLOWED_ORIGINS", cls.cors_allowed_origins
            ),
        )
