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
    PROMPT_VERSION = 1
    MAX_BATCH_CHARACTERS = 24_000

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
    def _semantic_text(entry: dict[str, Any]) -> str:
        lines = [f"Semantic description: {entry.get('description', '').strip()}"]
        column_descriptions = entry.get("column_descriptions") or {}
        if column_descriptions:
            lines.append("Semantic column descriptions:")
            for name, description in column_descriptions.items():
                lines.append(f"- [{name}]: {description}")
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
- Descriptions should help English and Persian user questions retrieve the table.
- Use an empty description when the meaning cannot be inferred.
- Return JSON only in this exact shape:
{{"tables":[{{"id":"schema.table","description":"...","column_descriptions":{{"ExactColumn":"..."}},"sensitive":false}}]}}

Metadata:
{json.dumps(input_payload, ensure_ascii=False)}
"""
        response = self.llm.invoke([HumanMessage(content=prompt)])
        return self._parse_response(response.content)

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

        pending = [
            spec for spec in specs
            if not (
                cached_tables.get(spec["id"], {}).get("fingerprint")
                == spec["fingerprint"]
                and cached_tables.get(spec["id"], {}).get("prompt_version")
                == self.PROMPT_VERSION
            )
        ]

        if self.llm_enabled and pending:
            print(f"[Enrichment] LLM descriptions needed for {len(pending)} tables")
            for batch_number, batch in enumerate(self._batches(pending), start=1):
                try:
                    results = self._enrich_batch(batch)
                except Exception as exc:
                    print(
                        f"[Enrichment] WARNING - LLM batch {batch_number} failed: {exc}. "
                        "Using deterministic metadata for remaining tables."
                    )
                    break

                allowed = {spec["id"]: spec for spec in batch}
                for result in results:
                    table_id = str(result.get("id", ""))
                    if table_id not in allowed:
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
                        "description": str(result.get("description") or "").strip(),
                        "column_descriptions": descriptions,
                        "sensitive": result.get("sensitive") is True,
                    }
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
                introspection_result.table_descriptions[key] = str(
                    entry.get("description") or ""
                ).strip()
                for name, description in (
                    entry.get("column_descriptions") or {}
                ).items():
                    introspection_result.column_descriptions[
                        (spec["schema"], spec["table"], str(name))
                    ] = str(description).strip()
                document = semantic + "\n" + document
                semantic_count += 1
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
