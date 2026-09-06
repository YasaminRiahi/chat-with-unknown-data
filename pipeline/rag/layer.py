"""Hierarchical semantic retrieval over tables and columns.

Table and column vectors are persisted on disk. A database restart therefore
only embeds metadata whose content or embedding model has changed.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from pathlib import Path
from typing import Any

from langchain_core.messages import HumanMessage

from pipeline.base import BaseLayer
from pipeline.introspection.layer import IntrospectionResult


class _PersistentEmbeddingIndex:
    CACHE_VERSION = 1
    EMBED_BATCH_SIZE = 32
    EMBED_BATCH_CHARACTERS = 24_000

    def __init__(self, embeddings, path: Path):
        self.embeddings = embeddings
        self.path = path
        self.items: dict[str, dict[str, Any]] = {}
        self.vectors: dict[str, list[float]] = {}

    def _model_name(self) -> str:
        return str(getattr(self.embeddings, "model", type(self.embeddings).__name__))

    @staticmethod
    def _digest(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    @staticmethod
    def _valid_vector(vector: Any) -> bool:
        """Reject empty vectors and values JSON cannot safely represent."""
        if not isinstance(vector, (list, tuple)) or not vector:
            return False
        try:
            return all(math.isfinite(float(value)) for value in vector)
        except (TypeError, ValueError):
            return False

    @staticmethod
    def _is_nan_error(exc: Exception) -> bool:
        message = str(exc).casefold()
        return "nan" in message or "unsupported value" in message

    @staticmethod
    def _safe_text(text: str) -> str:
        """Perturb pathological tokenization without changing metadata meaning."""
        return "Database metadata record:\n" + text

    def _embed_one_resilient(
        self, item_id: str, text: str,
    ) -> tuple[list[float], bool]:
        """Embed one document, normalizing only reproducible NaN failures."""
        normalized = False
        try:
            vectors = self.embeddings.embed_documents([text])
            vector = vectors[0] if vectors else []
            if not self._valid_vector(vector):
                raise ValueError("Embedding contained NaN, infinity, or no values")
        except Exception as exc:
            if not self._is_nan_error(exc):
                raise
            normalized = True
            safe_text = self._safe_text(text)
            print(
                f"[RAG] NaN document: {item_id}; "
                "retrying with safe metadata formatting"
            )
            vectors = self.embeddings.embed_documents([safe_text])
            vector = vectors[0] if vectors else []
            if not self._valid_vector(vector):
                raise RuntimeError(
                    "Embedding remained invalid after safe metadata formatting"
                ) from exc
        return [float(value) for value in vector], normalized

    def _load(self) -> dict[str, Any]:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            if (
                payload.get("cache_version") == self.CACHE_VERSION
                and payload.get("model") == self._model_name()
            ):
                return payload
        except FileNotFoundError:
            pass
        except (OSError, json.JSONDecodeError) as exc:
            print(f"[RAG] WARNING - cannot read embedding cache: {exc}")
        return {}

    def _save(self, entries: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(
            json.dumps({
                "cache_version": self.CACHE_VERSION,
                "model": self._model_name(),
                "entries": entries,
            }, ensure_ascii=False),
            encoding="utf-8",
        )
        temporary.replace(self.path)

    @staticmethod
    def _batches(pending: list[tuple[str, str]]):
        batch: list[tuple[str, str]] = []
        characters = 0
        for item in pending:
            if batch and (
                len(batch) >= _PersistentEmbeddingIndex.EMBED_BATCH_SIZE
                or characters + len(item[1])
                > _PersistentEmbeddingIndex.EMBED_BATCH_CHARACTERS
            ):
                yield batch
                batch, characters = [], 0
            batch.append(item)
            characters += len(item[1])
        if batch:
            yield batch

    def build(self, items: dict[str, dict[str, Any]]) -> None:
        """Load matching vectors and embed only new or changed documents."""
        cached = self._load().get("entries", {})
        pending: list[tuple[str, str]] = []
        entries: dict[str, Any] = {}
        self.items = items
        self.vectors = {}

        for item_id, item in items.items():
            digest = self._digest(item["text"])
            entry = cached.get(item_id, {})
            vector = entry.get("vector") if entry.get("digest") == digest else None
            if self._valid_vector(vector):
                self.vectors[item_id] = [float(value) for value in vector]
                entries[item_id] = {"digest": digest, "vector": vector}
            else:
                pending.append((item_id, item["text"]))

        if pending:
            print(f"[RAG] Embedding {len(pending)} new or changed metadata documents")
        for batch in self._batches(pending):
            try:
                vectors = self.embeddings.embed_documents([text for _, text in batch])
                if len(vectors) != len(batch) or not all(
                    self._valid_vector(vector) for vector in vectors
                ):
                    raise ValueError(
                        "Embedding batch contained NaN, infinity, missing vectors, "
                        "or empty vectors"
                    )
                for (item_id, text), vector in zip(batch, vectors):
                    values = [float(value) for value in vector]
                    self.vectors[item_id] = values
                    entries[item_id] = {
                        "digest": self._digest(text), "vector": values,
                    }
            except Exception as batch_exc:
                print(
                    f"[RAG] WARNING - embedding batch failed ({batch_exc}); "
                    "retrying its documents individually"
                )
                for item_id, text in batch:
                    values, normalized = self._embed_one_resilient(item_id, text)
                    self.vectors[item_id] = values
                    entries[item_id] = {
                        "digest": self._digest(text),
                        "vector": values,
                        "safe_format": normalized,
                    }
                    # A later item may still fail, so retain each recovered vector.
                    self._save(entries)
            else:
                # Preserve completed work if a later Ollama batch fails.
                self._save(entries)

        if not pending or len(entries) == len(items):
            self._save(entries)
        reused = len(items) - len(pending)
        print(f"[RAG] Embedding cache: {reused} reused, {len(pending)} generated")

    @staticmethod
    def _cosine(left: list[float], right: list[float]) -> float:
        numerator = sum(a * b for a, b in zip(left, right))
        left_norm = math.sqrt(sum(value * value for value in left))
        right_norm = math.sqrt(sum(value * value for value in right))
        if not left_norm or not right_norm:
            return 0.0
        return numerator / (left_norm * right_norm)

    def scores(
        self, query_vector: list[float], *, kind: str,
        tables: set[tuple[str, str]] | None = None,
    ) -> list[tuple[dict[str, Any], float]]:
        matches = []
        for item_id, item in self.items.items():
            if item["kind"] != kind:
                continue
            table_key = (item["schema"], item["table"])
            if tables is not None and table_key not in tables:
                continue
            matches.append((item, self._cosine(query_vector, self.vectors[item_id])))
        return sorted(matches, key=lambda match: match[1], reverse=True)

    @staticmethod
    def _lexical_tokens(text: str) -> list[str]:
        """Tokenize prose and SQL identifiers for lightweight BM25 retrieval."""
        expanded = re.sub(r"([a-z\d])([A-Z])", r"\1 \2", text)
        expanded = re.sub(r"[_\-.]+", " ", expanded)
        return re.findall(r"[^\W_]+", expanded.casefold(), flags=re.UNICODE)

    def lexical_scores(
        self, query: str, *, kind: str,
        tables: set[tuple[str, str]] | None = None,
    ) -> list[tuple[dict[str, Any], float]]:
        """Return exact BM25 scores over the current metadata documents."""
        candidates = [
            (item_id, item) for item_id, item in self.items.items()
            if item["kind"] == kind
            and (tables is None or (item["schema"], item["table"]) in tables)
        ]
        query_terms = self._lexical_tokens(query)
        if not candidates or not query_terms:
            return []
        documents = {
            item_id: Counter(self._lexical_tokens(item["text"]))
            for item_id, item in candidates
        }
        lengths = {item_id: sum(terms.values()) for item_id, terms in documents.items()}
        average_length = sum(lengths.values()) / len(lengths) or 1.0
        document_frequency = Counter()
        for terms in documents.values():
            document_frequency.update(terms.keys())

        scored = []
        total = len(candidates)
        k1, b = 1.5, 0.75
        for item_id, item in candidates:
            score = 0.0
            terms = documents[item_id]
            for term in query_terms:
                frequency = terms.get(term, 0)
                if not frequency:
                    continue
                frequency_docs = document_frequency[term]
                inverse_frequency = math.log(
                    1.0 + (total - frequency_docs + 0.5) / (frequency_docs + 0.5)
                )
                denominator = frequency + k1 * (
                    1.0 - b + b * lengths[item_id] / average_length
                )
                score += inverse_frequency * frequency * (k1 + 1.0) / denominator
            if score > 0:
                scored.append((item, score))
        return sorted(scored, key=lambda match: match[1], reverse=True)


class RAGLayer(BaseLayer):
    MAX_TABLES = 8
    MAX_FK_EXPANSION = 4
    TABLE_RERANK_CANDIDATES = 24
    ALL_COLUMNS_TABLE_LIMIT = 30
    MAX_WIDE_TABLE_COLUMNS = 20
    MAX_SCHEMA_CHARACTERS = 21_000
    TABLE_SCORE_WINDOW = 0.10
    MIN_SIMILARITY = 0.30
    BASE_ENTITY_MARGIN = 0.05
    BASE_ENTITY_BONUS = 0.03
    DERIVATIVE_TABLE_PENALTY = 0.015
    FUSION_CANDIDATES = 40
    RRF_K = 60
    SCHEMA_LINK_CANDIDATES = 12
    MAX_SCHEMA_LINK_COLUMNS = 12

    @staticmethod
    def _log_table_ranking(
        stage: str, scored: list[tuple[dict[str, Any], float]], *, limit: int = 30,
    ) -> None:
        """Print a compact retrieval trace so table losses are diagnosable."""
        if not scored:
            print(f"[RAG][Trace] {stage}: <no candidates>")
            return
        rendered = ", ".join(
            f"{item['schema']}.{item['table']}={score:.6f}"
            for item, score in scored[:limit]
        )
        print(f"[RAG][Trace] {stage}: {rendered}")
    def __init__(
        self, llm, embeddings, db_manager,
        cache_dir: str = ".cache/embeddings",
        schema_linking_enabled: bool = True,
    ):
        super().__init__(llm, embeddings, db_manager)
        self.cache_dir = Path(cache_dir)
        self.indexes: dict[str, _PersistentEmbeddingIndex] = {}
        self.schema_linking_enabled = schema_linking_enabled

    @classmethod
    def _fuse_scores(
        cls, *rankings: list[tuple[dict[str, Any], float]],
    ) -> list[tuple[dict[str, Any], float]]:
        """Fuse heterogeneous rankings with Reciprocal Rank Fusion."""
        combined: dict[str, tuple[dict[str, Any], float]] = {}
        for ranking in rankings:
            for rank, (item, _) in enumerate(ranking, start=1):
                item_id = (
                    f"{item['kind']}:{item['schema']}.{item['table']}."
                    f"{item.get('column', {}).get('name', '')}"
                )
                previous = combined.get(item_id, (item, 0.0))[1]
                combined[item_id] = (item, previous + 1.0 / (cls.RRF_K + rank))
        ranked = sorted(combined.values(), key=lambda match: match[1], reverse=True)
        if not ranked:
            return []
        maximum = ranked[0][1]
        return [(item, score / maximum) for item, score in ranked]

    @classmethod
    def _schema_link_columns(
        cls, metadata: dict[str, Any], question: str = "",
    ) -> list[dict[str, Any]]:
        """Return compact columns while retaining identifiers and relationships."""
        columns = list(metadata.get("columns", []))
        question_tokens = set(cls._identifier_tokens(question))
        important, matching, ordinary = [], [], []
        for column in columns:
            normalized = cls._normalized(str(column.get("name", "")))
            column_tokens = set(cls._identifier_tokens(str(column.get("name", ""))))
            if (
                column.get("primary_key")
                or column.get("references")
                or normalized.endswith("id")
                or normalized.endswith("ref")
            ):
                target = important
            elif question_tokens & column_tokens:
                target = matching
            else:
                target = ordinary
            target.append(column)
        selected = (important + matching + ordinary)[:cls.MAX_SCHEMA_LINK_COLUMNS]
        return [
            {
                "name": str(column.get("name", "")),
                "primary_key": bool(column.get("primary_key")),
                "references": column.get("references"),
            }
            for column in selected
        ]

    @classmethod
    def _schema_link_relationships(
        cls, candidate_keys: list[tuple[str, str]], result: IntrospectionResult,
    ) -> list[dict[str, str]]:
        """Build authoritative FK edges plus conservative Ref-to-Id hints."""
        candidate_set = set(candidate_keys)
        relationships: list[dict[str, str]] = []
        seen: set[tuple[str, str]] = set()

        def add(source: str, target: str, confidence: str) -> None:
            edge = (source.casefold(), target.casefold())
            if edge not in seen:
                seen.add(edge)
                relationships.append({
                    "from": source, "to": target, "confidence": confidence,
                })

        table_by_stem: dict[str, list[tuple[str, str]]] = {}
        for key in candidate_keys:
            table_by_stem.setdefault(cls._normalized(key[1]), []).append(key)

        for source_key in candidate_keys:
            metadata = result.table_metadata.get(source_key, {})
            for column in metadata.get("columns", []):
                column_name = str(column.get("name", ""))
                reference = column.get("references")
                if reference:
                    parts = str(reference).split(".", 2)
                    target_key = (
                        result.resolve_table(parts[0], parts[1])
                        if len(parts) == 3 else None
                    )
                    if target_key in candidate_set:
                        add(
                            f"{source_key[0]}.{source_key[1]}.{column_name}",
                            f"{target_key[0]}.{target_key[1]}.{parts[2]}",
                            "declared_fk",
                        )
                    continue

                normalized_column = cls._normalized(column_name)
                if not normalized_column.endswith("ref"):
                    continue
                stem = normalized_column[:-3]
                for target_key in table_by_stem.get(stem, []):
                    target_columns = result.table_metadata.get(
                        target_key, {}
                    ).get("columns", [])
                    id_names = {
                        "id", stem + "id", cls._normalized(target_key[1]) + "id"
                    }
                    target_column = next(
                        (
                            str(candidate.get("name", ""))
                            for candidate in target_columns
                            if cls._normalized(str(candidate.get("name", "")))
                            in id_names
                        ),
                        None,
                    )
                    if target_column:
                        add(
                            f"{source_key[0]}.{source_key[1]}.{column_name}",
                            f"{target_key[0]}.{target_key[1]}.{target_column}",
                            "inferred_name_match",
                        )
        return relationships

    def _llm_schema_link(
        self, question: str, scored: list[tuple[dict[str, Any], float]],
        result: IntrospectionResult,
    ) -> list[tuple[str, str]] | None:
        """Select a coherent table group, failing open to deterministic retrieval."""
        if not self.schema_linking_enabled or self.llm is None or not scored:
            return None

        candidates = scored[:self.SCHEMA_LINK_CANDIDATES]
        keys = [(item["schema"], item["table"]) for item, _ in candidates]
        payload = []
        for rank, ((item, score), key) in enumerate(zip(candidates, keys), start=1):
            payload.append({
                "id": f"{key[0]}.{key[1]}",
                "retrieval_rank": rank,
                "retrieval_score": round(float(score), 6),
                "description": result.retrieval_table_description(*key),
                "columns": self._schema_link_columns(
                    result.table_metadata.get(key, {}), question
                ),
            })
        relationships = self._schema_link_relationships(keys, result)
        prompt = f"""Select the smallest connected set of database tables needed to answer the question.

Rules:
- Select only exact table ids supplied in candidates; never invent identifiers.
- Consider all candidates together, including header/detail and bridge tables.
- A table needed only to connect two required tables should be selected.
- declared_fk relationships are authoritative.
- inferred_name_match relationships are hints inferred from Ref/Id names; use them
  only when their business meaning also fits the question.
- Prefer recall when omitting a table would make the required join impossible.
- Select at most {self.MAX_TABLES} tables.
- Return JSON only: {{"tables":["schema.table"],"reason":"brief reason"}}

Question:
{question}

Candidates:
{json.dumps(payload, ensure_ascii=False)}

Relationships:
{json.dumps(relationships, ensure_ascii=False)}
"""
        try:
            response = self.llm.invoke([HumanMessage(content=prompt)])
            text = str(response.content).strip().replace("```json", "").replace("```", "")
            start, end = text.find("{"), text.rfind("}")
            if start < 0 or end <= start:
                raise ValueError("response did not contain a JSON object")
            decoded = json.loads(text[start:end + 1])
            requested = decoded.get("tables")
            if not isinstance(requested, list) or not requested:
                raise ValueError("response did not contain a non-empty tables array")

            allowed = {f"{s}.{t}".casefold(): (s, t) for s, t in keys}
            normalized = [str(value).strip().casefold() for value in requested]
            if len(normalized) > self.MAX_TABLES or any(
                value not in allowed for value in normalized
            ):
                raise ValueError("response contained unknown or too many tables")
            selected = []
            for value in normalized:
                key = allowed[value]
                if key not in selected:
                    selected.append(key)
            print(
                "[RAG][Trace] LLM schema-linked tables: "
                + ", ".join(f"{s}.{t}" for s, t in selected)
            )
            return selected
        except Exception as exc:
            print(
                f"[RAG] WARNING - schema linking failed ({exc}); "
                "using deterministic retrieval"
            )
            return None

    @staticmethod
    def _cache_name(db_name: str) -> str:
        slug = re.sub(r"[^a-zA-Z0-9_.-]+", "_", db_name).strip("_") or "database"
        suffix = hashlib.sha256(db_name.encode("utf-8")).hexdigest()[:10]
        return f"{slug}-{suffix}.json"

    @staticmethod
    def _normalized(value: str) -> str:
        return re.sub(r"[^\w]+", "", value, flags=re.UNICODE).casefold()

    @staticmethod
    def _identifier_tokens(identifier: str) -> tuple[str, ...]:
        """Split PascalCase/snake_case identifiers without database-specific words."""
        normalized = re.sub(r"[_\-.]+", " ", identifier)
        tokens = re.findall(
            r"[A-Z]+(?=[A-Z][a-z]|\d|\b)|[A-Z]?[a-z]+|\d+",
            normalized,
        )
        return tuple(token.casefold() for token in tokens)

    @classmethod
    def _identifier_variants(cls, left: str, right: str) -> bool:
        """Return true when one identifier adds one prefix/suffix token.

        This recognizes Title/Title_En and Description/EnglishDescription but
        does not conflate same-shaped numbered columns such as Field1/Field2.
        """
        left_tokens = cls._identifier_tokens(left)
        right_tokens = cls._identifier_tokens(right)
        shorter, longer = sorted(
            (left_tokens, right_tokens), key=lambda tokens: len(tokens)
        )
        if not shorter or len(longer) != len(shorter) + 1:
            return False
        return (
            longer[:len(shorter)] == shorter
            or longer[-len(shorter):] == shorter
        )

    def _rerank_table_scores(
        self, question: str,
        scored: list[tuple[dict[str, Any], float]],
    ) -> list[tuple[dict[str, Any], float]]:
        """Prefer a close-scoring base entity over an unrequested derivative.

        Example: Contract is favored over ContractCoefficient when their
        semantic scores are close and the question does not explicitly contain
        the compound table's extra identifier tokens. No concrete table or
        column names are encoded here.
        """
        question_tokens = set(self._identifier_tokens(question))
        candidates = []
        for item, score in scored:
            tokens = set(self._identifier_tokens(item["table"]))
            candidates.append((item, score, tokens))

        base_keys: set[tuple[str, str]] = set()
        derivative_keys: set[tuple[str, str]] = set()
        for compound, compound_score, compound_tokens in candidates:
            ordered_tokens = self._identifier_tokens(compound["table"])
            if len(ordered_tokens) < 2:
                continue
            possible_bases = [
                (base, base_score, base_tokens)
                for base, base_score, base_tokens in candidates
                if base["schema"] == compound["schema"]
                and base_tokens
                and base_tokens < compound_tokens
            ]
            if not possible_bases:
                continue
            # Check question compatibility before choosing a base. Otherwise a
            # high-scoring but explicitly different subset can prevent the
            # base actually named by the question from being promoted. For
            # example, Coefficient must not block Contract for a "contract"
            # question about ContractCoefficientItem.
            eligible_bases = []
            for base, base_score, base_tokens in possible_bases:
                extra_qualifiers = compound_tokens - base_tokens
                explicitly_requested = bool(
                    extra_qualifiers & question_tokens
                )
                score_gap = compound_score - base_score
                if (
                    not explicitly_requested
                    and 0 <= score_gap <= self.BASE_ENTITY_MARGIN
                ):
                    eligible_bases.append((base, base_score, base_tokens))

            if eligible_bases:
                base, base_score, _ = max(
                    eligible_bases, key=lambda candidate: candidate[1]
                )
                base_key = (base["schema"], base["table"])
                compound_key = (compound["schema"], compound["table"])
                base_keys.add(base_key)
                derivative_keys.add(compound_key)
                print(
                    f"[RAG] Base-entity rerank: {base['schema']}.{base['table']} "
                    f"over {compound['schema']}.{compound['table']}"
                )

        adjusted = []
        for item, score, _ in candidates:
            key = (item["schema"], item["table"])
            if key in base_keys:
                score += self.BASE_ENTITY_BONUS
            if key in derivative_keys:
                score -= self.DERIVATIVE_TABLE_PENALTY
            adjusted.append((item, score))
        return sorted(adjusted, key=lambda match: match[1], reverse=True)

    def _exact_tables(
        self, question: str, result: IntrospectionResult,
    ) -> list[tuple[str, str]]:
        normalized_question = question.casefold().replace("[", "").replace("]", "")
        normalized_question = normalized_question.replace('"', "").replace("'", "")
        matches = []
        for schema, table in result.table_metadata:
            qualified = f"{schema}.{table}".casefold()
            if re.search(rf"(?<![\w.]){re.escape(qualified)}(?![\w.])", normalized_question):
                matches.append((schema, table))
        return matches

    def _items(self, result: IntrospectionResult) -> dict[str, dict[str, Any]]:
        items: dict[str, dict[str, Any]] = {}
        for (schema, table), metadata in result.table_metadata.items():
            description = result.retrieval_table_description(schema, table)
            column_lines = []
            for column in metadata.get("columns", []):
                column_description = result.retrieval_column_description(
                    schema, table, column["name"]
                ) or column.get("comment") or column["name"]
                column_lines.append(f"{column['name']}: {column_description}")
                column_text = (
                    f"Table {schema}.{table}. Column {column['name']}. "
                    f"Type {column['type']}. Meaning {column_description}."
                )
                if column.get("primary_key"):
                    column_text += " Primary key."
                if column.get("references"):
                    column_text += f" References {column['references']}."
                items[f"column:{schema}.{table}.{column['name']}"] = {
                    "kind": "column", "schema": schema, "table": table,
                    "column": column, "text": column_text,
                }
            table_text = (
                f"Table {schema}.{table}. Purpose: {description}. Columns: "
                + "; ".join(column_lines)
            )
            items[f"table:{schema}.{table}"] = {
                "kind": "table", "schema": schema, "table": table,
                "text": table_text,
            }
        return items

    def _ensure_index(
        self, db_name: str, result: IntrospectionResult,
    ) -> _PersistentEmbeddingIndex:
        if db_name not in self.indexes:
            index = _PersistentEmbeddingIndex(
                self.embeddings, self.cache_dir / self._cache_name(db_name)
            )
            index.build(self._items(result))
            self.indexes[db_name] = index
        return self.indexes[db_name]

    def _select_tables(
        self, question: str, result: IntrospectionResult,
        index: _PersistentEmbeddingIndex, query_vector: list[float],
    ) -> list[tuple[str, str]]:
        exact = self._exact_tables(question, result)
        if exact:
            print(
                "[RAG][Trace] Exact table bypass: "
                + ", ".join(f"{schema}.{table}" for schema, table in exact)
            )
            return exact[:self.MAX_TABLES]

        dense = index.scores(query_vector, kind="table")[:self.FUSION_CANDIDATES]
        lexical = index.lexical_scores(
            question, kind="table"
        )[:self.FUSION_CANDIDATES]
        self._log_table_ranking(f"Dense top {self.FUSION_CANDIDATES}", dense)
        self._log_table_ranking(f"BM25 top {self.FUSION_CANDIDATES}", lexical)
        scored = self._fuse_scores(dense, lexical)[:self.FUSION_CANDIDATES]
        self._log_table_ranking(f"RRF fused top {self.FUSION_CANDIDATES}", scored)
        scored = scored[:self.TABLE_RERANK_CANDIDATES]
        scored = self._rerank_table_scores(question, scored)
        linked = self._llm_schema_link(question, scored, result)
        if linked:
            return linked
        scored = scored[:self.MAX_TABLES]
        self._log_table_ranking("Rule-adjusted top 8", scored, limit=self.MAX_TABLES)
        if not scored:
            return []

        threshold = max(self.MIN_SIMILARITY, scored[0][1] - self.TABLE_SCORE_WINDOW)
        selected = [
            (item["schema"], item["table"])
            for item, score in scored if score >= threshold
        ]
        print(
            f"[RAG][Trace] Final threshold={threshold:.6f} "
            f"(minimum={self.MIN_SIMILARITY:.2f}, "
            f"best-minus-window={scored[0][1] - self.TABLE_SCORE_WINDOW:.6f})"
        )
        print(
            "[RAG][Trace] Threshold survivors: "
            + (
                ", ".join(f"{schema}.{table}" for schema, table in selected)
                if selected else "<none; closest table fallback will be used>"
            )
        )
        # Always retain the closest table, even for an unusually low score.
        return selected or [(scored[0][0]["schema"], scored[0][0]["table"])]

    @staticmethod
    def _add_fk_referenced_tables(
        tables: list[tuple[str, str]], result: IntrospectionResult,
    ) -> list[tuple[str, str]]:
        """Add a bounded set of direct FK neighbors in both directions.

        Both referenced parents and referencing children can be necessary for
        a query. Only one hop and a small fixed number of additions are allowed
        so a highly connected table cannot flood the schema prompt.
        """
        expanded = list(tables)
        included = set(tables)
        additions = 0

        def add(target: tuple[str, str] | None) -> None:
            nonlocal additions
            if (
                target is not None
                and target not in included
                and additions < RAGLayer.MAX_FK_EXPANSION
            ):
                included.add(target)
                expanded.append(target)
                additions += 1

        # Outgoing relationships first: these are explicit dependencies of the
        # selected tables.
        for table_key in tables:
            metadata = result.table_metadata.get(table_key, {})
            for column in metadata.get("columns", []):
                reference = column.get("references")
                if not reference:
                    continue
                parts = str(reference).split(".", 2)
                if len(parts) != 3:
                    continue
                target = result.resolve_table(parts[0], parts[1])
                add(target)

        # Then add detail/child tables whose FK points at a selected table.
        selected = set(tables)
        for source_key, metadata in result.table_metadata.items():
            if additions >= RAGLayer.MAX_FK_EXPANSION:
                break
            for column in metadata.get("columns", []):
                reference = column.get("references")
                if not reference:
                    continue
                parts = str(reference).split(".", 2)
                if len(parts) != 3:
                    continue
                target = result.resolve_table(parts[0], parts[1])
                if target in selected:
                    add(source_key)
                    break
        return expanded

    def _select_columns(
        self, question: str, tables: list[tuple[str, str]],
        index: _PersistentEmbeddingIndex, query_vector: list[float],
        result: IntrospectionResult,
    ) -> dict[tuple[str, str], list[dict[str, Any]]]:
        dense = index.scores(query_vector, kind="column", tables=set(tables))
        lexical = index.lexical_scores(
            question, kind="column", tables=set(tables)
        )
        scored = self._fuse_scores(dense, lexical)
        by_table: dict[tuple[str, str], list[tuple[dict[str, Any], float]]] = {
            table: [] for table in tables
        }
        for item, score in scored:
            by_table[(item["schema"], item["table"])].append((item, score))

        normalized_question = self._normalized(question)
        selected: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for table, candidates in by_table.items():
            if not candidates:
                selected[table] = []
                continue

            # Small and medium tables are cheap enough to expose completely.
            # Semantic order still matters if the global prompt budget later
            # needs to truncate the combined schema.
            if len(candidates) <= self.ALL_COLUMNS_TABLE_LIMIT:
                structural = [
                    item["column"] for item, _ in candidates
                    if item["column"].get("primary_key")
                    or item["column"].get("references")
                ]
                chosen = structural + [
                    item["column"] for item, _ in candidates
                    if item["column"] not in structural
                ]
                selected[table] = chosen
                continue

            chosen: list[dict[str, Any]] = []
            # Keys are mandatory context. Do not let the semantic-column cap
            # remove a low-scoring join key.
            for item, _ in candidates:
                column = item["column"]
                if column.get("primary_key") or column.get("references"):
                    chosen.append(column)

            # Preserve explicitly named identifiers even if their semantic
            # score is unexpectedly low.
            for item, _ in candidates:
                column = item["column"]
                explicitly_named = self._normalized(column["name"]) in normalized_question
                if explicitly_named and column not in chosen:
                    chosen.append(column)

            # Embeddings establish priority, but the first twenty candidates
            # are retained without an additional hard similarity cutoff.
            for item, _ in candidates:
                if len(chosen) >= self.MAX_WIDE_TABLE_COLUMNS:
                    break
                column = item["column"]
                if column not in chosen:
                    chosen.append(column)
            if not chosen:
                chosen = [item["column"] for item, _ in candidates[:3]]

            # If a selected identifier has a very close sibling (Title and
            # Title_En, Value and Value2, etc.), retain it without assigning a
            # database-specific semantic role to either column.
            all_columns = [item["column"] for item, _ in candidates]
            for candidate in all_columns:
                if candidate in chosen:
                    continue
                if any(
                    self._identifier_variants(
                        candidate["name"], column["name"]
                    )
                    for column in chosen
                ):
                    chosen.append(candidate)
            selected[table] = chosen
        return selected

    @classmethod
    def _compact_schema(
        cls, tables: list[tuple[str, str]], columns: dict[tuple[str, str], list[dict]],
        result: IntrospectionResult,
    ) -> str:
        block_lines: dict[tuple[str, str], list[str]] = {}
        for schema, table in tables:
            description = result.table_descriptions.get((schema, table), "")
            lines = [f"TABLE [{schema}].[{table}]"]
            if description:
                lines.append(f"Purpose: {description}")
            lines.append("Available columns (ordered by relevance):")
            block_lines[(schema, table)] = lines

        current_characters = sum(
            len("\n".join(lines)) for lines in block_lines.values()
        ) + max(0, len(tables) - 1) * 2
        positions = {table: 0 for table in tables}
        omitted = {table: 0 for table in tables}

        # Allocate the shared budget round-robin so one very wide table cannot
        # consume all context before other selected tables receive columns.
        while True:
            progressed = False
            for schema, table in tables:
                table_key = (schema, table)
                table_columns = columns.get(table_key, [])
                position = positions[table_key]
                if position >= len(table_columns):
                    continue
                column = table_columns[position]
                details = [str(column["type"])]
                details.append("NULL" if column.get("nullable", True) else "NOT NULL")
                if column.get("primary_key"):
                    details.append("PRIMARY KEY")
                if column.get("references"):
                    details.append(f"REFERENCES {column['references']}")
                semantic = result.column_descriptions.get(
                    (schema, table, column["name"]), column.get("comment") or ""
                )
                suffix = f" -- {semantic}" if semantic else ""
                line = f"- [{column['name']}] {' '.join(details)}{suffix}"
                positions[table_key] += 1
                if current_characters + len(line) + 1 <= cls.MAX_SCHEMA_CHARACTERS:
                    block_lines[table_key].append(line)
                    current_characters += len(line) + 1
                    progressed = True
                else:
                    omitted[table_key] += 1
            if all(
                positions[table] >= len(columns.get(table, []))
                for table in tables
            ):
                break
            if not progressed:
                # Account for every candidate not visited after the budget was
                # exhausted, then stop without repeatedly scanning them.
                for table in tables:
                    remaining = len(columns.get(table, [])) - positions[table]
                    omitted[table] += max(0, remaining)
                    positions[table] += max(0, remaining)
                break

        omitted_total = sum(omitted.values())
        if omitted_total:
            print(
                f"[RAG] Schema budget omitted {omitted_total} lower-priority columns"
            )
            for table in tables:
                if omitted[table]:
                    block_lines[table].append(
                        f"- ... {omitted[table]} lower-priority columns omitted "
                        "by prompt budget"
                    )
        return "\n\n".join(
            "\n".join(block_lines[table]) for table in tables
        )

    def run(
        self, question: str, introspection_result: IntrospectionResult, db_name: str,
    ) -> str:
        index = self._ensure_index(db_name, introspection_result)
        query_vector = self.embeddings.embed_query(question)
        tables = self._select_tables(
            question, introspection_result, index, query_vector
        )
        if not tables:
            raise RuntimeError("No user tables were found in the active database.")
        tables = self._add_fk_referenced_tables(tables, introspection_result)
        columns = self._select_columns(
            question, tables, index, query_vector, introspection_result
        )
        print("[RAG] Selected tables: " + ", ".join(f"{s}.{t}" for s, t in tables))
        print(
            "[RAG] Selected columns: "
            + "; ".join(
                f"{schema}.{table}="
                + ",".join(column["name"] for column in columns[(schema, table)])
                for schema, table in tables
            )
        )
        return self._compact_schema(tables, columns, introspection_result)

    def clear(self, db_name: str | None = None) -> None:
        """Clear only in-memory indexes; disk vectors remain reusable."""
        if db_name:
            self.indexes.pop(db_name, None)
        else:
            self.indexes.clear()
