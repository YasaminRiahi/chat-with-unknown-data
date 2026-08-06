"""Layer 6: turn successful SQL results into a concise user-facing answer."""

import json
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from pipeline.base import BaseLayer


class AnswerGenerationLayer(BaseLayer):
    """Summarize query results without inventing facts outside those results."""

    def run(self, question: str, sql: str, rows: list[dict[str, Any]]) -> str:
        if not rows:
            return "No matching records were found."

        prompt = f"""Original question:
{question}

SQL that was executed:
{sql}

Query result (JSON):
{json.dumps(rows, ensure_ascii=False, default=str)}

Write a concise, human-readable answer. State the direct answer first. Format
numbers clearly, summarize patterns when there are multiple rows, and mention
important findings. Do not mention SQL or JSON unless the user asked for them.
Use only facts present in the result."""

        response = self.llm.invoke([
            SystemMessage(content=(
                "You are the answer-generation layer of a Text-to-SQL system. "
                "Never add facts that are absent from the supplied query result."
            )),
            HumanMessage(content=prompt),
        ])
        return str(response.content).strip()
