"""
pipeline/self_correction/layer.py
===================================
Layer 5 — Self-Correction  [BASIC]

Runs the generated SQL. On failure, feeds the error back to the LLM and retries.

TODO improvements:
  - Add SQL safety check before execution (block DROP, DELETE, UPDATE)
  - Classify error types and use different fix strategies
  - Log all retries for evaluation / debugging
  - Detect infinite loops (same error twice → give up early)
"""

from langchain_core.messages import HumanMessage
from pipeline.base import BaseLayer


class SelfCorrectionLayer(BaseLayer):

    def run(self, sql: str, db_name: str, original_question: str,
            schema: list[dict], max_retries: int = 3) -> tuple[list[dict], str]:
        """
        Returns: (result_rows, final_sql)
        Raises RuntimeError if all retries fail.
        """
        last_error = None

        for attempt in range(max_retries):
            try:
                result = self.db_manager.execute_query(db_name, sql)
                return result, sql
            except Exception as e:
                last_error = str(e)
                print(f"[SelfCorrection] Attempt {attempt + 1} failed: {last_error}")
                if attempt < max_retries - 1:
                    sql = self._fix_sql(sql, last_error, original_question, schema)

        raise RuntimeError(
            f"SQL failed after {max_retries} attempts. Last error: {last_error}"
        )

    def _fix_sql(self, broken_sql: str, error: str,
                 question: str, schema: list[dict]) -> str:
        schema_text = self._schema_to_text(schema)
        prompt = f"""Fix this SQL query.

Original question: {question}

Schema:
{schema_text}

Broken SQL:
{broken_sql}

Error:
{error}

Return ONLY the corrected SQL, no explanation, no markdown fences.

Fixed SQL:"""

        response = self.llm.invoke([HumanMessage(content=prompt)])
        content = response.content.strip()
        # Extract only the SQL part — find first SELECT/WITH/INSERT
        import re
        match = re.search(r'(SELECT|WITH|INSERT|UPDATE|DELETE)[\s\S]+', content, re.IGNORECASE)
        fixed = match.group(0).strip() if match else content
        fixed = fixed.replace("```sql", "").replace("```", "").strip()
        return fixed

    def _schema_to_text(self, schema: list[dict]) -> str:
        lines = []
        for table in schema:
            lines.append(f"Table: {table['table']}")
            for col in table["columns"]:
                lines.append(f"  {col['name']} {col['type']}")
            lines.append("")
        return "\n".join(lines)
