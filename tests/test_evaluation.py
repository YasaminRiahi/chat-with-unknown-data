import json
import tempfile
import unittest
from pathlib import Path

from evaluation.run_evaluation import (
    append_checkpoint,
    load_checkpoints,
    make_debug_records,
    question_requests_order,
    record_order_sensitive,
    results_equal,
    retrieval_metrics,
    r_ves_item,
    safe_sql,
    write_debug_html,
)


class EvaluationMetricTests(unittest.TestCase):
    def test_sql_safety_allows_reads_and_rejects_mutations(self):
        self.assertTrue(safe_sql("SELECT * FROM [dbo].[Thing]"))
        self.assertTrue(safe_sql("WITH x AS (SELECT 1 AS n) SELECT n FROM x"))
        self.assertFalse(safe_sql("DELETE FROM [dbo].[Thing]"))
        self.assertFalse(safe_sql("SELECT 1; DROP TABLE [dbo].[Thing]"))

    def test_execution_order_is_controlled_by_question_semantics(self):
        reference = [{"x": 1}, {"x": 2}]
        predicted = [{"value": 2}, {"value": 1}]
        sql = "SELECT x FROM t ORDER BY x"
        self.assertTrue(results_equal(
            reference, predicted, sql, order_sensitive=False
        ))
        self.assertFalse(results_equal(
            reference, predicted, sql, order_sensitive=True
        ))

    def test_order_sensitivity_detects_explicit_english_and_persian_requests(self):
        self.assertTrue(question_requests_order("Show rows ordered by date."))
        self.assertTrue(question_requests_order("Show the top 20 by amount."))
        self.assertTrue(question_requests_order("نتایج را به ترتیب تاریخ نشان بده."))
        self.assertFalse(question_requests_order("Show totals for each year."))
        self.assertFalse(question_requests_order("مجموع هر سال را نمایش دهید."))

    def test_explicit_order_sensitive_field_overrides_question_detection(self):
        self.assertFalse(record_order_sensitive({
            "question": "Show rows ordered by date.", "order_sensitive": False,
        }))
        self.assertTrue(record_order_sensitive({
            "question": "Show all rows.", "order_sensitive": True,
        }))

    def test_retrieval_metrics_use_fractional_table_recall_only(self):
        record = {
            "gold_tables": ["CNT.Contract", "CNT.Status", "CNT.StatusItem"],
            "gold_columns": [
                "CNT.Contract.ContractID", "CNT.Status.ContractRef"
            ],
        }
        metrics = retrieval_metrics(
            record,
            [("CNT", "Contract"), ("CNT", "Status"), ("CNT", "Project")],
            {
                ("CNT", "Contract"): [{"name": "ContractID"}],
                ("CNT", "Status"): [{"name": "ContractRef"}],
                ("CNT", "Project"): [{"name": "ProjectID"}],
            },
        )
        self.assertAlmostEqual(metrics["table_recall"], 2 / 3, places=6)
        self.assertAlmostEqual(metrics["table_precision"], 2 / 3, places=6)
        self.assertEqual(metrics["column_recall"], 1.0)
        self.assertNotIn("column_precision", metrics)

    def test_rves_uses_official_reward_bands(self):
        fast = r_ves_item([20, 20], [10, 10], True)
        equal = r_ves_item([10], [10], True)
        wrong = r_ves_item([10], [1], False)
        self.assertEqual(fast["reward"], 1.25)
        self.assertAlmostEqual(fast["score"], (1.25 ** 0.5) * 100, places=5)
        self.assertEqual(equal["score"], 100.0)
        self.assertEqual(wrong["score"], 0.0)

    def test_checkpoint_keeps_completed_records_for_resume(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "checkpoint.jsonl"
            append_checkpoint(path, {"id": "q1", "status": "completed"})
            append_checkpoint(path, {"id": "q2", "status": "completed"})
            with path.open("a", encoding="utf-8") as handle:
                handle.write('{"truncated":')
            loaded = load_checkpoints(path)
            self.assertEqual(set(loaded), {"q1", "q2"})

    def test_debug_artifacts_contain_only_requested_diagnostics(self):
        record = {
            "id": "q1",
            "question": "Which row?",
            "reference_sql": "SELECT 1",
            "final_sql": "SELECT 2",
            "error": None,
            "metrics": {
                "final_ex": 0,
                "table_recall": 0.5,
                "table_precision": 1.0,
                "column_recall": 0.25,
            },
            "retrieval": {
                "retrieved_tables": ["dbo.Thing"],
                "retrieved_columns": ["dbo.Thing.Id"],
            },
            "unrelated": "not included",
        }
        debug = make_debug_records([record])
        self.assertEqual(set(debug[0]), {
            "id", "question", "reference_sql", "final_generated_sql", "error",
            "ex", "table_recall", "table_precision", "column_recall",
            "retrieved_tables", "retrieved_columns",
        })
        self.assertEqual(debug[0]["final_generated_sql"], "SELECT 2")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "debug.html"
            write_debug_html(path, [record])
            document = path.read_text(encoding="utf-8")
            self.assertIn("Evaluation Debugger", document)
            self.assertIn("Which row?", document)
            self.assertNotIn("fetch('checkpoint.jsonl'", document)
            self.assertIn("Next failed", document)
            self.assertIn("Copy ID", document)
            self.assertIn("copyQuestionId", document)


if __name__ == "__main__":
    unittest.main()
