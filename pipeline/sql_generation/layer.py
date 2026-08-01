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

### Schema
{schema_text}

### Question
{question}

### SQL
SELECT"""

        response = self.llm.invoke([HumanMessage(content=prompt)])

        # Prepend SELECT since we primed the model with it
        sql = "SELECT " + response.content.strip()

        # Strip any markdown fences the model might have added
        sql = sql.replace("```sql", "").replace("```", "").strip()

        # Extract only the SQL part in case model added extra text before SELECT
        match = re.search(r'(SELECT|WITH|INSERT|UPDATE|DELETE)[\s\S]+', sql, re.IGNORECASE)
        if match:
            sql = match.group(0).strip()

        return sql