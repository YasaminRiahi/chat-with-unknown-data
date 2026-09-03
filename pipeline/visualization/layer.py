"""Build display metadata from query rows without changing the query or rows."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from numbers import Number
import re
from typing import Any


class VisualizationLayer:
    """Suggest a conservative visualization from executed query results."""

    TEMPORAL_NAME_HINTS = (
        "date", "time", "day", "week", "month", "quarter", "year",
        "\u062a\u0627\u0631\u06cc\u062e", "\u0631\u0648\u0632", "\u0647\u0641\u062a\u0647",
        "\u0645\u0627\u0647", "\u0641\u0635\u0644", "\u0633\u0627\u0644",
    )
    RECORD_LIST_PATTERN = re.compile(
        r"\b(records?|rows?|details?)\b|"
        r"\b(?:list|latest|recent)\b.*"
        r"\b(?:receipts?|orders?|items?|entries|transactions?)\b|"
        r"(?:\u0631\u06a9\u0648\u0631\u062f|\u0631\u062f\u06cc\u0641|\u0641\u0647\u0631\u0633\u062a|"
        r"\u0644\u06cc\u0633\u062a|\u062c\u0632\u0626\u06cc\u0627\u062a)",
        re.IGNORECASE,
    )
    AGGREGATE_PATTERN = re.compile(
        r"\b(count|number\s+of|total|sum|average|avg|minimum|maximum|min|max)\b|"
        r"\bgroup(?:ed)?\s+by\b|"
        r"(?:\u062a\u0639\u062f\u0627\u062f|\u0645\u062c\u0645\u0648\u0639|\u0645\u06cc\u0627\u0646\u06af\u06cc\u0646|"
        r"\u062d\u062f\u0627\u0642\u0644|\u062d\u062f\u0627\u06a9\u062b\u0631|\u0628\u0647\s*\u062a\u0641\u06a9\u06cc\u06a9)",
        re.IGNORECASE,
    )
    MAX_CHART_COLUMNS = 4
    MAX_VALUE_SERIES = 3

    def run(self, question: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
        """Return presentation metadata without mutating SQL or result rows."""
        columns = list(rows[0].keys()) if rows else []
        base = {
            "type": "table",
            "title": question.strip(),
            "category_column": None,
            "value_columns": [],
        }

        if not rows or not columns:
            return base

        numeric_columns = [
            column for column in columns
            if self._column_values_are(rows, column, self._is_numeric)
        ]
        temporal_columns = [
            column for column in columns
            if self._is_temporal_column(rows, column)
        ]
        category_columns = [
            column for column in columns if column not in numeric_columns
        ]

        if len(rows) == 1 and len(columns) == 1 and numeric_columns:
            return {
                **base,
                "type": "kpi",
                "value_columns": [numeric_columns[0]],
            }

        # Detail/list queries are better represented as tables. Wide records
        # usually mix unrelated IDs, flags, and amounts on incompatible scales.
        is_record_list = bool(self.RECORD_LIST_PATTERN.search(question))
        is_aggregate = bool(self.AGGREGATE_PATTERN.search(question))
        if (is_record_list and not is_aggregate) or len(columns) > self.MAX_CHART_COLUMNS:
            return base

        category = (
            temporal_columns[0] if temporal_columns
            else category_columns[0] if category_columns
            else columns[0] if is_aggregate and len(columns) > 1
            else None
        )
        value_columns = [
            column for column in numeric_columns
            if column != category and not self._looks_like_identifier(column)
        ]
        if category and 0 < len(value_columns) <= self.MAX_VALUE_SERIES:
            return {
                **base,
                "type": "line" if category in temporal_columns else "bar",
                "category_column": category,
                "value_columns": value_columns,
            }

        return base

    @staticmethod
    def _is_numeric(value: Any) -> bool:
        return isinstance(value, (Number, Decimal)) and not isinstance(value, bool)

    @staticmethod
    def _looks_like_identifier(column: str) -> bool:
        compact = re.sub(r"[^a-z0-9]", "", str(column).casefold())
        return compact.endswith(("id", "ref", "number", "version", "rownumber"))

    @classmethod
    def _column_values_are(cls, rows, column, predicate) -> bool:
        values = [row.get(column) for row in rows if row.get(column) is not None]
        return bool(values) and all(predicate(value) for value in values)

    @classmethod
    def _is_temporal_column(cls, rows: list[dict[str, Any]], column: str) -> bool:
        if cls._column_values_are(
            rows, column, lambda value: isinstance(value, (date, datetime))
        ):
            return True
        folded = str(column).casefold()
        return any(hint in folded for hint in cls.TEMPORAL_NAME_HINTS)
