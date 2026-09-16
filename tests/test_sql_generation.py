import unittest
from unittest.mock import MagicMock

from pipeline.sql_generation.layer import SQLGenerationLayer


class SQLGenerationPromptTests(unittest.TestCase):
    def test_prompt_requires_precision_aware_half_open_date_ranges(self):
        llm = MagicMock()
        llm.invoke.return_value.content = "SELECT 1"
        layer = SQLGenerationLayer(llm, None, None)

        layer.run("created on 2019-03-31", "CREATE TABLE [dbo].[Voucher] (...)")

        prompt = llm.invoke.call_args.args[0][0].content
        self.assertIn("date without a time means the entire day", prompt)
        self.assertIn("column >= period_start AND column < next_period_start", prompt)
        self.assertIn(">= '20190331' AND < '20190401'", prompt)
        self.assertIn("with an hour and minute, the entire minute", prompt)

    def test_prompt_requires_schema_grounded_join_keys(self):
        llm = MagicMock()
        llm.invoke.return_value.content = "SELECT 1"
        layer = SQLGenerationLayer(llm, None, None)

        layer.run("Show every asset and its costs", "Relationships: ...")

        prompt = llm.invoke.call_args.args[0][0].content
        self.assertIn("Never invent a join", prompt)
        self.assertIn("declared_fk", prompt)
        self.assertIn("inferred_name_match", prompt)
        self.assertIn("Ref-to-Id", prompt)
        self.assertIn("PlaqueNumber", prompt)
        self.assertIn("Never use NATURAL JOIN", prompt)
        self.assertIn("use INNER JOIN by default", prompt)
        self.assertIn("only when the question explicitly requires", prompt)
        self.assertIn("include banks with zero branches", prompt)

    def test_generated_mutation_after_select_is_rejected(self):
        llm = MagicMock()
        llm.invoke.return_value.content = (
            "SELECT 1; INSERT INTO [GNR].[CostCenter] ([Type]) VALUES (2);"
        )
        layer = SQLGenerationLayer(llm, None, None)

        with self.assertRaisesRegex(RuntimeError, "Only read-only SELECT"):
            layer.run("Insert a new cost center", "CREATE TABLE [GNR].[CostCenter] (...)")

    def test_generated_plain_insert_is_rejected(self):
        llm = MagicMock()
        llm.invoke.return_value.content = (
            "INSERT INTO [GNR].[CostCenter] ([Type]) VALUES (2);"
        )
        layer = SQLGenerationLayer(llm, None, None)

        with self.assertRaisesRegex(RuntimeError, "Only read-only SELECT"):
            layer.run("Insert a new cost center", "CREATE TABLE [GNR].[CostCenter] (...)")


if __name__ == "__main__":
    unittest.main()
