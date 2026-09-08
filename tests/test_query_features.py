import unittest
from evaluation.query_features import classify, annotate, feature_summary


class QueryFeaturesTests(unittest.TestCase):
    def test_literals_comments_and_identifiers_are_not_operators(self):
        result = classify({'reference_sql': "SELECT [Order], 'JOIN GROUP BY SUM(x)' FROM [JOIN] -- LEFT JOIN\n"})
        self.assertEqual(result['features'], ['simple_select'])

    def test_combined_features_and_date_range(self):
        result = classify({'id': 'x_typo_en', 'reference_sql':
            "SELECT TOP(20) a.Title, COUNT(b.Id) FROM a LEFT JOIN b ON b.Ref=a.Id "
            "WHERE b.Date >= '2026-01-01' GROUP BY a.Title ORDER BY COUNT(b.Id) DESC"})
        self.assertEqual(set(result['features']), {'top_limit', 'aggregation', 'join',
            'outer_join', 'filter', 'date_operation', 'range_filter', 'group_by', 'order_by', 'typo'})

    def test_overlapping_denominators_and_recovery(self):
        rows = annotate([
            {'reference_sql': 'SELECT COUNT(*) FROM a GROUP BY x', 'metrics': {'initial_ex': 0, 'final_ex': 1}, 'correction': {'attempted': True}},
            {'reference_sql': 'SELECT COUNT(*) FROM a', 'metrics': {'initial_ex': 0, 'final_ex': 0}},
        ])
        summary = feature_summary(rows)
        self.assertEqual(summary['aggregation']['questions'], 2)
        self.assertEqual(summary['aggregation']['execution_accuracy'], .5)
        self.assertEqual(summary['aggregation']['recovered_questions'], 1)
        self.assertEqual(summary['group_by']['execution_accuracy'], 1)


if __name__ == '__main__':
    unittest.main()
