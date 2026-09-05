import unittest
from datetime import date

from pipeline.visualization.layer import VisualizationLayer


class VisualizationLayerTests(unittest.TestCase):
    def setUp(self):
        self.layer = VisualizationLayer()

    def test_single_numeric_value_uses_kpi(self):
        rows = [{"TotalSales": 125000}]

        result = self.layer.run("What are total sales?", rows)

        self.assertEqual(result["type"], "kpi")
        self.assertEqual(result["value_columns"], ["TotalSales"])
        self.assertIsNone(result["category_column"])
        self.assertEqual(rows, [{"TotalSales": 125000}])

    def test_single_date_value_uses_summary_value(self):
        rows = [{"CreationDate": "2020-08-09T18:31:47"}]

        result = self.layer.run(
            "When was the general ledger voucher created?",
            rows,
        )

        self.assertEqual(result["type"], "kpi")
        self.assertEqual(result["value_columns"], ["CreationDate"])
        self.assertIsNone(result["category_column"])

    def test_single_row_direct_lookup_uses_summary_values(self):
        rows = [{
            "CreationDate": "2020-08-09T18:31:47",
            "VoucherNumber": "1",
            "Status": "Final",
        }]

        result = self.layer.run(
            "What is the creation date, voucher number, and status?",
            rows,
        )

        self.assertEqual(result["type"], "kpi")
        self.assertEqual(
            result["value_columns"],
            ["CreationDate", "VoucherNumber", "Status"],
        )
        self.assertIsNone(result["category_column"])

    def test_temporal_category_uses_line_chart(self):
        rows = [
            {"Year": 2024, "TotalSales": 100},
            {"Year": 2025, "TotalSales": 140},
        ]

        result = self.layer.run("Sales by year", rows)

        self.assertEqual(result["type"], "line")
        self.assertEqual(result["category_column"], "Year")
        self.assertEqual(result["value_columns"], ["TotalSales"])

    def test_date_values_use_line_chart(self):
        rows = [
            {"Period": date(2025, 1, 1), "Revenue": 10.5},
            {"Period": date(2025, 2, 1), "Revenue": 12.0},
        ]

        result = self.layer.run("Revenue trend", rows)

        self.assertEqual(result["type"], "line")
        self.assertEqual(result["category_column"], "Period")

    def test_text_category_uses_bar_chart(self):
        rows = [
            {"Product": "A", "Sales": 10},
            {"Product": "B", "Sales": 20},
        ]

        result = self.layer.run("Sales by product", rows)

        self.assertEqual(result["type"], "bar")
        self.assertEqual(result["category_column"], "Product")

    def test_record_listing_with_many_numeric_fields_uses_table(self):
        rows = [
            {
                "AcquisitionReceiptID": 8001,
                "Number": 12,
                "CurrencyRef": 2,
                "CurrencyRate": 60000,
                "Type": 1,
                "Date": date(2026, 5, 13),
                "Version": 3,
            },
            {
                "AcquisitionReceiptID": 8002,
                "Number": 13,
                "CurrencyRef": 2,
                "CurrencyRate": 59500,
                "Type": 1,
                "Date": date(2026, 5, 12),
                "Version": 3,
            },
        ]

        result = self.layer.run(
            "Show the latest 20 acquisition receipt records ordered by date.",
            rows,
        )

        self.assertEqual(result["type"], "table")
        self.assertEqual(result["value_columns"], [])

    def test_single_record_listing_stays_table(self):
        rows = [{
            "AcquisitionReceiptID": 8001,
            "Number": 12,
            "Date": date(2026, 5, 13),
        }]

        result = self.layer.run(
            "Show the latest acquisition receipt record ordered by date.",
            rows,
        )

        self.assertEqual(result["type"], "table")
        self.assertEqual(result["value_columns"], [])

    def test_grouped_record_count_uses_bar_chart(self):
        rows = [
            {"Type": 1, "RecordCount": 12},
            {"Type": 2, "RecordCount": 8},
        ]

        result = self.layer.run(
            "Show the number of cost center information records grouped by type",
            rows,
        )

        self.assertEqual(result["type"], "bar")
        self.assertEqual(result["category_column"], "Type")
        self.assertEqual(result["value_columns"], ["RecordCount"])

    def test_identifier_is_not_used_as_chart_value(self):
        rows = [
            {"Month": "January", "ProductID": 10, "TotalSales": 100},
            {"Month": "February", "ProductID": 20, "TotalSales": 140},
        ]

        result = self.layer.run("Sales by month", rows)

        self.assertEqual(result["type"], "line")
        self.assertEqual(result["value_columns"], ["TotalSales"])

    def test_ambiguous_or_empty_results_fall_back_to_table(self):
        self.assertEqual(self.layer.run("Nothing", [])["type"], "table")
        self.assertEqual(
            self.layer.run("Names", [{"Name": "A"}, {"Name": "B"}])["type"],
            "table",
        )


if __name__ == "__main__":
    unittest.main()
