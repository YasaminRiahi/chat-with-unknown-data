import json
import tempfile
import unittest
from types import SimpleNamespace

from pipeline.enrichment.layer import EnrichmentLayer
from pipeline.introspection.layer import IntrospectionResult
from pipeline.rag.layer import RAGLayer


class FakeDatabase:
    @staticmethod
    def get_usable_table_names():
        return ["Voucher"]

    @staticmethod
    def get_table_info(table_names=None):
        return "CREATE TABLE [ACC].[Voucher] ([Amount] INTEGER)"


class FakeEnrichmentLLM:
    def __init__(self):
        self.prompts = []

    def invoke(self, messages):
        prompt = messages[0].content
        self.prompts.append(prompt)
        if prompt.startswith("Translate existing English"):
            table = {
                "id": "ACC.Voucher",
                "description_fa": "سربرگ سند حسابداری",
                "column_descriptions_fa": {"Amount": "مبلغ سند"},
            }
        else:
            table = {
                "id": "ACC.Voucher",
                "description": "Accounting voucher header",
                "column_descriptions": {"Amount": "Voucher amount"},
                "sensitive": False,
            }
        content = {"tables": [table]}
        return SimpleNamespace(content=json.dumps(content, ensure_ascii=False))


class TruncatingTranslationLLM:
    def __init__(self, *, max_tables=100, max_columns=100):
        self.max_tables = max_tables
        self.max_columns = max_columns
        self.calls = 0

    def invoke(self, messages):
        self.calls += 1
        payload = json.loads(
            messages[0].content.split("Existing English enrichment:\n", 1)[1]
        )
        column_count = sum(
            len(item["column_descriptions_en"]) for item in payload
        )
        if len(payload) > self.max_tables or column_count > self.max_columns:
            return SimpleNamespace(content='{"tables": [{"id": "truncated')
        tables = []
        for item in payload:
            tables.append({
                "id": item["id"],
                "description_fa": f"Persian {item['description_en']}",
                "column_descriptions_fa": {
                    name: f"Persian {description}"
                    for name, description
                    in item["column_descriptions_en"].items()
                },
            })
        return SimpleNamespace(content=json.dumps({"tables": tables}))


class MultilingualEnrichmentTests(unittest.TestCase):
    @staticmethod
    def _result():
        return IntrospectionResult(
            db_per_schema={"ACC": FakeDatabase()},
            schemas=["ACC"],
            table_metadata={
                ("ACC", "Voucher"): {
                    "schema": "ACC",
                    "table": "Voucher",
                    "columns": [{
                        "name": "Amount",
                        "type": "INTEGER",
                        "nullable": False,
                        "comment": "",
                        "primary_key": False,
                        "references": None,
                    }],
                }
            },
        )

    def test_run_caches_and_exposes_both_languages(self):
        with tempfile.TemporaryDirectory() as cache_dir:
            llm = FakeEnrichmentLLM()
            layer = EnrichmentLayer(
                llm, None, None, cache_dir=cache_dir
            )
            result = layer.run(self._result(), "erp")

            self.assertEqual(
                result.table_descriptions[("ACC", "Voucher")],
                "Accounting voucher header",
            )
            self.assertEqual(
                result.localized_table_descriptions[("ACC", "Voucher")]["fa"],
                "سربرگ سند حسابداری",
            )
            self.assertEqual(
                result.localized_column_descriptions[
                    ("ACC", "Voucher", "Amount")
                ]["fa"],
                "مبلغ سند",
            )

            cache = json.loads(
                layer._cache_path("erp").read_text(encoding="utf-8")
            )
            entry = cache["tables"]["ACC.Voucher"]
            self.assertEqual(entry["prompt_version"], 1)
            self.assertEqual(entry["persian_prompt_version"], 1)
            self.assertEqual(entry["description"], "Accounting voucher header")
            self.assertEqual(entry["description_fa"], "سربرگ سند حسابداری")
            self.assertEqual(len(llm.prompts), 2)

    def test_existing_english_cache_is_not_regenerated_or_overwritten(self):
        with tempfile.TemporaryDirectory() as cache_dir:
            llm = FakeEnrichmentLLM()
            layer = EnrichmentLayer(llm, None, None, cache_dir=cache_dir)
            result = self._result()
            _, _, ddl = next(result.iter_table_info())
            original_entry = {
                "fingerprint": layer._fingerprint(ddl),
                "prompt_version": 1,
                "model": "original-english-model",
                "description": "Original English wording",
                "column_descriptions": {"Amount": "Original amount wording"},
                "sensitive": False,
            }
            layer._save_cache("erp", {
                "cache_version": 1,
                "tables": {"ACC.Voucher": original_entry.copy()},
            })

            enriched = layer.run(result, "erp")
            cache = json.loads(
                layer._cache_path("erp").read_text(encoding="utf-8")
            )
            entry = cache["tables"]["ACC.Voucher"]

            self.assertEqual(len(llm.prompts), 1)
            self.assertTrue(llm.prompts[0].startswith("Translate existing English"))
            self.assertIn("Original English wording", llm.prompts[0])
            for field in (
                "prompt_version", "model", "description",
                "column_descriptions", "sensitive",
            ):
                self.assertEqual(entry[field], original_entry[field])
            self.assertEqual(
                enriched.table_descriptions[("ACC", "Voucher")],
                "Original English wording",
            )

    def test_rag_documents_contain_english_and_persian_descriptions(self):
        result = self._result()
        result.localized_table_descriptions[("ACC", "Voucher")] = {
            "en": "Accounting voucher header",
            "fa": "سربرگ سند حسابداری",
        }
        result.localized_column_descriptions[("ACC", "Voucher", "Amount")] = {
            "en": "Voucher amount",
            "fa": "مبلغ سند",
        }

        item = RAGLayer.__new__(RAGLayer)._items(result)["table:ACC.Voucher"]

        self.assertIn("Accounting voucher header", item["text"])
        self.assertIn("سربرگ سند حسابداری", item["text"])
        self.assertIn("Voucher amount", item["text"])
        self.assertIn("مبلغ سند", item["text"])

    def test_legacy_cache_fields_remain_usable_as_english(self):
        entry = {
            "description": "Legacy English description",
            "column_descriptions": {"Amount": "Legacy amount"},
        }

        semantic = EnrichmentLayer._semantic_text(entry)

        self.assertIn("Legacy English description", semantic)
        self.assertIn("Legacy amount", semantic)

    def test_malformed_multi_table_response_is_retried_in_smaller_batches(self):
        llm = TruncatingTranslationLLM(max_tables=1)
        layer = EnrichmentLayer(llm, None, None)
        specs = [{"id": "ACC.One"}, {"id": "ACC.Two"}]
        cache = {
            "ACC.One": {
                "description": "One", "column_descriptions": {"Id": "ID"},
            },
            "ACC.Two": {
                "description": "Two", "column_descriptions": {"Id": "ID"},
            },
        }

        results = layer._translate_resilient(specs, cache)

        self.assertEqual([item["id"] for item in results], ["ACC.One", "ACC.Two"])
        self.assertEqual(llm.calls, 3)

    def test_malformed_wide_table_response_is_split_by_columns(self):
        llm = TruncatingTranslationLLM(max_columns=2)
        layer = EnrichmentLayer(llm, None, None)
        specs = [{"id": "ACC.Wide"}]
        columns = {f"Column{index}": f"Meaning {index}" for index in range(4)}
        cache = {
            "ACC.Wide": {
                "description": "Wide table", "column_descriptions": columns,
            }
        }

        result = layer._translate_resilient(specs, cache)[0]

        self.assertEqual(set(result["column_descriptions_fa"]), set(columns))
        self.assertEqual(llm.calls, 3)


if __name__ == "__main__":
    unittest.main()
