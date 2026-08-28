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


if __name__ == "__main__":
    unittest.main()
