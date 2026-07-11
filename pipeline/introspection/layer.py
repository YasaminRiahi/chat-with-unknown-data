"""
pipeline/introspection/layer.py
================================
Layer 1 — Introspection  [BASIC]

Reads the database schema automatically:
tables, columns, types, sample values, foreign keys.
No human involvement — works on any unknown database.

Updated to support SQL Server schemas (e.g. ACC.Account, AST.Asset)
"""

from sqlalchemy import inspect, text
from pipeline.base import BaseLayer

# SQL Server system schemas to skip
SYSTEM_SCHEMAS = {
    "sys", "INFORMATION_SCHEMA", "guest", "db_owner",
    "db_accessadmin", "db_securityadmin", "db_ddladmin",
    "db_backupoperator", "db_datareader", "db_datawriter",
    "db_denydatareader", "db_denydatawriter"
}


class IntrospectionLayer(BaseLayer):

    def run(self, db_name: str) -> list[dict]:
        """
        Returns:
            [
              {
                "table": "ACC.Account",
                "schema": "ACC",
                "columns": [
                  {"name": "Id", "type": "INTEGER", "samples": [1, 2, 3]},
                  ...
                ],
                "foreign_keys": [...]
              },
              ...
            ]

        TODO:
          - Also read views (inspector.get_view_names())
          - Read CHECK constraints (hints for enum-like columns)
          - Smarter sampling: avoid PII, prefer diverse values
          - Handle very large tables with TABLESAMPLE
        """
        engine    = self.db_manager.get_engine(db_name)
        inspector = inspect(engine)
        tables    = []

        for schema_name in inspector.get_schema_names():
            if schema_name in SYSTEM_SCHEMAS:
                continue

            for table_name in inspector.get_table_names(schema=schema_name):
                columns      = inspector.get_columns(table_name, schema=schema_name)
                foreign_keys = inspector.get_foreign_keys(table_name, schema=schema_name)

                col_descriptors = []
                for col in columns:
                    samples = self._sample_column(engine, schema_name, table_name, col["name"])
                    col_descriptors.append({
                        "name":    col["name"],
                        "type":    str(col["type"]),
                        "samples": samples,
                    })

                tables.append({
                    "table":        f"{schema_name}.{table_name}",
                    "schema":       schema_name,
                    "columns":      col_descriptors,
                    "foreign_keys": foreign_keys,
                })

        return tables

    def _sample_column(self, engine, schema_name: str, table_name: str, col_name: str, n: int = 5) -> list:
        try:
            with engine.connect() as conn:
                sql    = f'SELECT DISTINCT [{col_name}] FROM [{schema_name}].[{table_name}] WHERE [{col_name}] IS NOT NULL'
                result = conn.execute(text(sql))
                return [row[0] for row in result.fetchall()[:n]]
        except Exception:
            return []