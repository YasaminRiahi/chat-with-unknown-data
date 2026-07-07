"""
pipeline/introspection/layer.py
================================
Layer 1 — Introspection  [BASIC]

Reads the database schema automatically:
tables, columns, types, sample values, foreign keys.
No human involvement — works on any unknown database.
"""

from sqlalchemy import inspect, text
from pipeline.base import BaseLayer


class IntrospectionLayer(BaseLayer):

    def run(self, db_name: str) -> list[dict]:
        """
        Returns:
            [
              {
                "table": "orders",
                "columns": [
                  {"name": "id", "type": "INTEGER", "samples": [1, 2, 3]},
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

        for table_name in inspector.get_table_names():
            columns      = inspector.get_columns(table_name)
            foreign_keys = inspector.get_foreign_keys(table_name)

            col_descriptors = []
            for col in columns:
                samples = self._sample_column(engine, table_name, col["name"])
                col_descriptors.append({
                    "name":    col["name"],
                    "type":    str(col["type"]),
                    "samples": samples,
                })

            tables.append({
                "table":        table_name,
                "columns":      col_descriptors,
                "foreign_keys": foreign_keys,
            })

        return tables

    def _sample_column(self, engine, table_name: str, col_name: str, n: int = 5) -> list:
        try:
            with engine.connect() as conn:
                sql    = f'SELECT DISTINCT "{col_name}" FROM "{table_name}" WHERE "{col_name}" IS NOT NULL LIMIT {n}'
                result = conn.execute(text(sql))
                return [row[0] for row in result.fetchall()]
        except Exception:
            return []
