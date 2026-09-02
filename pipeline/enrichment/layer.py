"""Layer 2: persistent semantic enrichment for database metadata."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from langchain_core.messages import HumanMessage
from sqlalchemy import inspect

from pipeline.base import BaseLayer
from pipeline.introspection.layer import IntrospectionResult


class EnrichmentLayer(BaseLayer):
    """Combine safe metadata hints with cached LLM-generated descriptions."""

    CACHE_VERSION = 1
    # Keep the established English cache contract stable. Persian enrichment
    # is additive and has an independently bumpable prompt version.
    PROMPT_VERSION = 1
    PERSIAN_PROMPT_VERSION = 1
    # Bilingual responses are substantially larger than the metadata input.
    # Keep requests bounded so wide schemas do not exhaust the model's output
    # limit before it can return both languages.
    MAX_BATCH_CHARACTERS = 12_000

    SENSITIVE_TERMS = {
        "password", "passwd", "pwd", "secret", "token", "api_key", "apikey",
        "private_key", "national_id", "nationalcode", "ssn", "passport",
        "email", "phone", "mobile", "address", "birth", "salary", "iban",
        "bank_account", "card_number", "credit_card", "cvv",
    }

    def __init__(
        self,
        llm,
        embeddings,
        db_manager,
        cache_dir: str = ".cache/enrichment",
        llm_enabled: bool = True,
        batch_size: int = 12,
    ):
        super().__init__(llm, embeddings, db_manager)
        self.cache_dir = Path(cache_dir)
        self.llm_enabled = llm_enabled
        self.batch_size = max(1, batch_size)

    @staticmethod
    def _humanize(identifier: str) -> str:
        value = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", identifier)
        value = re.sub(r"[_\-.]+", " ", value)
        return re.sub(r"\s+", " ", value).strip()

    @classmethod
    def _sensitive_columns(cls, column_names: list[str]) -> list[str]:
        matches = []
        for name in column_names:
            normalized = re.sub(
                r"[^a-z0-9]+", "_", cls._humanize(name).lower()
            ).strip("_")
            if any(
                term == normalized
                or term in normalized.split("_")
                or ("_" in term and term in normalized)
                for term in cls.SENSITIVE_TERMS
            ):
                matches.append(name)
        return matches

    @staticmethod
    def _fingerprint(ddl: str) -> str:
        return hashlib.sha256(ddl.encode("utf-8")).hexdigest()

    def _cache_path(self, db_name: str) -> Path:
        slug = re.sub(r"[^a-zA-Z0-9_.-]+", "_", db_name).strip("_") or "database"
        suffix = hashlib.sha256(db_name.encode("utf-8")).hexdigest()[:10]
        return self.cache_dir / f"{slug}-{suffix}.json"

    def _model_name(self) -> str:
        model = getattr(self.llm, "model", self.llm)
        return str(
            getattr(model, "model_name", None)
            or getattr(model, "model", None)
            or type(model).__name__
        )

    def _load_cache(self, db_name: str) -> dict[str, Any]:
        path = self._cache_path(db_name)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if payload.get("cache_version") == self.CACHE_VERSION:
                return payload
        except FileNotFoundError:
            pass
        except (OSError, json.JSONDecodeError) as exc:
            print(f"[Enrichment] WARNING - cannot read cache {path}: {exc}")
        return {"cache_version": self.CACHE_VERSION, "tables": {}}

    def _save_cache(self, db_name: str, cache: dict[str, Any]) -> None:
        path = self._cache_path(db_name)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        temporary.replace(path)

    def _metadata_for_table(
        self, inspector, schema: str, table: str, ddl: str
    ) -> dict[str, Any]:
        columns = inspector.get_columns(table, schema=schema)
        pk_info = inspector.get_pk_constraint(table, schema=schema) or {}
        primary_keys = set(pk_info.get("constrained_columns") or [])

        foreign_keys: dict[str, str] = {}
        for fk in inspector.get_foreign_keys(table, schema=schema):
            target_schema = fk.get("referred_schema") or schema
            target_table = fk.get("referred_table") or "unknown"
            for source, target in zip(
                fk.get("constrained_columns") or [],
                fk.get("referred_columns") or [],
            ):
                foreign_keys[str(source)] = f"{target_schema}.{target_table}.{target}"

        column_specs = []
        for column in columns:
            name = str(column["name"])
            column_specs.append({
                "name": name,
                "type": str(column.get("type", "unknown")),
                "nullable": bool(column.get("nullable", True)),
                "comment": str(column.get("comment") or "").strip(),
                "primary_key": name in primary_keys,
                "references": foreign_keys.get(name),
            })

        return {
            "id": f"{schema}.{table}",
            "schema": schema,
            "table": table,
            "ddl": ddl,
            "fingerprint": self._fingerprint(ddl),
            "columns": column_specs,
            "sensitive_columns": self._sensitive_columns(
                [column["name"] for column in column_specs]
            ),
        }

    def _deterministic_document(self, spec: dict[str, Any]) -> str:
        lines = [
            f"Table: [{spec['schema']}].[{spec['table']}]",
            f"Name words: {self._humanize(spec['schema'])} / "
            f"{self._humanize(spec['table'])}",
        ]
        if spec["sensitive_columns"]:
            lines.append(
                "Potentially sensitive columns: "
                + ", ".join(spec["sensitive_columns"])
            )
        lines.append("Column meanings and relationships:")
        for column in spec["columns"]:
            properties = [column["type"]]
            properties.append("nullable" if column["nullable"] else "required")
            if column["primary_key"]:
                properties.append("primary key")
            if column["references"]:
                properties.append(f"references {column['references']}")
            meaning = column["comment"] or self._humanize(column["name"])
            lines.append(
                f"- [{column['name']}]: {meaning} ({', '.join(properties)})"
            )
        lines.extend(["SQL definition:", spec["ddl"]])
        return "\n".join(lines)

    @staticmethod
    def _english_description(entry: dict[str, Any]) -> str:
        value = (
            entry.get("description")
            if "description" in entry
            else entry.get("description_en", "")
        )
        return str(value or "").strip()

    @staticmethod
    def _english_column_descriptions(entry: dict[str, Any]) -> dict[str, Any]:
        value = (
            entry.get("column_descriptions")
            if "column_descriptions" in entry
            else entry.get("column_descriptions_en", {})
        )
        return value if isinstance(value, dict) else {}

    @classmethod
    def _semantic_text(cls, entry: dict[str, Any]) -> str:
        description_en = cls._english_description(entry)
        description_fa = str(entry.get("description_fa") or "").strip()
        lines = []
        if description_en:
            lines.append(f"Semantic description (English): {description_en}")
        if description_fa:
            lines.append(f"Semantic description (Persian): {description_fa}")

        descriptions_en = cls._english_column_descriptions(entry)
        descriptions_fa = entry.get("column_descriptions_fa") or {}
        names = list(dict.fromkeys([*descriptions_en, *descriptions_fa]))
        if names:
            lines.append("Semantic column descriptions (English / Persian):")
            for name in names:
                localized = []
                if descriptions_en.get(name):
                    localized.append(f"English: {descriptions_en[name]}")
                if descriptions_fa.get(name):
                    localized.append(f"Persian: {descriptions_fa[name]}")
                lines.append(f"- [{name}]: {'; '.join(localized)}")
        return "\n".join(lines)

    def _prompt_spec(self, spec: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": spec["id"],
            "schema": spec["schema"],
            "table": spec["table"],
            "columns": spec["columns"],
        }

    def _batches(self, specs: list[dict[str, Any]]):
        batch: list[dict[str, Any]] = []
        size = 0
        for spec in specs:
            encoded = json.dumps(self._prompt_spec(spec), ensure_ascii=False)
            if batch and (
                len(batch) >= self.batch_size
                or size + len(encoded) > self.MAX_BATCH_CHARACTERS
            ):
                yield batch
                batch, size = [], 0
            batch.append(spec)
            size += len(encoded)
        if batch:
            yield batch

    @staticmethod
    def _parse_response(content: Any) -> list[dict[str, Any]]:
        text = str(content).strip().replace("```json", "").replace("```", "")
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("LLM enrichment response did not contain a JSON object")
        payload = json.loads(text[start:end + 1])
        tables = payload.get("tables")
        if not isinstance(tables, list):
            raise ValueError("LLM enrichment response is missing a tables array")
        return [table for table in tables if isinstance(table, dict)]

    def _enrich_batch(self, specs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        input_payload = [self._prompt_spec(spec) for spec in specs]
        prompt = f"""You enrich database schemas for semantic table retrieval.

For each supplied table, infer its likely business purpose and concise column
meanings from names, types, comments, and relationships. Be conservative:
- Never invent entities or rules unsupported by the metadata.
- Keep original identifiers exactly unchanged.
- Descriptions should help English user questions retrieve the table.
- Use an empty description when the meaning cannot be inferred.
- Return JSON only in this exact shape:
{{"tables":[{{"id":"schema.table","description":"...","column_descriptions":{{"ExactColumn":"..."}},"sensitive":false}}]}}

Metadata:
{json.dumps(input_payload, ensure_ascii=False)}
"""
        response = self.llm.invoke([HumanMessage(content=prompt)])
        return self._parse_response(response.content)

    def _translate_batch(
        self, specs: list[dict[str, Any]], cached_tables: dict[str, Any],
    ) -> list[dict[str, Any]]:
        input_payload = []
        for spec in specs:
            entry = cached_tables[spec["id"]]
            input_payload.append({
                "id": spec["id"],
                "description_en": self._english_description(entry),
                "column_descriptions_en": self._english_column_descriptions(entry),
            })
        return self._translate_payload(input_payload)

    def _translate_payload(
        self, input_payload: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        prompt = f"""Translate existing English database schema enrichment into Persian for semantic retrieval.

Rules:
- Translate only the supplied descriptions; do not infer new business rules.
- Use natural Persian ERP and accounting terminology, not transliteration.
- Keep every table id and column identifier exactly unchanged.
- Preserve empty descriptions as empty strings.
- Keep column descriptions concise (prefer 2-12 words).
- Return every supplied table, even when some descriptions are empty.
- Return JSON only in this exact shape:
{{"tables":[{{"id":"schema.table","description_fa":"...","column_descriptions_fa":{{"ExactColumn":"..."}}}}]}}

Existing English enrichment:
{json.dumps(input_payload, ensure_ascii=False)}
"""
        response = self.llm.invoke([HumanMessage(content=prompt)])
        results = self._parse_response(response.content)
        expected = {item["id"]: item for item in input_payload}
        received: dict[str, dict[str, Any]] = {}
        for result in results:
            table_id = str(result.get("id", ""))
            if table_id not in expected or table_id in received:
                raise ValueError("Persian response contained an unknown or duplicate table")
            if not {
                "description_fa", "column_descriptions_fa",
            }.issubset(result):
                raise ValueError(f"Incomplete Persian translation for {table_id}")
            descriptions = result.get("column_descriptions_fa")
            if not isinstance(descriptions, dict):
                raise ValueError(f"Invalid Persian column descriptions for {table_id}")
            expected_columns = set(
                expected[table_id].get("column_descriptions_en") or {}
            )
            if set(map(str, descriptions)) != expected_columns:
                raise ValueError(
                    f"Persian response omitted or changed columns for {table_id}"
                )
            received[table_id] = result
        if set(received) != set(expected):
            raise ValueError("Persian response omitted one or more tables")
        return [received[item["id"]] for item in input_payload]

    def _translate_resilient(
        self, specs: list[dict[str, Any]], cached_tables: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Retry truncated JSON with smaller table and column payloads."""
        try:
            return self._translate_batch(specs, cached_tables)
        except Exception as exc:
            if len(specs) > 1:
                midpoint = len(specs) // 2
                print(
                    f"[Enrichment] Persian response was invalid ({exc}); "
                    f"retrying as {midpoint} + {len(specs) - midpoint} tables"
                )
                return (
                    self._translate_resilient(specs[:midpoint], cached_tables)
                    + self._translate_resilient(specs[midpoint:], cached_tables)
                )
            return [self._translate_wide_table(specs[0], cached_tables, exc)]

    def _translate_wide_table(
        self, spec: dict[str, Any], cached_tables: dict[str, Any],
        original_error: Exception,
    ) -> dict[str, Any]:
        """Recursively translate one table's columns when one output is too large."""
        entry = cached_tables[spec["id"]]
        description = self._english_description(entry)
        columns = list(self._english_column_descriptions(entry).items())

        def translate_chunk(items: list[tuple[str, Any]]) -> dict[str, Any]:
            payload = [{
                "id": spec["id"],
                "description_en": description,
                "column_descriptions_en": dict(items),
            }]
            try:
                return self._translate_payload(payload)[0]
            except Exception as exc:
                if len(items) <= 1:
                    raise RuntimeError(
                        f"Persian translation failed for {spec['id']} even "
                        "after reducing it to one column"
                    ) from exc
                midpoint = len(items) // 2
                print(
                    f"[Enrichment] Persian response for {spec['id']} was "
                    f"invalid ({exc}); splitting {len(items)} columns"
                )
                left = translate_chunk(items[:midpoint])
                right = translate_chunk(items[midpoint:])
                return {
                    "id": spec["id"],
                    "description_fa": (
                        left.get("description_fa")
                        or right.get("description_fa")
                        or ""
                    ),
                    "column_descriptions_fa": {
                        **left["column_descriptions_fa"],
                        **right["column_descriptions_fa"],
                    },
                }

        if len(columns) <= 1:
            # Retry once for a transient malformed response. There is no
            # smaller safe payload to split after this point.
            try:
                return translate_chunk(columns)
            except Exception as exc:
                raise RuntimeError(
                    f"Persian translation failed for {spec['id']}: "
                    f"{original_error}"
                ) from exc

        midpoint = len(columns) // 2
        print(
            f"[Enrichment] Persian response for {spec['id']} was invalid "
            f"({original_error}); splitting {len(columns)} columns"
        )
        left = translate_chunk(columns[:midpoint])
        right = translate_chunk(columns[midpoint:])
        return {
            "id": spec["id"],
            "description_fa": (
                left.get("description_fa") or right.get("description_fa") or ""
            ),
            "column_descriptions_fa": {
                **left["column_descriptions_fa"],
                **right["column_descriptions_fa"],
            },
        }

    @classmethod
    def _has_current_english(
        cls, entry: dict[str, Any], fingerprint: str,
    ) -> bool:
        if entry.get("fingerprint") != fingerprint:
            return False
        legacy = (
            entry.get("prompt_version") == cls.PROMPT_VERSION
            and "description" in entry
            and "column_descriptions" in entry
        )
        # Also preserve valid English from the short-lived bilingual cache
        # format if it was produced before this additive migration.
        explicit = (
            "description_en" in entry and "column_descriptions_en" in entry
        )
        return legacy or explicit

    def run(self, introspection_result: IntrospectionResult, db_name: str) -> IntrospectionResult:
        if introspection_result.enriched_table_info:
            return introspection_result

        cache = self._load_cache(db_name)
        cached_tables = cache.setdefault("tables", {})
        specs: list[dict[str, Any]] = []

        for schema, table, ddl in introspection_result.iter_table_info():
            try:
                metadata = introspection_result.table_metadata.get((schema, table))
                if metadata is None:
                    inspector = inspect(self.db_manager.get_engine(db_name))
                    spec = self._metadata_for_table(inspector, schema, table, ddl)
                else:
                    columns = list(metadata.get("columns", []))
                    spec = {
                        "id": f"{schema}.{table}",
                        "schema": schema,
                        "table": table,
                        "ddl": ddl,
                        "fingerprint": self._fingerprint(ddl),
                        "columns": columns,
                        "sensitive_columns": self._sensitive_columns(
                            [column["name"] for column in columns]
                        ),
                    }
            except Exception as exc:
                print(f"[Enrichment] WARNING - basic metadata for {schema}.{table}: {exc}")
                spec = {
                    "id": f"{schema}.{table}", "schema": schema, "table": table,
                    "ddl": ddl, "fingerprint": self._fingerprint(ddl),
                    "columns": [], "sensitive_columns": [],
                }
            specs.append(spec)

        english_pending = [
            spec for spec in specs
            if not self._has_current_english(
                cached_tables.get(spec["id"], {}), spec["fingerprint"]
            )
        ]

        if self.llm_enabled and english_pending:
            print(
                f"[Enrichment] English descriptions needed for "
                f"{len(english_pending)} tables"
            )
            for batch_number, batch in enumerate(
                self._batches(english_pending), start=1
            ):
                try:
                    results = self._enrich_batch(batch)
                except Exception as exc:
                    print(
                        f"[Enrichment] WARNING - English batch {batch_number} "
                        f"failed: {exc}. Using deterministic metadata for this batch."
                    )
                    continue

                allowed = {spec["id"]: spec for spec in batch}
                for result in results:
                    table_id = str(result.get("id", ""))
                    if table_id not in allowed:
                        continue
                    if not {"description", "column_descriptions"}.issubset(result):
                        print(
                            f"[Enrichment] WARNING - incomplete English "
                            f"description for {table_id}; it will be retried "
                            "after the metadata cache is refreshed"
                        )
                        continue
                    spec = allowed[table_id]
                    valid_columns = {column["name"] for column in spec["columns"]}
                    raw_descriptions = result.get("column_descriptions") or {}
                    if not isinstance(raw_descriptions, dict):
                        raw_descriptions = {}
                    descriptions = {
                        str(name): str(description).strip()
                        for name, description in raw_descriptions.items()
                        if str(name) in valid_columns and str(description).strip()
                    }
                    cached_tables[table_id] = {
                        "fingerprint": spec["fingerprint"],
                        "prompt_version": self.PROMPT_VERSION,
                        "model": self._model_name(),
                        "description": str(
                            result.get("description") or ""
                        ).strip(),
                        "column_descriptions": descriptions,
                        "sensitive": result.get("sensitive") is True,
                    }
                self._save_cache(db_name, cache)

        persian_pending = [
            spec for spec in specs
            if self._has_current_english(
                cached_tables.get(spec["id"], {}), spec["fingerprint"]
            )
            and not (
                cached_tables[spec["id"]].get("persian_prompt_version")
                == self.PERSIAN_PROMPT_VERSION
                and "description_fa" in cached_tables[spec["id"]]
                and "column_descriptions_fa" in cached_tables[spec["id"]]
            )
        ]

        if self.llm_enabled and persian_pending:
            print(
                f"[Enrichment] Persian translations needed for "
                f"{len(persian_pending)} tables"
            )
            for batch_number, batch in enumerate(
                self._batches(persian_pending), start=1
            ):
                try:
                    results = self._translate_resilient(batch, cached_tables)
                except Exception as exc:
                    print(
                        f"[Enrichment] WARNING - Persian batch {batch_number} "
                        f"failed: {exc}. English enrichment is unchanged."
                    )
                    continue

                allowed = {spec["id"]: spec for spec in batch}
                for result in results:
                    table_id = str(result.get("id", ""))
                    if table_id not in allowed:
                        continue
                    if not {
                        "description_fa", "column_descriptions_fa",
                    }.issubset(result):
                        print(
                            f"[Enrichment] WARNING - incomplete Persian "
                            f"translation for {table_id}; English is unchanged"
                        )
                        continue
                    spec = allowed[table_id]
                    valid_columns = {column["name"] for column in spec["columns"]}
                    raw_descriptions = result.get("column_descriptions_fa") or {}
                    if not isinstance(raw_descriptions, dict):
                        raw_descriptions = {}
                    descriptions_fa = {
                        str(name): str(description).strip()
                        for name, description in raw_descriptions.items()
                        if str(name) in valid_columns and str(description).strip()
                    }
                    entry = cached_tables[table_id]
                    entry["description_fa"] = str(
                        result.get("description_fa") or ""
                    ).strip()
                    entry["column_descriptions_fa"] = descriptions_fa
                    entry["persian_prompt_version"] = self.PERSIAN_PROMPT_VERSION
                    entry["persian_model"] = self._model_name()
                self._save_cache(db_name, cache)

        semantic_count = 0
        for spec in specs:
            key = (spec["schema"], spec["table"])
            introspection_result.table_metadata[key] = {
                "schema": spec["schema"],
                "table": spec["table"],
                "columns": list(spec["columns"]),
                "fingerprint": spec["fingerprint"],
            }
            document = self._deterministic_document(spec)
            entry = cached_tables.get(spec["id"])
            if entry and entry.get("fingerprint") == spec["fingerprint"]:
                semantic = self._semantic_text(entry)
                introspection_result.semantic_table_info[key] = semantic
                localized_table = {
                    "en": self._english_description(entry),
                    "fa": str(entry.get("description_fa") or "").strip(),
                }
                introspection_result.localized_table_descriptions[key] = (
                    localized_table
                )
                introspection_result.table_descriptions[key] = localized_table["en"]
                descriptions_by_language = {
                    "en": self._english_column_descriptions(entry),
                    "fa": entry.get("column_descriptions_fa") or {},
                }
                for language, descriptions in descriptions_by_language.items():
                    for name, description in descriptions.items():
                        column_key = (spec["schema"], spec["table"], str(name))
                        localized_column = (
                            introspection_result.localized_column_descriptions
                            .setdefault(column_key, {})
                        )
                        localized_column[language] = str(description).strip()
                        if language == "en":
                            introspection_result.column_descriptions[column_key] = (
                                str(description).strip()
                            )
                document = semantic + "\n" + document
                semantic_count += bool(semantic)
                if entry.get("sensitive"):
                    introspection_result.sensitive_tables.add(key)
            if spec["sensitive_columns"]:
                introspection_result.sensitive_tables.add(key)
            introspection_result.enriched_table_info[key] = document

        print(
            f"[Enrichment] Prepared {len(specs)} tables; "
            f"{semantic_count} have cached LLM descriptions; "
            f"{len(introspection_result.sensitive_tables)} flagged as potentially sensitive"
        )
        return introspection_result
