import json
import tempfile
import unittest
from pathlib import Path

from evaluation.run_evaluation import (
    append_checkpoint,
    load_checkpoints,
    results_equal,
    retrieval_metrics,
    r_ves_item,
    safe_sql,
)


class EvaluationMetricTests(unittest.TestCase):
    def test_sql_safety_allows_reads_and_rejects_mutations(self):
        self.assertTrue(safe_sql("SELECT * FROM [dbo].[Thing]"))
        self.assertTrue(safe_sql("WITH x AS (SELECT 1 AS n) SELECT n FROM x"))
        self.assertFalse(safe_sql("DELETE FROM [dbo].[Thing]"))
        self.assertFalse(safe_sql("SELECT 1; DROP TABLE [dbo].[Thing]"))

    def test_execution_results_ignore_order_without_order_by(self):
        reference = [{"x": 1}, {"x": 2}]
        predicted = [{"value": 2}, {"value": 1}]
        self.assertTrue(results_equal(reference, predicted, "SELECT x FROM t"))
        self.assertFalse(
            results_equal(reference, predicted, "SELECT x FROM t ORDER BY x")
        )

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


if __name__ == "__main__":
    unittest.main()
