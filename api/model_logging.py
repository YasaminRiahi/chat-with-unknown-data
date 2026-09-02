"""JSONL audit logging for chat and embedding model calls."""

from __future__ import annotations

import json
import math
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from langchain_ollama import OllamaEmbeddings


class ModelCallLogger:
    """Append one self-contained JSON object per provider call."""

    def __init__(self, path: str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def write(self, record: dict[str, Any]) -> None:
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **record,
        }
        line = json.dumps(record, ensure_ascii=False, default=str)
        with self._lock, self.path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")


def _estimated_tokens(texts: list[str]) -> int:
    """Conservative display estimate; provider usage remains authoritative."""
    return math.ceil(sum(len(text) for text in texts) / 3)


def _message_payload(messages: Any) -> list[dict[str, Any]]:
    if not isinstance(messages, (list, tuple)):
        messages = [messages]
    payload = []
    for message in messages:
        payload.append({
            "role": getattr(message, "type", type(message).__name__),
            "content": getattr(message, "content", str(message)),
        })
    return payload


def _chat_operation(messages: list[dict[str, Any]]) -> str:
    combined = "\n".join(str(message["content"]) for message in messages)
    if "Generate a T-SQL query" in combined:
        return "sql_generation"
    if "Fix this T-SQL query" in combined:
        return "self_correction"
    if "answer-generation layer" in combined:
        return "answer_generation"
    if (
        "You enrich database schemas for semantic table retrieval" in combined
        or "Translate existing English database schema enrichment" in combined
    ):
        return "schema_enrichment"
    if "Select the smallest connected set of database tables" in combined:
        return "schema_linking"
    return "general_chat"


def _chat_usage(response: Any) -> dict[str, Any]:
    usage = getattr(response, "usage_metadata", None)
    if usage:
        return {"source": "provider", **dict(usage)}
    metadata = getattr(response, "response_metadata", {}) or {}
    token_usage = metadata.get("token_usage") or metadata.get("usage")
    if token_usage:
        return {"source": "provider", **dict(token_usage)}
    return {"source": "unavailable"}


class LoggedChatModel:
    """Small proxy that preserves the normal LangChain invoke interface."""

    def __init__(self, model: Any, logger: ModelCallLogger):
        self.model = model
        self.logger = logger

    def invoke(self, messages: Any, *args: Any, **kwargs: Any) -> Any:
        payload = _message_payload(messages)
        texts = [str(message["content"]) for message in payload]
        started = time.perf_counter()
        base = {
            "provider": "groq",
            "model": getattr(self.model, "model_name", None)
                or getattr(self.model, "model", "unknown"),
            "operation": _chat_operation(payload),
            "request": {"messages": payload},
            "request_size": {
                "characters": sum(len(text) for text in texts),
                "estimated_tokens": _estimated_tokens(texts),
                "estimate_note": "character estimate only; usage.source=provider is exact",
            },
        }
        try:
            response = self.model.invoke(messages, *args, **kwargs)
        except Exception as exc:
            self.logger.write({
                **base,
                "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                "status": "error",
                "error": {"type": type(exc).__name__, "message": str(exc)},
            })
            raise

        self.logger.write({
            **base,
            "duration_ms": round((time.perf_counter() - started) * 1000, 2),
            "status": "success",
            "usage": _chat_usage(response),
            "response": {"content": getattr(response, "content", str(response))},
        })
        return response


class LoggedOllamaEmbeddings(OllamaEmbeddings):
    """Local Ollama embeddings with exact evaluated-token audit logs."""

    _audit_logger: ModelCallLogger

    def configure_logging(
        self, logger: ModelCallLogger
    ) -> "LoggedOllamaEmbeddings":
        object.__setattr__(self, "_audit_logger", logger)
        return self

    def _embed(self, texts: list[str], operation: str) -> list[list[float]]:
        started = time.perf_counter()
        base = {
            "provider": "ollama",
            "model": self.model,
            "operation": operation,
            "request": {"texts": texts},
            "request_size": {
                "texts": len(texts),
                "characters": sum(len(text) for text in texts),
                "estimated_tokens": _estimated_tokens(texts),
                "estimate_note": "character estimate only; usage.input_tokens is exact",
            },
        }
        try:
            if not self._client:
                raise RuntimeError("Ollama sync client is not initialized.")
            response = self._client.embed(
                self.model,
                texts,
                dimensions=self.dimensions,
                options=self._default_params,
                keep_alive=self.keep_alive,
            )
        except Exception as exc:
            self._audit_logger.write({
                **base,
                "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                "status": "error",
                "error": {"type": type(exc).__name__, "message": str(exc)},
            })
            raise

        embeddings = [list(map(float, value)) for value in response["embeddings"]]
        input_tokens = response.get("prompt_eval_count")

        self._audit_logger.write({
            **base,
            "duration_ms": round((time.perf_counter() - started) * 1000, 2),
            "status": "success",
            "usage": {
                "source": "ollama_prompt_eval_count",
                "input_tokens": input_tokens,
                "total_tokens": input_tokens,
            },
            "response": {
                "embedding_count": len(embeddings),
                "dimensions": len(embeddings[0]) if embeddings else 0,
            },
        })
        return embeddings

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._embed(texts, "embedding_search_document")

    def embed_query(self, text: str) -> list[float]:
        return self._embed([text], "embedding_search_query")[0]
