"""Layer 6: turn successful SQL results into a concise user-facing answer."""

import json
import re
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from pipeline.base import BaseLayer


class AnswerGenerationLayer(BaseLayer):
    """Summarize query results without inventing facts outside those results."""

    def run(self, question: str, sql: str, rows: list[dict[str, Any]]) -> str:
        is_persian = bool(re.search(r"[\u0600-\u06ff]", str(question or "")))
        if not rows:
            return (
                "هیچ رکورد منطبقی یافت نشد."
                if is_persian else "No matching records were found."
            )

        prompt = f"""Original question:
{question}

SQL that was executed:
{sql}

Query result (JSON):
{json.dumps(rows, ensure_ascii=False, default=str)}

Write a concise, human-readable answer. State the direct answer first. Format
numbers clearly and mention important findings. For multiple rows, do not list
every row and never create a Markdown table because the frontend visualizes the
complete result. Instead, write a "Key observations" heading followed by 2 to 4
short bullets covering only useful patterns or extremes such as the largest,
next-largest, and smallest values. Do not mention SQL, JSON, charts, or tables
unless the user asked for them. Use only facts present in the result. Answer in
the same language as the original question."""

        response = self.llm.invoke([
            SystemMessage(content=(
                "You are the answer-generation layer of a Text-to-SQL system. "
                "Never add facts that are absent from the supplied query result."
            )),
            HumanMessage(content=prompt),
        ])
        answer = str(response.content).strip()
        # Enforce the UI contract even if the model ignores the no-table
        # instruction. The complete rows remain available in the visualization.
        answer = "\n".join(
            line for line in answer.splitlines()
            if not (line.strip().startswith("|") and line.strip().endswith("|"))
        ).strip()
        if answer:
            return answer
        return (
            "نتیجهٔ کامل در بخش مصورسازی نمایش داده شده است."
            if is_persian
            else "The complete result is shown in the visualization."
        )
