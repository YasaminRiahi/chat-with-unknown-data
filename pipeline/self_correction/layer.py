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
  - Handle empty result sets separately from errors
"""

import re
from langchain_core.messages import HumanMessage
from pipeline.base import BaseLayer


class SelfCorrectionLayer(BaseLayer):

    def run(self, sql: str, db_name: str, original_question: str,
            schema_text: str, max_retries: int = 3) -> tuple[list[dict], str]:
        """
        Runs the SQL query and retries with LLM correction on failure.

        Args:
            sql:               SQL query to execute
            db_name:           Name of the active database connection
            original_question: Original user question (for context in correction prompt)
            schema_text:       Schema text from RAG Layer (for correction context)
            max_retries:       Maximum number of correction attempts

        Returns:
            tuple: (result_rows, final_sql)

        Raises:
            RuntimeError: If all retries fail
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
                    sql = self._fix_sql(sql, last_error, original_question, schema_text)

        raise RuntimeError(
            f"SQL failed after {max_retries} attempts. Last error: {last_error}"
        )

    def _fix_sql(self, broken_sql: str, error: str,
                 question: str, schema_text: str) -> str:
        """
        Asks the LLM to fix a broken SQL query given the error message.

        Passes both the error message AND the schema so the LLM has
        full context to produce a correct fix.
        """
        prompt = f"""Fix this T-SQL query for Microsoft SQL Server.

Original question: {question}

Schema:
{schema_text}

Broken SQL:
{broken_sql}

Error:
{error}

Rules:
- Return ONLY the corrected SQL, no explanation, no markdown fences.
- First word MUST be SELECT.
- Use square brackets: [ACC].[Account]
- Use TOP instead of LIMIT.

Fixed SQL:
SELECT"""

        response = self.llm.invoke([HumanMessage(content=prompt)])

        # Prepend SELECT since we primed the model with it
        fixed = "SELECT " + response.content.strip()

        # Strip markdown fences
        fixed = fixed.replace("```sql", "").replace("```", "").strip()

        # Extract only the SQL part in case model added extra text
        match = re.search(r'(SELECT|WITH|INSERT|UPDATE|DELETE)[\s\S]+', fixed, re.IGNORECASE)
        if match:
            fixed = match.group(0).strip()

        return fixed