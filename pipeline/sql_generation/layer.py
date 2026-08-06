"""
pipeline/sql_generation/layer.py
=================================
Layer 4 — SQL Generation  [BASIC]

Generates a SQL query from the user's question and the schema text from RAG Layer.

TODO improvements:
  - Add chain-of-thought: ask LLM to reason before writing SQL
  - Support few-shot examples generated automatically from schema
  - Post-process to strip markdown fences more robustly
  - Detect when question is not a data query (e.g. greetings) and skip SQL
"""

import re
from langchain_core.messages import HumanMessage
from pipeline.base import BaseLayer


class SQLGenerationLayer(BaseLayer):

    @staticmethod
    def _extract_sql(content: str) -> str:
        sql = content.replace("```sql", "").replace("```", "").strip()
        sql = re.sub(r"^(?:SELECT\s+){2,}", "SELECT ", sql, flags=re.IGNORECASE)
        match = re.search(r"\b(SELECT|WITH)\b[\s\S]+", sql, re.IGNORECASE)
        if not match:
            raise RuntimeError("The model did not return a read-only SQL query.")
        return match.group(0).strip()

    def run(self, question: str, schema_text: str) -> str:
        """
        Generates a T-SQL query for Microsoft SQL Server.

        Args:
            question:    Natural language question from the user
            schema_text: LLM-ready schema text from RAG Layer
                         (CREATE TABLE statements + sample rows)

        Returns:
            str: A valid T-SQL query string
        """
        prompt = f"""### Task
Generate a T-SQL query for Microsoft SQL Server.

### Rules
- Output ONLY the SQL query. Nothing else.
- No explanations, no comments, no markdown, no other languages.
- First word MUST be SELECT.
- Use square brackets for schema and table names: [ACC].[Account]
- Use TOP instead of LIMIT: SELECT TOP 100 ...
- Use table aliases for readability.
- For every Persian/non-ASCII string literal, use SQL Server Unicode syntax
  with an N prefix, for example: N'حسن انجام کار'.
- Prefer the simplest table that directly contains the requested value. Do not
  add a join unless the requested result requires it and the schema supports it.

### Schema
{schema_text}

### Question
{question}

### SQL"""

        response = self.llm.invoke([HumanMessage(content=prompt)])

        return self._extract_sql(str(response.content))
