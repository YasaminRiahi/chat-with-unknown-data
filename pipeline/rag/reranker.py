"""Lazy local cross-encoder reranker used after hybrid candidate retrieval."""

from __future__ import annotations


class CrossEncoderReranker:
    def __init__(self, model_name: str, *, enabled: bool = True):
        self.model_name = model_name
        self.enabled = enabled
        self._model = None

    def _ensure_model(self):
        if not self.enabled:
            raise RuntimeError("reranking is disabled")
        if self._model is None:
            try:
                from sentence_transformers import CrossEncoder
            except ImportError as exc:
                raise RuntimeError(
                    "sentence-transformers is not installed"
                ) from exc
            print(f"[RAG] Loading reranker: {self.model_name}")
            self._model = CrossEncoder(self.model_name)
        return self._model

    def score_pairs(self, pairs: list[tuple[str, str]]) -> list[float]:
        values = self._ensure_model().predict(pairs, show_progress_bar=False)
        return [float(value) for value in values]
