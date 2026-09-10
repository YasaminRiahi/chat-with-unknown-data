import unittest
from types import SimpleNamespace

from pipeline.answer_generation.layer import AnswerGenerationLayer


class CapturingLLM:
    def __init__(self, content):
        self.content = content
        self.messages = None

    def invoke(self, messages):
        self.messages = messages
        return SimpleNamespace(content=self.content)


class AnswerGenerationTests(unittest.TestCase):
    def test_multi_row_prompt_requests_observations_instead_of_table(self):
        llm = CapturingLLM("Key observations\n\n- Bank A has the largest total.")
        layer = AnswerGenerationLayer(llm, None, None)

        layer.run(
            "Total by bank",
            "SELECT ...",
            [{"Bank": "A", "Total": 20}, {"Bank": "B", "Total": 10}],
        )

        prompt = llm.messages[1].content
        self.assertIn("never create a Markdown table", prompt)
        self.assertIn('"Key observations" heading', prompt)

    def test_markdown_table_is_removed_if_model_ignores_instruction(self):
        llm = CapturingLLM(
            "| Bank | Total |\n"
            "|---|---:|\n"
            "| A | 20 |\n\n"
            "Key observations\n\n"
            "- Bank A has the largest total."
        )
        layer = AnswerGenerationLayer(llm, None, None)

        answer = layer.run("Total by bank", "SELECT ...", [{"Bank": "A", "Total": 20}])

        self.assertNotIn("|", answer)
        self.assertIn("Key observations", answer)


if __name__ == "__main__":
    unittest.main()
