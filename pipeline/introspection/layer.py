"""
pipeline/introspection/layer.py
================================
Layer 1 — Introspection

Uses LangChain's SQLDatabase to read all schemas automatically.
No human involvement — works on any unknown database.
"""

from dataclasses import dataclass, field
from sqlalchemy import inspect
from langchain_community.utilities import SQLDatabase
from pipeline.base import BaseLayer


@dataclass
class IntrospectionResult:
    """
    Result of the Introspection Layer.

    Holds one SQLDatabase per schema and provides helper methods
    for downstream layers (Enrichment, RAG, SQL Generation).
    """
    db_per_schema: dict = field(default_factory=dict)  # {schema_name: SQLDatabase}
    schemas: list = field(default_factory=list)         # ['ACC', 'AST', 'FMK', ...]
    enriched_table_info: dict[tuple[str, str], str] = field(default_factory=dict)
    semantic_table_info: dict[tuple[str, str], str] = field(default_factory=dict)
    table_metadata: dict[tuple[str, str], dict] = field(default_factory=dict)
    table_descriptions: dict[tuple[str, str], str] = field(default_factory=dict)
    column_descriptions: dict[tuple[str, str, str], str] = field(default_factory=dict)
    localized_table_descriptions: dict[
        tuple[str, str], dict[str, str]
    ] = field(default_factory=dict)
    localized_column_descriptions: dict[
        tuple[str, str, str], dict[str, str]
    ] = field(default_factory=dict)
    sensitive_tables: set[tuple[str, str]] = field(default_factory=set)

    @staticmethod
    def _localized_description(values: dict[str, str] | None) -> str:
        """Render language-labelled text for multilingual retrieval."""
        values = values or {}
        parts = []
        if values.get("en"):
            parts.append(f"English: {values['en']}")
        if values.get("fa"):
            parts.append(f"Persian: {values['fa']}")
        return "\n".join(parts)

    def retrieval_table_description(self, schema: str, table: str) -> str:
        key = (schema, table)
        localized = self._localized_description(
            self.localized_table_descriptions.get(key)
        )
        return localized or self.table_descriptions.get(key, "")

    def retrieval_column_description(
        self, schema: str, table: str, column: str,
    ) -> str:
        key = (schema, table, column)
        localized = self._localized_description(
            self.localized_column_descriptions.get(key)
        )
        return localized or self.column_descriptions.get(key, "")

    def get_full_schema_info(self) -> str:
        """
        Returns schema info for ALL tables in LLM-ready format.

        Example output:
            -- Schema: ACC
            CREATE TABLE [ACC].[Account] (...)
            /* 2 rows from Account: ... */

            -- Schema: AST
            CREATE TABLE [AST].[Asset] (...)
        """
        parts = []
        for schema, db in self.db_per_schema.items():
            parts.append(f"-- Schema: {schema}\n{db.get_table_info()}")
        return "\n\n".join(parts)

    def get_schema_info_for(self, schemas: list[str]) -> str:
        """
        Returns schema info only for the given list of schemas.
        Used by the RAG Layer to pass only relevant tables to the LLM.
        """
        parts = []
        for schema in schemas:
            if schema in self.db_per_schema:
                parts.append(f"-- Schema: {schema}\n{self.db_per_schema[schema].get_table_info()}")
        return "\n\n".join(parts)

    def get_all_table_names(self) -> list[str]:
        """
        Returns all table names in schema.table format.
        Example: ['ACC.Account', 'ACC.Voucher', 'AST.Asset', ...]
        """
        if self.table_metadata:
            return [f"{schema}.{table}" for schema, table in self.table_metadata]
        tables = []
        for schema, db in self.db_per_schema.items():
            for table in db.get_usable_table_names():
                tables.append(f"{schema}.{table}")
        return tables

    def resolve_table(self, schema: str, table: str) -> tuple[str, str] | None:
        """Resolve a qualified table name case-insensitively."""
        wanted = (schema.casefold(), table.casefold())
        for candidate in self.table_metadata:
            if (candidate[0].casefold(), candidate[1].casefold()) == wanted:
                return candidate
        return None

    def get_columns(self, schema: str, table: str) -> list[dict]:
        """Return authoritative structured column metadata for one table."""
        key = self.resolve_table(schema, table)
        if key is None:
            return []
        return list(self.table_metadata[key].get("columns", []))

    def iter_table_info(self):
        """Yield one retrievable schema document per table."""
        for schema, db in self.db_per_schema.items():
            for table in db.get_usable_table_names():
                try:
                    info = db.get_table_info(table_names=[table])
                except Exception as exc:
                    print(f"[Introspection] WARNING - skipping {schema}.{table}: {exc}")
                    continue
                yield schema, table, f"-- Schema: {schema}\n{info}"

    def iter_retrieval_documents(self):
        """Yield enriched table documents when enrichment is available."""
        for schema, table, table_info in self.iter_table_info():
            key = (schema, table)
            semantic = self.semantic_table_info.get(key, "")
            prompt_schema = (
                f"-- Semantic hints (may be incomplete; DDL is authoritative)\n"
                f"{semantic}\n{table_info}"
                if semantic else table_info
            )
            yield (
                schema,
                table,
                self.enriched_table_info.get(key, table_info),
                prompt_schema,
                key in self.sensitive_tables,
            )

    def get_db_for_schema(self, schema: str) -> SQLDatabase | None:
        """Returns the SQLDatabase object for a given schema."""
        return self.db_per_schema.get(schema)

    def summary(self) -> str:
        """Returns a short summary of what was found."""
        lines = [f"Found {len(self.schemas)} schemas:"]
        for schema, db in self.db_per_schema.items():
            count = len(db.get_usable_table_names())
            lines.append(f"  {schema}: {count} tables")
        return "\n".join(lines)


class IntrospectionLayer(BaseLayer):

    def run(self, db_name: str) -> IntrospectionResult:
        """
        Reads ALL schemas from the database and returns an IntrospectionResult.

        Steps:
        1. Use SQLAlchemy to discover all schema names
        2. Build one SQLDatabase per schema using LangChain
        3. Return results wrapped in IntrospectionResult

        TODO:
          - Cache results to disk to avoid re-reading on every query
          - Add support for views in addition to tables
          - Handle schemas where the user has no read permission
        """
        engine    = self.db_manager.get_engine(db_name)
        inspector = inspect(engine)

        system_schemas = {
            "information_schema", "sys", "guest",
            "db_owner", "db_accessadmin", "db_securityadmin",
            "db_ddladmin", "db_backupoperator", "db_datareader",
            "db_datawriter", "db_denydatareader", "db_denydatawriter",
        }
        all_schemas = [
            schema for schema in inspector.get_schema_names()
            if schema.lower() not in system_schemas
        ]
        print(f"[Introspection] Found {len(all_schemas)} schemas: {all_schemas}")

        db_per_schema = {}
        table_metadata = {}
        for schema in all_schemas:
            try:
                db_per_schema[schema] = SQLDatabase(
                    engine=engine,
                    schema=schema,
                    # DDL is sufficient for SQL generation; sample rows make
                    # wide/large schemas consume the chat model's token quota.
                    sample_rows_in_table_info=0,
                )
                table_count = len(db_per_schema[schema].get_usable_table_names())
                print(f"[Introspection] {schema}: {table_count} tables")
                for table in db_per_schema[schema].get_usable_table_names():
                    try:
                        columns = inspector.get_columns(table, schema=schema)
                        pk = inspector.get_pk_constraint(table, schema=schema) or {}
                        primary_keys = set(pk.get("constrained_columns") or [])
                        foreign_keys = {}
                        for fk in inspector.get_foreign_keys(table, schema=schema):
                            target_schema = fk.get("referred_schema") or schema
                            target_table = fk.get("referred_table") or "unknown"
                            for source, target in zip(
                                fk.get("constrained_columns") or [],
                                fk.get("referred_columns") or [],
                            ):
                                foreign_keys[str(source)] = (
                                    f"{target_schema}.{target_table}.{target}"
                                )
                        table_metadata[(schema, table)] = {
                            "schema": schema,
                            "table": table,
                            "columns": [
                                {
                                    "name": str(column["name"]),
                                    "type": str(column.get("type", "unknown")),
                                    "nullable": bool(column.get("nullable", True)),
                                    "comment": str(column.get("comment") or "").strip(),
                                    "primary_key": str(column["name"]) in primary_keys,
                                    "references": foreign_keys.get(str(column["name"])),
                                }
                                for column in columns
                            ],
                        }
                    except Exception as exc:
                        print(
                            f"[Introspection] WARNING - metadata for "
                            f"{schema}.{table}: {exc}"
                        )
            except Exception as e:
                print(f"[Introspection] WARNING — skipping schema '{schema}': {e}")

        result = IntrospectionResult(
            db_per_schema=db_per_schema,
            schemas=list(db_per_schema.keys()),
            table_metadata=table_metadata,
        )

        print(f"\n[Introspection] Summary:\n{result.summary()}")
        return result
