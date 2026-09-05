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
from pipeline.sql_safety import contains_forbidden_sql, ensure_read_only_sql


class SQLGenerationLayer(BaseLayer):

    @staticmethod
    def _extract_sql(content: str) -> str:
        sql = content.replace("```sql", "").replace("```", "").strip()
        sql = re.sub(r"^(?:SELECT\s+){2,}", "SELECT ", sql, flags=re.IGNORECASE)
        match = re.search(r"\b(SELECT|WITH)\b[\s\S]+", sql, re.IGNORECASE)
        if not match:
            if contains_forbidden_sql(sql):
                ensure_read_only_sql(sql)
            raise RuntimeError("The model did not return a read-only SQL query.")
        return ensure_read_only_sql(match.group(0).strip())

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
- The query MUST be read-only. Never generate INSERT, UPDATE, DELETE, MERGE,
  DROP, ALTER, TRUNCATE, EXEC, CREATE, GRANT, REVOKE, DBCC, BACKUP, or RESTORE.
- Return one SELECT query only; do not append a second statement after a
  semicolon.
- Use square brackets for schema and table names: [ACC].[Account]
- Use TOP instead of LIMIT: SELECT TOP 100 ...
- Use table aliases for readability.
- For every Persian/non-ASCII string literal, use SQL Server Unicode syntax
  with an N prefix, for example: N'حسن انجام کار'.
- Prefer the simplest table that directly contains the requested value. Do not
  add a join unless the requested result requires it and the schema supports it.
- Match date/time filtering to the precision stated by the user. A calendar
  date without a time means the entire day, not midnight. A date with only an
  hour means the entire hour; with an hour and minute, the entire minute; and
  with seconds, the entire second. Do not invent time components the user did
  not provide.
- For a datetime-like column, express those periods as index-friendly half-open
  ranges: column >= period_start AND column < next_period_start. For example,
  a request for 2019-03-31 must use >= '20190331' AND < '20190401', rather than
  equality, CAST(column AS date), BETWEEN, or an end-of-day value. Keep an
  explicitly requested exact timestamp exact only when the user's wording
  clearly requires exact equality.

### Schema
{schema_text}

### Question
{question}

### SQL"""

        response = self.llm.invoke([HumanMessage(content=prompt)])

        return self._extract_sql(str(response.content))
