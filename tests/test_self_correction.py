import unittest
from unittest.mock import Mock, patch

from sqlalchemy import NVARCHAR

from pipeline.self_correction.layer import SelfCorrectionLayer


def _persian_values():
    actual = "\u062a\u0633\u062a \u062f\u0644\u062e\u0648\u0627\u0647"
    requested = "\u0636\u0631\u06cc\u0628 " + actual
    typo = "\u062a\u0633\u062a \u062f\u0644\u062e\u0627\u0647"
    return actual, requested, typo


class _FakeDatabaseManager:
    def __init__(self, original_sql, corrected_sql, actual_value):
        self.original_sql = original_sql
        self.corrected_sql = corrected_sql
        self.actual_value = actual_value
        self.calls = []

    def get_engine(self, _name):
        return object()

    def execute_query(self, _name, sql):
        self.calls.append(sql)
        if "candidate_value" in sql:
            return [{"candidate_value": self.actual_value}]
        if sql == self.corrected_sql:
            return [{"Percent": 12.5}]
        return []


class SelfCorrectionTests(unittest.TestCase):
    def test_parses_qualified_unicode_equality(self):
        _, requested, _ = _persian_values()
        sql = (
            "SELECT c.[Percent] FROM [CNT].[Coefficient] c "
            f"WHERE c.[Title] = N'{requested}'"
        )

        predicates = SelfCorrectionLayer._parse_value_predicates(sql)

        self.assertEqual(len(predicates), 1)
        self.assertEqual(predicates[0]["schema"], "CNT")
        self.assertEqual(predicates[0]["table"], "Coefficient")
        self.assertEqual(predicates[0]["column"], "Title")
        self.assertEqual(predicates[0]["literal"], requested)

    def test_similarity_handles_extra_qualifier_and_typo(self):
        actual, requested, typo = _persian_values()

        self.assertGreaterEqual(
            SelfCorrectionLayer._value_similarity(requested, actual),
            SelfCorrectionLayer.MIN_VALUE_SIMILARITY,
        )
        self.assertGreaterEqual(
            SelfCorrectionLayer._value_similarity(typo, actual),
            SelfCorrectionLayer.MIN_VALUE_SIMILARITY,
        )

    def test_empty_result_is_retried_with_grounded_value(self):
        actual, requested, _ = _persian_values()
        original = (
            "SELECT TOP 1 c.[Percent] FROM [CNT].[Coefficient] c "
            f"WHERE c.[Title] = N'{requested}'"
        )
        corrected = (
            "SELECT TOP 1 c.[Percent] FROM [CNT].[Coefficient] c "
            f"WHERE c.[Title] = N'{actual}'"
        )
        database = _FakeDatabaseManager(original, corrected, actual)
        llm = Mock()
        llm.invoke.return_value = Mock(content=corrected)
        inspector = Mock()
        inspector.get_columns.return_value = [
            {"name": "Title", "type": NVARCHAR(200)}
        ]
        layer = SelfCorrectionLayer(llm, None, database)

        with patch(
            "pipeline.self_correction.layer.inspect", return_value=inspector
        ):
            rows, final_sql = layer.run(
                original, "test1", "question", "schema", max_retries=3
            )

        self.assertEqual(rows, [{"Percent": 12.5}])
        self.assertEqual(final_sql, corrected)
        self.assertEqual(llm.invoke.call_count, 1)
        self.assertEqual(len(database.calls), 3)
        self.assertIn("TOP 200", database.calls[1])
        self.assertIn("LIKE N'", database.calls[1])


if __name__ == "__main__":
    unittest.main()
