"""
pipeline/sql_generation/layer.py
=================================
Layer 4 — SQL Generation  [BASIC]

Generates a SQL query from the user's question and the enriched/filtered schema.

TODO improvements:
  - Detect SQL dialect (SQLite vs PostgreSQL have syntax differences)
  - Add chain-of-thought: ask LLM to reason before writing SQL
  - Support few-shot examples if user provides them
  - Post-process to strip markdown fences more robustly
"""

from langchain_core.messages import HumanMessage
from pipeline.base import BaseLayer


class SQLGenerationLayer(BaseLayer):

    def run(self, question: str, schema: list[dict]) -> str:
        schema_text = self._schema_to_text(schema)

        prompt = f"""You are a SQL expert. Generate a SQL query to answer the user's question.

Database schema:
{schema_text}

Rules:
- Return ONLY the SQL query, no explanation, no markdown fences
- Use standard SQL compatible with both SQLite and PostgreSQL
- Use table aliases for readability
- Limit results to 100 rows unless the user specifies otherwise

Question: {question}

SQL:"""

        response = self.llm.invoke([HumanMessage(content=prompt)])
        sql      = response.content.strip()
        sql      = sql.replace("```sql", "").replace("```", "").strip()
        return sql

    def _schema_to_text(self, schema: list[dict]) -> str:
        lines = []
        for table in schema:
            lines.append(f"Table: {table['table']}")
            for col in table["columns"]:
                desc    = f" — {col['description']}" if col.get("description") else ""
                samples = f" (e.g. {col['samples'][:3]})" if col.get("samples") else ""
                lines.append(f"  {col['name']} {col['type']}{desc}{samples}")
            for fk in table.get("foreign_keys", []):
                lines.append(
                    f"  FK: {fk['constrained_columns']} → "
                    f"{fk['referred_table']}.{fk['referred_columns']}"
                )
            lines.append("")
        return "\n".join(lines)
