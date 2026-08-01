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
        tables = []
        for schema, db in self.db_per_schema.items():
            for table in db.get_usable_table_names():
                tables.append(f"{schema}.{table}")
        return tables

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

        all_schemas = inspector.get_schema_names()
        print(f"[Introspection] Found {len(all_schemas)} schemas: {all_schemas}")

        db_per_schema = {}
        for schema in all_schemas:
            try:
                db_per_schema[schema] = SQLDatabase(
                    engine=engine,
                    schema=schema,
                    sample_rows_in_table_info=2,
                )
                table_count = len(db_per_schema[schema].get_usable_table_names())
                print(f"[Introspection] {schema}: {table_count} tables")
            except Exception as e:
                print(f"[Introspection] WARNING — skipping schema '{schema}': {e}")

        result = IntrospectionResult(
            db_per_schema=db_per_schema,
            schemas=list(db_per_schema.keys())
        )

        print(f"\n[Introspection] Summary:\n{result.summary()}")
        return result