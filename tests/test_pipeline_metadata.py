import unittest

from pipeline import Pipeline
from pipeline.introspection.layer import IntrospectionResult


class MetadataShortcutTests(unittest.TestCase):
    def setUp(self):
        self.pipeline = Pipeline.__new__(Pipeline)
        self.result = IntrospectionResult(
            schemas=["ACC", "CRM"],
            table_metadata={
                ("ACC", "AccountType"): {
                    "columns": [{"name": "Id"}, {"name": "Type"}]
                },
                ("CRM", "Customer"): {"columns": [{"name": "Id"}]},
            },
        )
        self.pipeline.ensure_introspection = lambda _db_name: self.result

    def test_counts_tables_for_explicit_structural_request(self):
        answer = self.pipeline.answer_metadata_question(
            "How many tables are in the database?", "test"
        )
        self.assertEqual(answer, "There are 2 tables.")

    def test_lists_schemas_for_explicit_structural_request(self):
        answer = self.pipeline.answer_metadata_question("Show all schemas", "test")
        self.assertEqual(answer, "ACC\nCRM")

    def test_counts_columns_for_qualified_table(self):
        answer = self.pipeline.answer_metadata_question(
            "How many columns does ACC.AccountType have?", "test"
        )
        self.assertEqual(answer, "ACC.AccountType has 2 columns.")

    def test_business_count_with_table_word_uses_normal_pipeline(self):
        question = (
            "Show the number of account type table, containing details about "
            "account types records grouped by type."
        )
        self.assertIsNone(
            self.pipeline.answer_metadata_question(question, "test")
        )

    def test_record_count_in_table_uses_normal_pipeline(self):
        answer = self.pipeline.answer_metadata_question(
            "Count records in the account type table.", "test"
        )
        self.assertIsNone(answer)


if __name__ == "__main__":
    unittest.main()
