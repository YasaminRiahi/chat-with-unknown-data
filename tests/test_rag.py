import unittest

from pipeline.introspection.layer import IntrospectionResult
from pipeline.rag.layer import RAGLayer


class TableRerankingTests(unittest.TestCase):
    @staticmethod
    def _table(name):
        return {"schema": "dbo", "table": name}

    def setUp(self):
        self.rag = RAGLayer.__new__(RAGLayer)

    def test_simpler_table_wins_when_compound_token_is_not_requested(self):
        contract = self._table("Contract")
        compound = self._table("ContractCoefficient")

        ranked = self.rag._rerank_table_scores(
            "show contracts", [(compound, 0.82), (contract, 0.80)]
        )

        self.assertEqual(ranked[0][0]["table"], "Contract")

    def test_compound_table_keeps_lead_when_all_tokens_are_requested(self):
        contract = self._table("Contract")
        compound = self._table("ContractCoefficient")

        ranked = self.rag._rerank_table_scores(
            "show contract coefficient", [(compound, 0.82), (contract, 0.80)]
        )

        self.assertEqual(ranked[0][0]["table"], "ContractCoefficient")

    def test_unrequested_higher_scoring_base_does_not_block_named_base(self):
        contract = self._table("Contract")
        coefficient = self._table("Coefficient")
        compound = self._table("ContractCoefficientItem")

        ranked = self.rag._rerank_table_scores(
            "show contract",
            [(compound, 0.82), (coefficient, 0.81), (contract, 0.80)],
        )

        self.assertEqual(ranked[0][0]["table"], "Contract")

    def test_direct_fk_targets_are_added_without_recursive_expansion(self):
        result = IntrospectionResult(table_metadata={
            ("dbo", "Order"): {
                "columns": [{"name": "CustomerId", "references": "dbo.Customer.Id"}]
            },
            ("dbo", "Customer"): {
                "columns": [{"name": "RegionId", "references": "dbo.Region.Id"}]
            },
            ("dbo", "Region"): {"columns": []},
        })

        tables = self.rag._add_fk_referenced_tables([("dbo", "Order")], result)

        self.assertEqual(tables, [("dbo", "Order"), ("dbo", "Customer")])


if __name__ == "__main__":
    unittest.main()
