# Running the Standalone Evaluation

`run_evaluation.py` runs only when invoked directly and does not change the API
or the application's normal behavior. The evaluator reads questions from JSON
and immediately writes each completed result to a checkpoint.

## Reported metrics

- Execution Accuracy before and after Self-Correction
- Valid SQL Rate before and after Self-Correction
- Fractional Table Recall
- Table Precision
- Column Recall
- Self-Correction Success Rate
- Correction Gain
- R-VES using the BIRD Mini-Dev reward bands
- End-to-End Latency and per-stage timing
- Token Usage and model call count

Column Precision and binary Table Recall are intentionally not calculated.

## Secure database connection

Set the connection string as an environment variable in the current terminal so
it is not written to a report file or command history:

```powershell
$env:EVALUATION_DATABASE_URL = "mssql+pyodbc://..."
```

The evaluator does not store the connection string in the manifest, checkpoint,
or reports.

## Low-cost smoke test

Start with one or two questions:

```powershell
.\.venv\Scripts\python.exe evaluation\run_evaluation.py `
  --dataset evaluation\datasets\test1_candidate_bilingual.json `
  --db-name test1 `
  --db-type mssql `
  --limit 2 `
  --timing-repeats 3 `
  --run-dir evaluation\runs\smoke_test
```

The current `test1_candidate_bilingual.json` file is a candidate dataset. Its
reference SQL and business meaning must be reviewed before final reporting.

## Resume an interrupted run

```powershell
.\.venv\Scripts\python.exe evaluation\run_evaluation.py `
  --dataset evaluation\datasets\test1_candidate_bilingual.json `
  --db-name test1 `
  --db-type mssql `
  --resume evaluation\runs\smoke_test
```

Questions whose IDs are complete in the checkpoint are not rerun and consume no
new tokens, even if the dataset is edited later. On resume, the evaluator records
the new dataset hash in the manifest and reads unfinished questions from the new
version. To rerun a question, deliberately remove its checkpoint record or use
the appropriate retry option. The database name, database type, and evaluator
version must still match the existing manifest.

Press `Ctrl+C` to stop safely. Completed question results remain available, and
the reports are rebuilt up to that point.

## Limit token usage

```powershell
.\.venv\Scripts\python.exe evaluation\run_evaluation.py `
  --dataset evaluation\datasets\test1_candidate_bilingual.json `
  --db-name test1 `
  --max-token-budget 100000 `
  --run-dir evaluation\runs\budgeted_run
```

The budget is checked between questions; an in-progress call is not interrupted.
The run stops safely after the checkpoint's total token usage reaches the limit.

Available filters:

```text
--language fa
--language en
--category aggregation
--category temporal
--limit 10
--retry-failed
```

Repeat `--category` to include multiple categories.

## Rebuild reports from a checkpoint

To synchronize every report with the current `checkpoint.jsonl` without a
database connection or model call:

```powershell
.\.venv\Scripts\python.exe evaluation\run_evaluation.py `
  --dataset evaluation\datasets\questions_all.json `
  --db-name test1 `
  --db-type mssql `
  --resume evaluation\runs\v1 `
  --reports-only
```

This command selects the latest record for each question ID and rebuilds
`report.html`, `debug.html`, `summary.json`, `debug_eval.json`, and
`per_question.csv`.

## Output from each run

```text
evaluation/runs/<run-name>/
|-- manifest.json
|-- checkpoint.jsonl
|-- model_calls.jsonl
|-- summary.json
|-- per_question.csv
|-- debug_eval.json
|-- debug.html
`-- report.html
```

- `checkpoint.jsonl`: complete per-question results used for resume
- `model_calls.jsonl`: audit log of model calls for the run
- `summary.json`: aggregate metrics and breakdowns
- `per_question.csv`: results suitable for review in Excel
- `debug_eval.json`: compact per-question debugging data
- `debug.html`: standalone interactive review of reference SQL, generated SQL,
  errors, and retrieval for each question; the evaluator embeds the latest
  checkpoint records so the file opens directly in a browser
- `report.html`: standalone English report with metric cards, charts, and failed
  cases

## Measurement notes

- Generated SQL results are compared with reference SQL results, not SQL text.
- If the reference SQL has no `ORDER BY`, row order is ignored during comparison;
  duplicate rows are still preserved.
- Only read-only SQL is accepted.
- R-VES is calculated only for SQL with a correct result.
- R-VES uses a warm-up, and the reference/generated SQL execution order is
  alternated between timing repetitions.
- One-time introspection and enrichment costs are recorded in `manifest.json`
  and are not mixed into per-question latency.
