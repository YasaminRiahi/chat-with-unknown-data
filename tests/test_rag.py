import unittest
from types import SimpleNamespace

from pipeline.introspection.layer import IntrospectionResult
from pipeline.rag.layer import RAGLayer, _PersistentEmbeddingIndex


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

    def test_direct_fk_neighbors_are_added_without_recursive_expansion(self):
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

    def test_referencing_child_table_is_added(self):
        result = IntrospectionResult(table_metadata={
            ("dbo", "Voucher"): {"columns": []},
            ("dbo", "VoucherItem"): {
                "columns": [
                    {"name": "VoucherId", "references": "dbo.Voucher.Id"}
                ]
            },
        })

        tables = self.rag._add_fk_referenced_tables(
            [("dbo", "Voucher")], result
        )

        self.assertEqual(tables, [("dbo", "Voucher"), ("dbo", "VoucherItem")])


class HybridRetrievalTests(unittest.TestCase):
    def setUp(self):
        self.index = _PersistentEmbeddingIndex(None, None)
        self.index.items = {
            "table:dbo.Account": {
                "kind": "table", "schema": "dbo", "table": "Account",
                "text": "Table dbo.Account. Customer financial accounts.",
            },
            "table:dbo.CustomerAccountArchive": {
                "kind": "table", "schema": "dbo",
                "table": "CustomerAccountArchive",
                "text": "Archived customer records containing AcctNo.",
            },
        }

    def test_bm25_rewards_exact_identifier_token(self):
        ranked = self.index.lexical_scores("find AcctNo", kind="table")
        self.assertEqual(ranked[0][0]["table"], "CustomerAccountArchive")

    def test_rrf_combines_dense_and_lexical_ranks(self):
        account = self.index.items["table:dbo.Account"]
        archive = self.index.items["table:dbo.CustomerAccountArchive"]
        fused = RAGLayer._fuse_scores(
            [(account, 0.9), (archive, 0.8)],
            [(archive, 4.0)],
        )
        self.assertEqual(fused[0][0]["table"], "CustomerAccountArchive")
        self.assertEqual(fused[0][1], 1.0)

    def test_schema_linker_selects_related_tables_as_a_group(self):
        class FakeLLM:
            @staticmethod
            def invoke(messages):
                return SimpleNamespace(content=(
                    '{"tables":["ACC.GLVoucher","ACC.GLVoucherItem",'
                    '"ACC.Voucher"],"reason":"bridge relationship"}'
                ))

        rag = RAGLayer(FakeLLM(), None, None, schema_linking_enabled=True)
        result = IntrospectionResult(
            table_metadata={
                ("ACC", "GLVoucher"): {"columns": [
                    {"name": "GLVoucherId", "primary_key": True}
                ]},
                ("ACC", "GLVoucherItem"): {"columns": [
                    {"name": "GLVoucherRef"}, {"name": "VoucherRef"}
                ]},
                ("ACC", "Voucher"): {"columns": [
                    {"name": "VoucherId", "primary_key": True}
                ]},
                ("GNR", "Bill"): {"columns": [{"name": "BillId"}]},
            }
        )
        scored = [
            ({"schema": schema, "table": table}, score)
            for (schema, table), score in [
                (("ACC", "GLVoucher"), 1.0),
                (("ACC", "GLVoucherItem"), 0.9),
                (("GNR", "Bill"), 0.8),
                (("ACC", "Voucher"), 0.7),
            ]
        ]

        selected = rag._llm_schema_link("find the linked voucher", scored, result)

        self.assertEqual(selected, [
            ("ACC", "GLVoucher"),
            ("ACC", "GLVoucherItem"),
            ("ACC", "Voucher"),
        ])
        relationships = rag._schema_link_relationships(
            [(item["schema"], item["table"]) for item, _ in scored], result
        )
        self.assertIn({
            "from": "ACC.GLVoucherItem.VoucherRef",
            "to": "ACC.Voucher.VoucherId",
            "confidence": "inferred_name_match",
        }, relationships)

    def test_schema_linker_rejects_invented_table(self):
        class FakeLLM:
            @staticmethod
            def invoke(messages):
                return SimpleNamespace(content='{"tables":["ACC.MadeUp"]}')

        rag = RAGLayer(FakeLLM(), None, None, schema_linking_enabled=True)
        scored = [({"schema": "ACC", "table": "Voucher"}, 1.0)]
        result = IntrospectionResult(table_metadata={
            ("ACC", "Voucher"): {"columns": []}
        })

        self.assertIsNone(rag._llm_schema_link("find voucher", scored, result))

    def test_schema_link_metadata_is_compact_and_prioritized(self):
        metadata = {"columns": [
            {"name": "Unrelated"},
            {"name": "CreationDate"},
            {"name": "VoucherRef"},
            {"name": "VoucherItemId", "primary_key": True},
            *({"name": f"Extra{index}"} for index in range(20)),
        ]}

        columns = RAGLayer._schema_link_columns(
            metadata, "show the voucher creation date"
        )

        self.assertLessEqual(len(columns), RAGLayer.MAX_SCHEMA_LINK_COLUMNS)
        self.assertEqual(
            [column["name"] for column in columns[:3]],
            ["VoucherRef", "VoucherItemId", "CreationDate"],
        )
        self.assertNotIn("type", columns[0])


if __name__ == "__main__":
    unittest.main()
