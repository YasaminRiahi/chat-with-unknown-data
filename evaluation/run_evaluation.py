"""Standalone, resumable evaluator for the Text-to-SQL pipeline.

This module is intentionally not imported by the API or normal application.
It reads a benchmark JSON file, runs each unfinished question, appends one
checkpoint record immediately, and produces JSON/CSV/HTML reports.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import math
import os
import re
import statistics
import sys
import time
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from types import MethodType
from typing import Any

# Direct execution (``python evaluation/run_evaluation.py``) puts only the
# evaluation directory on sys.path. Add the repository root before importing
# project packages so both direct and ``python -m`` execution work.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from langchain_groq import ChatGroq

from api.config import Settings
from api.database_manager import DatabaseManager
from api.model_logging import LoggedChatModel, LoggedOllamaEmbeddings, ModelCallLogger
from pipeline import Pipeline


EVALUATOR_VERSION = 1
READ_ONLY_START = re.compile(r"^\s*(?:SELECT\b|WITH\b)", re.IGNORECASE)
FORBIDDEN_SQL = re.compile(
    r"\b(?:INSERT|UPDATE|DELETE|MERGE|DROP|ALTER|TRUNCATE|EXEC(?:UTE)?|"
    r"CREATE|GRANT|REVOKE|DENY|DBCC|BACKUP|RESTORE)\b",
    re.IGNORECASE,
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def percentile(values: list[float], percent: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * percent
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def stats(values: list[float]) -> dict[str, float | None]:
    return {
        "count": len(values),
        "mean": round(statistics.fmean(values), 3) if values else None,
        "median": round(statistics.median(values), 3) if values else None,
        "p90": round(percentile(values, 0.90), 3) if values else None,
        "p95": round(percentile(values, 0.95), 3) if values else None,
        "min": round(min(values), 3) if values else None,
        "max": round(max(values), 3) if values else None,
    }


def safe_sql(sql: str) -> bool:
    stripped = re.sub(r"--[^\n]*|/\*.*?\*/", " ", sql, flags=re.DOTALL)
    return bool(READ_ONLY_START.search(stripped)) and not FORBIDDEN_SQL.search(stripped)


def normalized_scalar(value: Any) -> Any:
    if value is None:
        return ["null", None]
    if isinstance(value, bool):
        return ["bool", value]
    if isinstance(value, (int, Decimal)):
        return ["number", str(value)]
    if isinstance(value, float):
        if math.isnan(value):
            return ["float", "nan"]
        return ["number", format(value, ".9g")]
    if isinstance(value, (datetime, date)):
        return ["datetime", value.isoformat()]
    if isinstance(value, bytes):
        return ["bytes", value.hex()]
    return ["text", str(value).strip()]


def normalized_rows(rows: list[dict], ordered: bool) -> list[str]:
    normalized = [
        json.dumps(
            [normalized_scalar(value) for value in row.values()],
            ensure_ascii=False,
            sort_keys=True,
        )
        for row in rows
    ]
    return normalized if ordered else sorted(normalized)


def results_equal(reference: list[dict] | None, predicted: list[dict] | None,
                  reference_sql: str) -> bool:
    if reference is None or predicted is None:
        return False
    if reference and predicted and len(reference[0]) != len(predicted[0]):
        return False
    ordered = bool(re.search(r"\bORDER\s+BY\b", reference_sql, re.IGNORECASE))
    return normalized_rows(reference, ordered) == normalized_rows(predicted, ordered)


def execute_timed(db: DatabaseManager, db_name: str, sql: str) -> dict[str, Any]:
    if not safe_sql(sql):
        return {
            "valid": False, "rows": None, "duration_ms": None,
            "error": "Evaluator rejected a non-read-only SQL statement.",
        }
    started = time.perf_counter()
    try:
        rows = db.execute_query(db_name, sql)
        return {
            "valid": True,
            "rows": rows,
            "duration_ms": round((time.perf_counter() - started) * 1000, 3),
            "error": None,
        }
    except Exception as exc:
        return {
            "valid": False,
            "rows": None,
            "duration_ms": round((time.perf_counter() - started) * 1000, 3),
            "error": f"{type(exc).__name__}: {exc}",
        }


def benchmark_times(db: DatabaseManager, db_name: str, reference_sql: str,
                    predicted_sql: str, repeats: int) -> dict[str, Any]:
    reference_times, predicted_times = [], []
    # One unmeasured warm-up pair reduces first-execution bias.
    execute_timed(db, db_name, reference_sql)
    execute_timed(db, db_name, predicted_sql)
    for index in range(repeats):
        pair = (
            ((reference_sql, reference_times), (predicted_sql, predicted_times))
            if index % 2 == 0 else
            ((predicted_sql, predicted_times), (reference_sql, reference_times))
        )
        for sql, destination in pair:
            result = execute_timed(db, db_name, sql)
            if not result["valid"]:
                return {
                    "reference_times_ms": reference_times,
                    "predicted_times_ms": predicted_times,
                    "error": result["error"],
                }
            destination.append(result["duration_ms"])
    return {
        "reference_times_ms": reference_times,
        "predicted_times_ms": predicted_times,
        "error": None,
    }


def r_ves_item(reference_times: list[float], predicted_times: list[float],
               correct: bool) -> dict[str, Any]:
    if not correct or not reference_times or not predicted_times:
        return {"time_ratio": None, "reward": 0.0, "score": 0.0}
    ratios = [
        reference / predicted
        for reference, predicted in zip(reference_times, predicted_times)
        if predicted > 0
    ]
    if not ratios:
        return {"time_ratio": None, "reward": 0.0, "score": 0.0}
    ratio = statistics.fmean(ratios)
    if ratio >= 2:
        reward = 1.25
    elif ratio >= 1:
        reward = 1.0
    elif ratio >= 0.5:
        reward = 0.75
    elif ratio >= 0.25:
        reward = 0.5
    else:
        reward = 0.25
    return {
        "time_ratio": round(ratio, 6),
        "reward": reward,
        # Matches BIRD Mini-Dev compute_ves: sqrt(reward) * 100.
        "score": round(math.sqrt(reward) * 100, 6),
    }


def load_model_calls(path: Path, offset: int) -> tuple[list[dict], int]:
    calls = []
    if not path.exists():
        return calls, offset
    with path.open("r", encoding="utf-8") as handle:
        handle.seek(offset)
        for line in handle:
            try:
                calls.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return calls, handle.tell()


def token_summary(calls: list[dict]) -> dict[str, Any]:
    totals = Counter()
    by_operation: dict[str, Counter] = defaultdict(Counter)
    for call in calls:
        operation = call.get("operation", "unknown")
        usage = call.get("usage") or {}
        input_tokens = usage.get("input_tokens", usage.get("prompt_tokens", 0)) or 0
        output_tokens = usage.get("output_tokens", usage.get("completion_tokens", 0)) or 0
        total_tokens = usage.get("total_tokens", input_tokens + output_tokens) or 0
        totals.update({
            "calls": 1,
            "input_tokens": int(input_tokens),
            "output_tokens": int(output_tokens),
            "total_tokens": int(total_tokens),
        })
        by_operation[operation].update({
            "calls": 1,
            "input_tokens": int(input_tokens),
            "output_tokens": int(output_tokens),
            "total_tokens": int(total_tokens),
        })
    return {**totals, "by_operation": {key: dict(value) for key, value in by_operation.items()}}


def normalized_name(value: str) -> str:
    return value.replace("[", "").replace("]", "").casefold()


def retrieval_metrics(record: dict, tables: list[tuple[str, str]],
                      columns: dict[tuple[str, str], list[dict]]) -> dict[str, Any]:
    retrieved_tables = {normalized_name(f"{s}.{t}") for s, t in tables}
    gold_tables = {normalized_name(value) for value in record.get("gold_tables", [])}
    table_hits = retrieved_tables & gold_tables
    table_recall = len(table_hits) / len(gold_tables) if gold_tables else None
    table_precision = len(table_hits) / len(retrieved_tables) if retrieved_tables else 0.0

    retrieved_columns = {
        normalized_name(f"{schema}.{table}.{column['name']}")
        for (schema, table), selected in columns.items()
        for column in selected
    }
    gold_columns = {normalized_name(value) for value in record.get("gold_columns", [])}
    column_hits = retrieved_columns & gold_columns
    column_recall = len(column_hits) / len(gold_columns) if gold_columns else None
    return {
        "retrieved_tables": sorted(f"{s}.{t}" for s, t in tables),
        "retrieved_columns": sorted(
            f"{s}.{t}.{column['name']}"
            for (s, t), selected in columns.items() for column in selected
        ),
        "table_recall": round(table_recall, 6) if table_recall is not None else None,
        "table_precision": round(table_precision, 6),
        "column_recall": round(column_recall, 6) if column_recall is not None else None,
        "missing_gold_tables": sorted(gold_tables - retrieved_tables),
        "missing_gold_columns": sorted(gold_columns - retrieved_columns),
    }


class RetrievalCapture:
    def __init__(self, rag: Any):
        self.tables: list[tuple[str, str]] = []
        self.columns: dict[tuple[str, str], list[dict]] = {}
        original = rag._compact_schema

        def wrapped(_instance: Any, tables: list[tuple[str, str]], columns: dict,
                    introspection_result: Any) -> str:
            self.tables = list(tables)
            self.columns = {key: list(value) for key, value in columns.items()}
            return original(tables, columns, introspection_result)

        rag._compact_schema = MethodType(wrapped, rag)

    def reset(self) -> None:
        self.tables = []
        self.columns = {}


def load_dataset(path: Path) -> list[dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    records = payload.get("records") if isinstance(payload, dict) else payload
    if not isinstance(records, list):
        raise ValueError("Dataset must be a list or an object containing a records list.")
    required = {"id", "question", "reference_sql", "gold_tables", "gold_columns"}
    seen = set()
    for index, record in enumerate(records):
        missing = required - set(record)
        if missing:
            raise ValueError(f"Record {index} is missing: {sorted(missing)}")
        if record["id"] in seen:
            raise ValueError(f"Duplicate record id: {record['id']}")
        if not safe_sql(record["reference_sql"]):
            raise ValueError(f"Reference SQL is not read-only: {record['id']}")
        seen.add(record["id"])
    return records


def append_checkpoint(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def load_checkpoints(path: Path) -> dict[str, dict]:
    completed = {}
    if not path.exists():
        return completed
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if record.get("status") == "completed":
            completed[record["id"]] = record
    return completed


def ratio(records: list[dict], key: str) -> float | None:
    values = [record.get("metrics", {}).get(key) for record in records]
    values = [float(value) for value in values if value is not None]
    return round(statistics.fmean(values), 6) if values else None


def grouped(records: list[dict], field: str) -> dict[str, dict[str, Any]]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for record in records:
        groups[str(record.get(field) or "unknown")].append(record)
    return {
        name: {
            "questions": len(items),
            "execution_accuracy": ratio(items, "final_ex"),
            "valid_sql_rate": ratio(items, "final_valid_sql"),
            "table_recall": ratio(items, "table_recall"),
            "column_recall": ratio(items, "column_recall"),
        }
        for name, items in sorted(groups.items())
    }


def make_summary(records: list[dict], manifest: dict) -> dict[str, Any]:
    total_tokens = sum(r.get("tokens", {}).get("total_tokens", 0) for r in records)
    total_calls = sum(r.get("tokens", {}).get("calls", 0) for r in records)
    attempted = [r for r in records if r.get("correction", {}).get("attempted")]
    corrected = [r for r in attempted if r.get("correction", {}).get("success")]
    latencies = [r["latency_ms"]["end_to_end"] for r in records]
    sql_latencies = [
        r["latency_ms"]["final_sql_execution"] for r in records
        if r["latency_ms"].get("final_sql_execution") is not None
    ]
    missing_tables = Counter(
        value for r in records for value in r.get("retrieval", {}).get("missing_gold_tables", [])
    )
    missing_columns = Counter(
        value for r in records for value in r.get("retrieval", {}).get("missing_gold_columns", [])
    )
    return {
        "generated_at": utc_now(),
        "manifest": manifest,
        "completed_questions": len(records),
        "metrics": {
            "initial_execution_accuracy": ratio(records, "initial_ex"),
            "final_execution_accuracy": ratio(records, "final_ex"),
            "initial_valid_sql_rate": ratio(records, "initial_valid_sql"),
            "final_valid_sql_rate": ratio(records, "final_valid_sql"),
            "table_recall": ratio(records, "table_recall"),
            "table_precision": ratio(records, "table_precision"),
            "column_recall": ratio(records, "column_recall"),
            "self_correction_success_rate": (
                round(len(corrected) / len(attempted), 6) if attempted else None
            ),
            "correction_gain": (
                round((ratio(records, "final_ex") or 0) - (ratio(records, "initial_ex") or 0), 6)
            ),
            "r_ves": ratio(records, "r_ves_score"),
            "end_to_end_latency_ms": stats(latencies),
            "final_sql_latency_ms": stats(sql_latencies),
            "total_llm_calls": total_calls,
            "average_llm_calls": round(total_calls / len(records), 3) if records else None,
            "total_tokens": total_tokens,
            "average_tokens": round(total_tokens / len(records), 3) if records else None,
        },
        "by_language": grouped(records, "language"),
        "by_category": grouped(records, "category"),
        "by_difficulty": grouped(records, "difficulty"),
        "most_missed_tables": missing_tables.most_common(15),
        "most_missed_columns": missing_columns.most_common(15),
    }


def write_csv(path: Path, records: list[dict]) -> None:
    fields = [
        "id", "language", "category", "difficulty", "initial_sql", "final_sql",
        "initial_ex", "final_ex", "initial_valid_sql", "final_valid_sql",
        "table_recall", "table_precision", "column_recall", "correction_attempted",
        "correction_success", "r_ves_score", "end_to_end_ms", "llm_calls",
        "total_tokens", "error",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for record in records:
            metrics = record.get("metrics", {})
            writer.writerow({
                "id": record["id"],
                "language": record.get("language"),
                "category": record.get("category"),
                "difficulty": record.get("difficulty"),
                "initial_sql": record.get("initial_sql"),
                "final_sql": record.get("final_sql"),
                "initial_ex": metrics.get("initial_ex"),
                "final_ex": metrics.get("final_ex"),
                "initial_valid_sql": metrics.get("initial_valid_sql"),
                "final_valid_sql": metrics.get("final_valid_sql"),
                "table_recall": metrics.get("table_recall"),
                "table_precision": metrics.get("table_precision"),
                "column_recall": metrics.get("column_recall"),
                "correction_attempted": record.get("correction", {}).get("attempted"),
                "correction_success": record.get("correction", {}).get("success"),
                "r_ves_score": metrics.get("r_ves_score"),
                "end_to_end_ms": record.get("latency_ms", {}).get("end_to_end"),
                "llm_calls": record.get("tokens", {}).get("calls"),
                "total_tokens": record.get("tokens", {}).get("total_tokens"),
                "error": record.get("error"),
            })


def format_percent(value: Any) -> str:
    return "—" if value is None else f"{float(value) * 100:.1f}%"


def bar_chart(title: str, groups: dict[str, dict], metric: str) -> str:
    bars = []
    for name, values in groups.items():
        value = values.get(metric)
        if value is None:
            continue
        width = max(0, min(100, float(value) * 100))
        bars.append(
            f'<div class="bar-row"><span>{html.escape(name)}</span>'
            f'<div class="track"><i style="width:{width:.1f}%"></i></div>'
            f'<b>{width:.1f}%</b></div>'
        )
    return f"<section><h2>{html.escape(title)}</h2>{''.join(bars) or '<p>داده‌ای نیست.</p>'}</section>"


def write_html(path: Path, summary: dict, records: list[dict]) -> None:
    metrics = summary["metrics"]
    cards = [
        ("Execution Accuracy", format_percent(metrics["final_execution_accuracy"])),
        ("Valid SQL Rate", format_percent(metrics["final_valid_sql_rate"])),
        ("Table Recall", format_percent(metrics["table_recall"])),
        ("Table Precision", format_percent(metrics["table_precision"])),
        ("Column Recall", format_percent(metrics["column_recall"])),
        ("Correction Gain", format_percent(metrics["correction_gain"])),
        ("Correction Success", format_percent(metrics["self_correction_success_rate"])),
        ("R-VES", "—" if metrics["r_ves"] is None else f'{metrics["r_ves"]:.2f}'),
        ("Median E2E", f'{metrics["end_to_end_latency_ms"]["median"] or 0:.1f} ms'),
        ("Average Tokens", f'{metrics["average_tokens"] or 0:,.0f}'),
        ("Average LLM Calls", f'{metrics["average_llm_calls"] or 0:.2f}'),
    ]
    failed = [r for r in records if not r.get("metrics", {}).get("final_ex")]
    failed_rows = "".join(
        "<tr>"
        f"<td>{html.escape(r['id'])}</td>"
        f"<td>{html.escape(str(r.get('question', '')))}</td>"
        f"<td>{html.escape(str(r.get('error') or 'Wrong result'))}</td>"
        "</tr>"
        for r in failed[:100]
    )
    document = f"""<!doctype html>
<html lang="fa" dir="rtl"><head><meta charset="utf-8">
<title>گزارش ارزیابی Text-to-SQL</title>
<style>
body{{font-family:Tahoma,Segoe UI,sans-serif;background:#f5f7fb;color:#172033;margin:0;padding:28px}}
main{{max-width:1200px;margin:auto}}h1,h2{{color:#152a4a}}.muted{{color:#667085}}
.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px}}
.card,section{{background:white;border:1px solid #e2e8f0;border-radius:12px;padding:18px;margin:14px 0}}
.card b{{display:block;font-size:25px;color:#176b87;margin-top:8px}}.bar-row{{display:grid;grid-template-columns:150px 1fr 60px;gap:10px;align-items:center;margin:10px 0}}
.track{{height:14px;background:#e8edf4;border-radius:8px;overflow:hidden}}.track i{{height:100%;display:block;background:#22a699}}
table{{width:100%;border-collapse:collapse;background:white}}th,td{{padding:9px;border-bottom:1px solid #e5e7eb;text-align:right;vertical-align:top}}
code{{direction:ltr}}@media(max-width:650px){{.bar-row{{grid-template-columns:100px 1fr 50px}}}}
</style></head><body><main>
<h1>گزارش ارزیابی Text-to-SQL</h1>
<p class="muted">تولیدشده در {html.escape(summary['generated_at'])} — {len(records)} سؤال تکمیل‌شده</p>
<div class="cards">{''.join(f'<div class="card"><span>{html.escape(k)}</span><b>{html.escape(v)}</b></div>' for k,v in cards)}</div>
{bar_chart('Execution Accuracy بر اساس زبان', summary['by_language'], 'execution_accuracy')}
{bar_chart('Execution Accuracy بر اساس دسته', summary['by_category'], 'execution_accuracy')}
{bar_chart('Execution Accuracy بر اساس سختی', summary['by_difficulty'], 'execution_accuracy')}
{bar_chart('Table Recall بر اساس دسته', summary['by_category'], 'table_recall')}
{bar_chart('Column Recall بر اساس دسته', summary['by_category'], 'column_recall')}
<section><h2>سؤال‌های ناموفق ({len(failed)})</h2><table><thead><tr><th>ID</th><th>سؤال</th><th>خطا/نتیجه</th></tr></thead><tbody>{failed_rows}</tbody></table></section>
<section><h2>فایل‌های همراه</h2><p><code>summary.json</code> خلاصه ماشینی، <code>per_question.csv</code> جزئیات و <code>checkpoint.jsonl</code> امکان ادامه اجرا را فراهم می‌کنند.</p></section>
</main></body></html>"""
    path.write_text(document, encoding="utf-8")


def write_reports(run_dir: Path, records: list[dict], manifest: dict) -> None:
    summary = make_summary(records, manifest)
    (run_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    write_csv(run_dir / "per_question.csv", records)
    write_html(run_dir / "report.html", summary, records)


def build_runtime(args: argparse.Namespace, run_dir: Path) -> tuple[Pipeline, DatabaseManager, Path]:
    settings = Settings.from_env()
    model_log = run_dir / "model_calls.jsonl"
    logger = ModelCallLogger(str(model_log))
    model = ChatGroq(
        model=settings.chat_model,
        api_key=settings.groq_api_key,
        temperature=0.1,
    )
    llm = LoggedChatModel(model, logger)
    embeddings = LoggedOllamaEmbeddings(
        model=settings.embedding_model,
        base_url=settings.ollama_base_url,
    ).configure_logging(logger)
    manager = DatabaseManager()
    connection_string = args.connection_string or os.getenv("EVALUATION_DATABASE_URL", "")
    if not connection_string:
        raise RuntimeError(
            "Set EVALUATION_DATABASE_URL or pass --connection-string. "
            "The value is never written to evaluation reports."
        )
    manager.add_database(args.db_name, args.db_type, connection_string)
    pipeline = Pipeline(
        llm, embeddings, manager,
        enrichment_cache_dir=settings.enrichment_cache_dir,
        embedding_cache_dir=settings.embedding_cache_dir,
        llm_enrichment_enabled=settings.llm_enrichment_enabled,
        enrichment_batch_size=settings.enrichment_batch_size,
        reranker_enabled=settings.reranker_enabled,
        reranker_model=settings.reranker_model,
        schema_linking_enabled=settings.schema_linking_enabled,
    )
    return pipeline, manager, model_log


def evaluate_one(record: dict, pipeline: Pipeline, manager: DatabaseManager,
                 db_name: str, capture: RetrievalCapture, model_log: Path,
                 log_offset: int, timing_repeats: int) -> tuple[dict, int]:
    capture.reset()
    initial_sql = final_sql = schema_text = None
    error = None
    phase_ms: dict[str, float | None] = {}
    reference = execute_timed(manager, db_name, record["reference_sql"])

    try:
        introspection = pipeline.ensure_introspection(db_name)
        phase = time.perf_counter()
        enriched = pipeline.enrichment.run(introspection, db_name)
        phase_ms["enrichment"] = round((time.perf_counter() - phase) * 1000, 3)

        phase = time.perf_counter()
        schema_text = pipeline.rag.run(record["question"], enriched, db_name)
        phase_ms["retrieval"] = round((time.perf_counter() - phase) * 1000, 3)

        phase = time.perf_counter()
        initial_sql = pipeline.sql_generation.run(record["question"], schema_text)
        phase_ms["sql_generation"] = round((time.perf_counter() - phase) * 1000, 3)
    except Exception as exc:
        error = f"Generation failed: {type(exc).__name__}: {exc}"

    initial = (
        execute_timed(manager, db_name, initial_sql) if initial_sql else
        {"valid": False, "rows": None, "duration_ms": None, "error": error}
    )
    initial_ex = results_equal(reference["rows"], initial["rows"], record["reference_sql"])

    correction_eligible = bool(initial_sql) and (not initial["valid"] or not initial["rows"])
    if initial_sql:
        phase = time.perf_counter()
        try:
            final_rows, final_sql = pipeline.self_correction.run(
                initial_sql, db_name, record["question"], schema_text
            )
            final = {
                "valid": True, "rows": final_rows,
                "duration_ms": initial["duration_ms"] if final_sql == initial_sql else None,
                "error": None,
            }
            if final["duration_ms"] is None:
                measured_final = execute_timed(manager, db_name, final_sql)
                final["duration_ms"] = measured_final["duration_ms"]
        except Exception as exc:
            final = {
                "valid": False, "rows": None, "duration_ms": None,
                "error": f"{type(exc).__name__}: {exc}",
            }
            final_sql = initial_sql
            error = error or final["error"]
        phase_ms["self_correction"] = round((time.perf_counter() - phase) * 1000, 3)
    else:
        final = initial

    final_ex = results_equal(reference["rows"], final["rows"], record["reference_sql"])

    if final.get("valid") and final_sql:
        phase = time.perf_counter()
        try:
            pipeline.answer_generation.run(record["question"], final_sql, final["rows"])
        except Exception as exc:
            error = error or f"Answer generation failed: {type(exc).__name__}: {exc}"
        phase_ms["answer_generation"] = round((time.perf_counter() - phase) * 1000, 3)

    # Only normal pipeline phases belong to user-facing latency. Gold execution,
    # evaluator comparisons, and repeated R-VES timing are intentionally excluded.
    end_to_end_ms = round(sum(value or 0 for value in phase_ms.values()), 3)
    timings = (
        benchmark_times(
            manager, db_name, record["reference_sql"], final_sql, timing_repeats
        )
        if final_ex and final_sql else
        {"reference_times_ms": [], "predicted_times_ms": [], "error": None}
    )
    rves = r_ves_item(
        timings["reference_times_ms"], timings["predicted_times_ms"], final_ex
    )
    calls, new_offset = load_model_calls(model_log, log_offset)
    tokens = token_summary(calls)
    retrieval = retrieval_metrics(record, capture.tables, capture.columns)
    result = {
        "id": record["id"],
        "intent_id": record.get("intent_id"),
        "language": record.get("language"),
        "category": record.get("category"),
        "difficulty": record.get("difficulty"),
        "question": record["question"],
        "status": "completed",
        "completed_at": utc_now(),
        "initial_sql": initial_sql,
        "final_sql": final_sql,
        "metrics": {
            "initial_ex": int(initial_ex),
            "final_ex": int(final_ex),
            "initial_valid_sql": int(bool(initial["valid"])),
            "final_valid_sql": int(bool(final["valid"])),
            "table_recall": retrieval["table_recall"],
            "table_precision": retrieval["table_precision"],
            "column_recall": retrieval["column_recall"],
            "r_ves_score": rves["score"],
        },
        "retrieval": retrieval,
        "correction": {
            "attempted": correction_eligible,
            "sql_changed": bool(initial_sql and final_sql and initial_sql.strip() != final_sql.strip()),
            "success": bool(correction_eligible and not initial_ex and final_ex),
        },
        "r_ves": {
            **rves,
            **timings,
            "method": "BIRD Mini-Dev reward thresholds; sqrt(reward) * 100",
        },
        "latency_ms": {
            **phase_ms,
            "initial_sql_execution": initial.get("duration_ms"),
            "final_sql_execution": final.get("duration_ms"),
            "end_to_end": end_to_end_ms,
        },
        "tokens": tokens,
        "model_operations": [call.get("operation") for call in calls],
        "reference_valid": reference["valid"],
        "error": error or final.get("error") or reference.get("error"),
    }
    return result, new_offset


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--db-name", default="test1")
    parser.add_argument("--db-type", default="mssql")
    parser.add_argument("--connection-string", default="")
    parser.add_argument("--run-dir", type=Path)
    parser.add_argument("--resume", type=Path)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--language", choices=["fa", "en"])
    parser.add_argument("--category", action="append")
    parser.add_argument("--timing-repeats", type=int, default=5)
    parser.add_argument("--max-token-budget", type=int)
    parser.add_argument("--retry-failed", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    dataset = args.dataset.resolve()
    records = load_dataset(dataset)
    if args.language:
        records = [r for r in records if r.get("language") == args.language]
    if args.category:
        allowed = set(args.category)
        records = [r for r in records if r.get("category") in allowed]
    if args.limit is not None:
        records = records[:max(0, args.limit)]

    run_dir = (args.resume or args.run_dir)
    if run_dir is None:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        run_dir = ROOT / "evaluation" / "runs" / f"run_{stamp}"
    run_dir = run_dir.resolve()
    run_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = run_dir / "manifest.json"
    manifest = {
        "evaluator_version": EVALUATOR_VERSION,
        "dataset": str(dataset),
        "dataset_sha256": file_hash(dataset),
        "db_name": args.db_name,
        "db_type": args.db_type,
        "timing_repeats": max(1, args.timing_repeats),
        "created_at": utc_now(),
    }
    if manifest_path.exists():
        existing = json.loads(manifest_path.read_text(encoding="utf-8"))
        for key in ("evaluator_version", "dataset_sha256", "db_name", "db_type"):
            if existing.get(key) != manifest.get(key):
                raise RuntimeError(f"Resume manifest mismatch for {key}.")
        manifest = existing
    else:
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    checkpoint_path = run_dir / "checkpoint.jsonl"
    completed = load_checkpoints(checkpoint_path)
    pipeline, manager, model_log = build_runtime(args, run_dir)
    setup_log_offset = model_log.stat().st_size if model_log.exists() else 0
    setup_started = time.perf_counter()
    introspection = pipeline.ensure_introspection(args.db_name)
    pipeline.enrichment.run(introspection, args.db_name)
    manifest["setup_latency_ms"] = round((time.perf_counter() - setup_started) * 1000, 3)
    setup_calls, log_offset = load_model_calls(model_log, setup_log_offset)
    manifest["setup_tokens"] = token_summary(setup_calls)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    capture = RetrievalCapture(pipeline.rag)
    spent_tokens = sum(r.get("tokens", {}).get("total_tokens", 0) for r in completed.values())

    try:
        for index, record in enumerate(records, start=1):
            if record["id"] in completed and not (
                args.retry_failed and completed[record["id"]].get("error")
            ):
                print(f"[{index}/{len(records)}] skip completed {record['id']}")
                continue
            if args.max_token_budget is not None and spent_tokens >= args.max_token_budget:
                print(f"Token budget reached ({spent_tokens}/{args.max_token_budget}); stopping safely.")
                break
            print(f"[{index}/{len(records)}] evaluating {record['id']}")
            result, log_offset = evaluate_one(
                record, pipeline, manager, args.db_name, capture, model_log,
                log_offset, max(1, args.timing_repeats),
            )
            append_checkpoint(checkpoint_path, result)
            completed[result["id"]] = result
            spent_tokens += result.get("tokens", {}).get("total_tokens", 0)
            write_reports(run_dir, list(completed.values()), manifest)
            print(
                f"  EX={result['metrics']['final_ex']} "
                f"valid={result['metrics']['final_valid_sql']} "
                f"table_recall={result['metrics']['table_recall']} "
                f"tokens={result['tokens'].get('total_tokens', 0)}"
            )
    except KeyboardInterrupt:
        print("Interrupted; the completed question checkpoint is preserved.")
    finally:
        write_reports(run_dir, list(completed.values()), manifest)
        print(f"Report: {run_dir / 'report.html'}")
        print(f"Resume: --resume \"{run_dir}\"")
    return 0


if __name__ == "__main__":
    sys.exit(main())
