# Feature-based benchmark reporting

Questions use `features` rather than subjective `difficulty` labels. Features
are derived from the reference SQL, never from generated SQL or execution success.
The classifier is in `query_features.py`; `DESCRIPTIONS` defines every label.
Intentional spelling errors are marked by `_typo_` in the record ID or the explicit
boolean `intentional_typo`. No spelling errors are inferred automatically.

This is a deterministic lexical classifier for this benchmark, not a complete
T-SQL parser. It masks comments, string literals and quoted identifiers before
matching SQL operators. ISO date literals also trigger `date_operation`.
New SQL constructs may require extending the classifier and its tests.

## Interpreting the report

- Labels overlap: a query can require join, aggregation, group_by and order_by.
  Do not sum feature counts or average feature accuracies into an overall score.
- `feature_count` counts labels; it is not an estimate of difficulty. Some labels
  overlap hierarchically (multi_join also implies join).
- Per-feature initial/final EX averages existing, non-null EX values. The table
  shows the scored denominator. Recorded service failures are not reclassified
  as successful answers; an error count is shown separately.
- Recovery means correction was attempted and EX changed from 0 to 1.
  No new weighted score is introduced; arbitrary feature weights would not be
  evidence of question difficulty. Overall EX remains the original metric.
- A typo test may succeed before correction in a future run. Use recorded
  correction attempts and recovery counts, not only final EX, to assess that layer.

## Offline regeneration

Run `evaluation/reclassify_results.py` with `--dataset`, `--checkpoint` and
`--output`. It requires unique IDs and exactly matching question/reference SQL
between the dataset and checkpoint. It never invokes evaluation, an LLM or SQL.
It annotates the dataset and writes new summary, CSV, HTML and checkpoint files
in the output directory. Original checkpoint bytes remain unchanged; the manifest
records their SHA-256 hash and legacy difficulty labels. A dataset backup is
saved on the first run. Do not use the output directory as an evaluation resume
directory; it is an offline analysis snapshot.

The final report is `runs/v1/report.html`. Its summary, CSV and debug artifacts
also use feature labels. The original checkpoint and model-call log are retained
in `runs/v1` as execution evidence. Duplicate reports and temporary report backups
were removed after verification. Normal future report generation also uses features.
