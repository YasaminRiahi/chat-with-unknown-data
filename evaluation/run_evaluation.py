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
from evaluation.query_features import annotate, classify, feature_summary


EVALUATOR_VERSION = 2
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


ORDER_REQUEST_PATTERN = re.compile(
    r"\b(?:order(?:ed)?|sort(?:ed)?)\s+by\b|"
    r"\b(?:ascending|descending|highest|lowest|latest|earliest|newest|oldest)\b|"
    r"\b(?:first|last|top|bottom)\s+\d+\b|\bmost\s+recent\b|"
    r"به\s*ترتیب|مرتب|صعودی|نزولی|بیشترین|کمترین|بالاترین|پایین[‌ ]?ترین|"
    r"جدیدترین|قدیمی[‌ ]?ترین|آخرین|اولین|برتر",
    re.IGNORECASE,
)


def question_requests_order(question: str) -> bool:
    """Return whether row ordering/ranking is explicitly part of the request."""
    return bool(ORDER_REQUEST_PATTERN.search(str(question or "")))


def record_order_sensitive(record: dict) -> bool:
    """Use an explicit benchmark override, otherwise infer from the question."""
    explicit = record.get("order_sensitive")
    if isinstance(explicit, bool):
        return explicit
    return question_requests_order(record.get("question", ""))


def results_equal(reference: list[dict] | None, predicted: list[dict] | None,
                  reference_sql: str, *, order_sensitive: bool | None = None) -> bool:
    if reference is None or predicted is None:
        return False
    if reference and predicted and len(reference[0]) != len(predicted[0]):
        return False
    ordered = (
        bool(re.search(r"\bORDER\s+BY\b", reference_sql, re.IGNORECASE))
        if order_sensitive is None else order_sensitive
    )
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
        if "order_sensitive" in record and not isinstance(record["order_sensitive"], bool):
            raise ValueError(f"order_sensitive must be boolean: {record['id']}")
        seen.add(record["id"])
    return records


def append_checkpoint(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def atomic_write_text(path: Path, content: str, *, encoding: str = "utf-8") -> None:
    """Replace a report file only after its complete content reaches disk."""
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding=encoding) as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)


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
    annotate(records)
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
        "by_feature": feature_summary(records),
        "by_feature_count": grouped(records, "feature_count"),
        "most_missed_tables": missing_tables.most_common(15),
        "most_missed_columns": missing_columns.most_common(15),
    }


def write_csv(path: Path, records: list[dict]) -> None:
    fields = [
        "id", "language", "category", "features", "feature_count", "initial_sql", "final_sql",
        "initial_ex", "final_ex", "initial_valid_sql", "final_valid_sql",
        "table_recall", "table_precision", "column_recall", "correction_attempted",
        "correction_success", "r_ves_score", "end_to_end_ms", "llm_calls",
        "total_tokens", "error",
    ]
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for record in records:
            metrics = record.get("metrics", {})
            writer.writerow({
                "id": record["id"],
                "language": record.get("language"),
                "category": record.get("category"),
                "features": "|".join(record.get("features", [])),
                "feature_count": record.get("feature_count"),
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
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)


def make_debug_records(records: list[dict]) -> list[dict]:
    """Return the small, stable diagnostic view used by debug artifacts."""
    debug_records = []
    for record in records:
        metrics = record.get("metrics", {})
        retrieval = record.get("retrieval", {})
        debug_records.append({
            "id": record.get("id"),
            "question": record.get("question"),
            "reference_sql": record.get("reference_sql"),
            "final_generated_sql": record.get("final_sql"),
            "error": record.get("error"),
            "ex": metrics.get("final_ex"),
            "table_recall": metrics.get("table_recall"),
            "table_precision": metrics.get("table_precision"),
            "column_recall": metrics.get("column_recall"),
            "retrieved_tables": retrieval.get("retrieved_tables", []),
            "retrieved_columns": retrieval.get("retrieved_columns", []),
        })
    return debug_records


def write_debug_html(path: Path, records: list[dict]) -> None:
    """Write a self-contained question debugger from checkpoint records."""
    payload = json.dumps(
        make_debug_records(records), ensure_ascii=False, separators=(",", ":")
    )
    # Prevent arbitrary question/SQL text from terminating the inline script.
    payload = (
        payload.replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )
    document = """<!doctype html>
<html lang="en" dir="ltr" data-theme="dark"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Evaluation Debugger</title>
<style>
:root{color-scheme:dark;--bg:#090d16;--panel:#111827;--panel-2:#1f2937;--panel-3:#374151;--border:rgba(169,175,180,.16);--text:#e2e8f0;--muted:#94a3b8;--title:#fff3e3;--accent:#748da4;--terracotta:#d28378;--sage:#a6b7a1;--sand:#eac8ab;--good:#8db9a8;--bad:#e19a91;--warn:#e0b27c;--code:#090d16;--shadow:0 24px 70px rgba(0,0,0,.32);--radius:22px;--font:-apple-system,BlinkMacSystemFont,"Segoe UI",Arial,sans-serif}
html[data-theme="light"]{color-scheme:light;--bg:#fff7ec;--panel:#fff3e3;--panel-2:#f4d3c0;--panel-3:#eac8ab;--border:rgba(163,145,123,.28);--text:#2d4f56;--muted:#6e4e3d;--title:#0f2c3d;--good:#547a6e;--bad:#a6534c;--warn:#946834;--code:#17212b;--shadow:0 18px 48px rgba(110,78,61,.12)}
*{box-sizing:border-box}body{min-height:100vh;margin:0;background:radial-gradient(circle at 8% 0%,rgba(116,141,164,.18),transparent 30%),radial-gradient(circle at 92% 12%,rgba(210,131,120,.13),transparent 28%),radial-gradient(circle at 50% 100%,rgba(166,183,161,.10),transparent 28%),var(--bg);color:var(--text);font:14px/1.5 var(--font)}
main{width:min(1180px,calc(100% - 32px));margin:auto;padding:28px 0 42px}.toolbar,.panel{background:color-mix(in srgb,var(--panel) 92%,transparent);border:1px solid var(--border);border-radius:var(--radius);padding:20px;margin-bottom:16px;box-shadow:0 12px 30px rgba(0,0,0,.10)}
.toolbar{position:relative;overflow:hidden;padding:28px;background:linear-gradient(145deg,color-mix(in srgb,var(--panel) 92%,transparent),color-mix(in srgb,var(--panel-2) 82%,transparent));box-shadow:var(--shadow)}.toolbar:before{content:"";position:absolute;inset:0 0 auto;height:5px;background:linear-gradient(90deg,var(--accent),var(--terracotta),var(--sage),#c4936a)}
.hero-row{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:16px;align-items:start}.eyebrow{color:var(--accent);font-size:12px;font-weight:800;letter-spacing:.08em;text-transform:uppercase}h1{margin:9px 0 4px;color:var(--title);font-size:clamp(27px,4vw,42px);line-height:1.15}.muted{color:var(--muted)}
.theme-toggle{border:1px solid var(--border);border-radius:999px;background:var(--panel-2);color:var(--text);cursor:pointer;font-weight:800;padding:10px 14px;white-space:nowrap}.controls{display:grid;grid-template-columns:minmax(220px,1fr) auto;gap:10px;margin-top:20px}
select,button{font:inherit;padding:11px 13px;border:1px solid var(--border);border-radius:10px;background:var(--panel-2);color:var(--text)}button{cursor:pointer}select:focus,button:focus{outline:2px solid var(--accent);outline-offset:2px}.metrics{display:grid;grid-template-columns:repeat(auto-fit,minmax(145px,1fr));gap:12px;background:transparent;border:0;box-shadow:none;padding:0}
.metric{min-height:105px;border:1px solid var(--border);border-radius:var(--radius);padding:17px;background:color-mix(in srgb,var(--panel) 92%,transparent);box-shadow:0 12px 30px rgba(0,0,0,.10);position:relative;overflow:hidden}.metric:before{content:"";position:absolute;inset:0 auto 0 0;width:5px;background:var(--metric-color,var(--accent))}.metric:nth-child(2){--metric-color:var(--terracotta)}.metric:nth-child(3){--metric-color:var(--sage)}.metric:nth-child(4){--metric-color:#c4936a}.metric span{display:block;color:var(--muted);font-size:12px;font-weight:800;text-transform:uppercase;letter-spacing:.04em}.metric b{display:block;margin-top:12px;color:var(--title);font-size:26px}
.good{color:var(--good)!important}.bad{color:var(--bad)!important}.warn{color:var(--warn)!important}h2{color:var(--title);font-size:17px;margin:0 0 10px}pre{white-space:pre-wrap;word-break:break-word;direction:ltr;text-align:left;background:var(--code);color:#e5e7eb;padding:15px;border:1px solid var(--border);border-radius:12px;min-height:54px;overflow:auto}
.question{font-size:16px;line-height:1.8;white-space:pre-wrap}.id-row{display:flex;align-items:center;justify-content:space-between;gap:12px}.question-id{direction:ltr;text-align:left;user-select:text;overflow-wrap:anywhere;color:var(--sand);font:600 14px/1.5 ui-monospace,SFMono-Regular,Consolas,monospace}.copy-button{flex:0 0 auto}.chips{display:flex;flex-wrap:wrap;gap:8px}.chip{background:var(--panel-2);border:1px solid var(--border);border-radius:999px;padding:6px 10px}.error{border-left:5px solid var(--bad)}.hidden{display:none}@media(max-width:650px){main{width:min(100% - 20px,1180px);padding:12px 0}.toolbar{padding:22px 18px}.hero-row,.controls{grid-template-columns:1fr}.theme-toggle{justify-self:start}.id-row{align-items:flex-start;flex-direction:column}}
</style></head><body><main>
<section class="toolbar"><div class="hero-row"><div><div class="eyebrow">Text-to-SQL diagnostics</div><h1>Evaluation Debugger</h1><div id="count" class="muted"></div></div><button class="theme-toggle" id="themeToggle" type="button" aria-label="Toggle color theme">Light mode</button></div>
<div class="controls"><select id="questionSelect" aria-label="Choose a question"></select><button id="failedButton" type="button">Next failed</button></div></section>
<section class="panel"><h2>Question ID</h2><div class="id-row"><div id="questionId" class="question-id"></div><button id="copyQuestionId" class="copy-button" type="button">Copy ID</button></div></section>
<section class="panel"><h2>Question</h2><div id="question" class="question"></div></section>
<section class="panel metrics" id="metrics"></section>
<section class="panel error" id="errorPanel"><h2>Error</h2><div id="error"></div></section>
<section class="panel"><h2>Reference SQL</h2><pre id="referenceSql"></pre></section>
<section class="panel"><h2>Final generated SQL</h2><pre id="generatedSql"></pre></section>
<section class="panel"><h2>Retrieved tables</h2><div class="chips" id="tables"></div></section>
<section class="panel"><h2>Retrieved columns</h2><div class="chips" id="columns"></div></section>
</main><script>
const records=__DEBUG_DATA__;
const select=document.getElementById('questionSelect');
const root=document.documentElement;
const themeToggle=document.getElementById('themeToggle');
let savedTheme=null;try{savedTheme=localStorage.getItem('evaluation-debug-theme')}catch(error){}
const initialTheme=savedTheme||(matchMedia('(prefers-color-scheme:light)').matches?'light':'dark');
function setTheme(theme){root.dataset.theme=theme;themeToggle.textContent=theme==='dark'?'Light mode':'Dark mode';try{localStorage.setItem('evaluation-debug-theme',theme)}catch(error){}}
setTheme(initialTheme);themeToggle.addEventListener('click',()=>setTheme(root.dataset.theme==='dark'?'light':'dark'));
const text=(value)=>value===null||value===undefined||value===''?'—':String(value);
const percent=(value)=>value===null||value===undefined?'—':(Number(value)*100).toFixed(1)+'%';
const setText=(id,value)=>document.getElementById(id).textContent=text(value);
async function copyText(value){if(navigator.clipboard&&window.isSecureContext){await navigator.clipboard.writeText(value);return}const area=document.createElement('textarea');area.value=value;area.style.position='fixed';area.style.opacity='0';document.body.appendChild(area);area.select();document.execCommand('copy');area.remove()}
const chips=(id,values)=>{const box=document.getElementById(id);box.replaceChildren();(values||[]).forEach(value=>{const item=document.createElement('span');item.className='chip';item.textContent=value;box.appendChild(item)});if(!box.children.length)box.textContent='—'};
records.forEach((record,index)=>{const option=document.createElement('option');option.value=index;option.textContent=(record.ex===1?'PASS':'FAIL')+' · '+record.id;select.appendChild(option)});
document.getElementById('count').textContent=records.length+' completed questions · '+records.filter(record=>record.ex!==1).length+' failed';
function show(index){const r=records[index];if(!r)return;setText('questionId',r.id);setText('question',r.question);setText('referenceSql',r.reference_sql);setText('generatedSql',r.final_generated_sql);setText('error',r.error||'No runtime error; the generated result differed from the reference result.');document.getElementById('errorPanel').classList.toggle('hidden',r.ex===1&&!r.error);const values=[['EX',r.ex,r.ex===1?'good':'bad'],['Table recall',percent(r.table_recall),''],['Table precision',percent(r.table_precision),''],['Column recall',percent(r.column_recall),'']];const metrics=document.getElementById('metrics');metrics.replaceChildren();values.forEach(([label,value,cls])=>{const item=document.createElement('div');item.className='metric';const name=document.createElement('span');name.textContent=label;const val=document.createElement('b');val.className=cls;val.textContent=text(value);item.append(name,val);metrics.appendChild(item)});chips('tables',r.retrieved_tables);chips('columns',r.retrieved_columns);select.value=index}
select.addEventListener('change',()=>show(Number(select.value)));
document.getElementById('copyQuestionId').addEventListener('click',async(event)=>{const r=records[Number(select.value)];if(!r)return;const button=event.currentTarget;try{await copyText(String(r.id));button.textContent='Copied';setTimeout(()=>button.textContent='Copy ID',1200)}catch(error){button.textContent='Copy failed';setTimeout(()=>button.textContent='Copy ID',1600)}});
document.getElementById('failedButton').addEventListener('click',()=>{if(!records.length)return;let index=Number(select.value);for(let step=1;step<=records.length;step++){const candidate=(index+step)%records.length;if(records[candidate].ex!==1){show(candidate);break}}});
show(0);
</script></body></html>""".replace("__DEBUG_DATA__", payload)
    atomic_write_text(path, document)


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
{bar_chart('Execution Accuracy by Feature', summary['by_feature'], 'execution_accuracy')}
{bar_chart('Table Recall بر اساس دسته', summary['by_category'], 'table_recall')}
{bar_chart('Column Recall بر اساس دسته', summary['by_category'], 'column_recall')}
<section><h2>سؤال‌های ناموفق ({len(failed)})</h2><table><thead><tr><th>ID</th><th>سؤال</th><th>خطا/نتیجه</th></tr></thead><tbody>{failed_rows}</tbody></table></section>
<section><h2>فایل‌های همراه</h2><p><code>summary.json</code> خلاصه ماشینی، <code>per_question.csv</code> جزئیات و <code>checkpoint.jsonl</code> امکان ادامه اجرا را فراهم می‌کنند.</p></section>
</main></body></html>"""
    atomic_write_text(path, document)


def _report_number(value: Any, digits: int = 1) -> str:
    if value is None:
        return "—"
    if isinstance(value, int):
        return f"{value:,}"
    if isinstance(value, float):
        return f"{value:,.{digits}f}"
    return str(value)


def _render_report_template(template: str, values: dict[str, str]) -> str:
    rendered = template
    for key, value in values.items():
        rendered = rendered.replace("{{" + key + "}}", value)
    return rendered


def _report_metric_card(label: str, value: str, color: str) -> str:
    return (
        f'<article class="card" style="--card-color:{color}">'
        f'<span>{html.escape(label)}</span><b>{html.escape(value)}</b></article>'
    )


def _report_bar_chart(title: str, groups: dict[str, dict], metric: str) -> str:
    palette = [
        "#748da4", "#d28378", "#a6b7a1", "#c4936a",
        "#e5b0a0", "#547a6e", "#eac8ab", "#8e8e6c",
    ]
    bars = []
    for index, (name, values) in enumerate(groups.items()):
        value = values.get(metric)
        if value is None:
            continue
        width = max(0, min(100, float(value) * 100))
        safe_name = html.escape(name)
        bars.append(
            f'<div class="bar-row" style="--bar-color:{palette[index % len(palette)]}">'
            f'<span class="bar-name" title="{safe_name}">{safe_name}</span>'
            f'<div class="track"><i style="width:{width:.1f}%"></i></div>'
            f'<b class="bar-value">{width:.1f}%</b></div>'
        )
    body = "".join(bars) or '<p class="empty">No data available.</p>'
    return f'<article class="section"><h2>{html.escape(title)}</h2>{body}</article>'


def _report_vertical_chart(title: str, groups: dict[str, dict], metric: str) -> str:
    palette = [
        "#748da4", "#d28378", "#a6b7a1", "#c4936a",
        "#e5b0a0", "#547a6e", "#eac8ab", "#8e8e6c",
    ]
    bars = []
    for index, (name, values) in enumerate(groups.items()):
        value = values.get(metric)
        if value is None:
            continue
        height = max(0, min(100, float(value) * 100))
        safe_name = html.escape(name)
        bars.append(
            f'<div class="vertical-item" style="--bar-color:{palette[index % len(palette)]}">'
            f'<div class="vertical-track"><i style="height:{height:.1f}%"></i></div>'
            f'<div class="vertical-value">{height:.1f}%</div>'
            f'<div class="vertical-name" title="{safe_name}">{safe_name}</div>'
            '</div>'
        )
    body = (
        f'<div class="vertical-chart">{"".join(bars)}</div>'
        if bars else '<p class="empty">No data available.</p>'
    )
    return f'<article class="section"><h2>{html.escape(title)}</h2>{body}</article>'


def _report_metric_bars(title: str, metrics: list[tuple[str, Any]]) -> str:
    groups = {
        label: {"value": value}
        for label, value in metrics
    }
    return _report_bar_chart(title, groups, "value")


def _report_distribution_block(title: str, records: list[dict], field: str, color_offset: int = 0) -> str:
    palette = [
        "#748da4", "#d28378", "#a6b7a1", "#c4936a",
        "#e5b0a0", "#547a6e", "#eac8ab", "#8e8e6c",
    ]
    total = len(records)
    counts = Counter(str(record.get(field) or "unknown") for record in records)
    if not total or not counts:
        body = '<p class="empty">No data available.</p>'
    else:
        rows = []
        for index, (name, count) in enumerate(sorted(counts.items())):
            percent = count / total * 100
            color = palette[(index + color_offset) % len(palette)]
            safe_name = html.escape(name)
            rows.append(
                f'<div class="distribution-row" style="--bar-color:{color}">'
                f'<span title="{safe_name}">{safe_name}</span>'
                f'<b>{percent:.1f}%</b>'
                f'<div class="mini-track"><i style="width:{percent:.1f}%"></i></div>'
                '</div>'
            )
        body = "".join(rows)
    return f'<div class="distribution"><h3>{html.escape(title)}</h3>{body}</div>'


def _report_dataset_profile(records: list[dict]) -> str:
    content = "".join([
        _report_feature_distribution(records),
        '<div class="distribution-stack">',
        _report_distribution_block("Language mix", records, "language", 4),
        _report_distribution_block("Feature count (not difficulty)", records, "feature_count", 0),
        '</div>',
    ])
    return (
        '<article class="section wide">'
        '<h2>Dataset composition</h2>'
        f'<div class="distribution-grid">{content}</div>'
        '<p>Features describe the reference SQL; typo marks intentional input errors. '
        'Groups overlap, so counts must not be added. Feature count is descriptive, not a difficulty score. '
        'EX uses stored execution results, including recorded failures; no queries were rerun.</p>'
        + _report_feature_table(records) +
        '</article>'
    )


def _report_feature_table(records: list[dict]) -> str:
    rows = []
    for label, values in feature_summary(records).items():
        rows.append('<tr><td title="' + html.escape(values['description']) + '">' + label + '</td>'
            + f"<td>{values['questions']}</td><td>{values['scored_questions']}</td>"
            + f"<td>{format_percent(values['initial_execution_accuracy'])}</td>"
            + f"<td>{format_percent(values['execution_accuracy'])}</td>"
            + f"<td>{format_percent(values['correction_gain'])}</td>"
            + f"<td>{values['correction_attempted']}</td><td>{values['recovered_questions']}</td>"
            + f"<td>{values['errors']}</td></tr>")
    return ('<h3>Results by required feature</h3><div class="table-wrap"><table><thead><tr>'
        '<th>Feature</th><th>Questions</th><th>Scored</th><th>Initial EX</th><th>Final EX</th>'
        '<th>Gain</th><th>Correction attempts</th><th>Recovered (0 → 1)</th><th>Errors</th>'
        '</tr></thead><tbody>' + ''.join(rows) + '</tbody></table></div>')


def _report_feature_distribution(records: list[dict]) -> str:
    rows = []
    palette = ["#748da4", "#d28378", "#a6b7a1", "#c4936a", "#e5b0a0", "#547a6e", "#eac8ab", "#8e8e6c"]
    for index, (label, values) in enumerate(feature_summary(records).items()):
        percent = values['questions'] / len(records) * 100 if records else 0
        rows.append(
            f'<div class="distribution-row" style="--bar-color:{palette[index % len(palette)]}">'
            f'<span title="{html.escape(values["description"])}">{html.escape(label)}</span>'
            f'<b>{values["questions"]} / {len(records)} ({percent:.1f}%)</b>'
            f'<div class="mini-track"><i style="width:{percent:.1f}%"></i></div></div>'
        )
    return '<div class="distribution"><h3>Required features (overlapping)</h3>' + ''.join(rows) + '</div>'


def _report_missed_items(items: list[tuple[str, int]]) -> str:
    if not items:
        return '<p class="empty">No missed items recorded.</p>'
    chips = [
        f'<span class="chip"><span>{html.escape(name)}</span><b>{count}</b></span>'
        for name, count in items
    ]
    return f'<div class="chips">{"".join(chips)}</div>'


def write_html(path: Path, summary: dict, records: list[dict]) -> None:
    metrics = summary["metrics"]
    palette = ["#748da4", "#d28378", "#a6b7a1", "#c4936a", "#e5b0a0", "#547a6e"]
    cards = [
        ("Valid SQL Rate", format_percent(metrics["final_valid_sql_rate"])),
        ("Table Recall", format_percent(metrics["table_recall"])),
        ("Column Recall", format_percent(metrics["column_recall"])),
        ("Correction Gain", format_percent(metrics["correction_gain"])),
        ("Correction Success", format_percent(metrics["self_correction_success_rate"])),
        ("R-VES", "—" if metrics["r_ves"] is None else f'{metrics["r_ves"]:.2f}'),
        ("Median E2E", f'{metrics["end_to_end_latency_ms"]["median"] or 0:.1f} ms'),
        ("Average Tokens", f'{metrics["average_tokens"] or 0:,.0f}'),
        ("Average LLM Calls", f'{metrics["average_llm_calls"] or 0:.2f}'),
    ]
    failed = [r for r in records if not r.get("metrics", {}).get("final_ex")]
    if failed:
        failed_rows = "".join(
            "<tr>"
            f"<td>{html.escape(r['id'])}</td>"
            f"<td>{html.escape(str(r.get('question', '')))}</td>"
            f"<td>{html.escape(', '.join(r.get('features', [])))}</td>"
            f"<td>{html.escape(str(r.get('error') or 'Wrong result'))}</td>"
            "</tr>"
            for r in failed[:100]
        )
        failed_table = (
            '<div class="table-wrap"><table><thead><tr>'
            '<th>ID</th><th>Question</th><th>Features</th><th>Error / result</th>'
            f'</tr></thead><tbody>{failed_rows}</tbody></table></div>'
        )
    else:
        failed_table = '<p class="empty">All questions passed successfully.</p>'

    template = Path(__file__).with_name("report_template.html").read_text(encoding="utf-8")
    final_accuracy = metrics["final_execution_accuracy"]
    initial_accuracy = metrics["initial_execution_accuracy"]
    gain = (final_accuracy or 0) - (initial_accuracy or 0)
    score_note = (
        f"Initial execution accuracy was {format_percent(initial_accuracy)}. "
        f"Self-correction changed the final score by {format_percent(gain)} across "
        f"{len(records)} completed questions."
    )
    document = _render_report_template(template, {
        "title": "Text-to-SQL Evaluation Report",
        "generated_at": html.escape(summary["generated_at"]),
        "completed_questions": _report_number(len(records), digits=0),
        "primary_score": format_percent(final_accuracy),
        "score_note": html.escape(score_note),
        "metric_cards": "".join(
            _report_metric_card(label, value, palette[index % len(palette)])
            for index, (label, value) in enumerate(cards)
        ),
        "dataset_profile": _report_dataset_profile(records),
        "performance_summary": _report_metric_bars("Performance summary", [
            ("Initial execution accuracy", initial_accuracy),
            ("Final execution accuracy", final_accuracy),
            ("Final valid SQL rate", metrics["final_valid_sql_rate"]),
            ("Table recall", metrics["table_recall"]),
            ("Column recall", metrics["column_recall"]),
        ]),
        "charts": "\n".join([
            _report_bar_chart("Execution Accuracy by Language", summary["by_language"], "execution_accuracy"),
            _report_bar_chart("Execution Accuracy by Feature (overlapping groups)", summary["by_feature"], "execution_accuracy"),
            _report_bar_chart("Table Recall by Feature", summary["by_feature"], "table_recall"),
            _report_bar_chart("Column Recall by Feature", summary["by_feature"], "column_recall"),
        ]),
        "missed_tables": _report_missed_items(summary["most_missed_tables"]),
        "missed_columns": _report_missed_items(summary["most_missed_columns"]),
        "failed_count": _report_number(len(failed), digits=0),
        "failed_table": failed_table,
    })
    atomic_write_text(path, document)


def write_reports(run_dir: Path, records: list[dict], manifest: dict) -> None:
    summary = make_summary(records, manifest)
    atomic_write_text(
        run_dir / "summary.json",
        json.dumps(summary, ensure_ascii=False, indent=2),
    )
    atomic_write_text(
        run_dir / "debug_eval.json",
        json.dumps(make_debug_records(records), ensure_ascii=False, indent=2),
    )
    write_csv(run_dir / "per_question.csv", records)
    write_html(run_dir / "report.html", summary, records)
    write_debug_html(run_dir / "debug.html", records)


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
    order_sensitive = record_order_sensitive(record)
    initial_ex = results_equal(
        reference["rows"], initial["rows"], record["reference_sql"],
        order_sensitive=order_sensitive,
    )

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

    final_ex = results_equal(
        reference["rows"], final["rows"], record["reference_sql"],
        order_sensitive=order_sensitive,
    )

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
        **classify(record),
        "order_sensitive": order_sensitive,
        "question": record["question"],
        "reference_sql": record["reference_sql"],
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
    parser.add_argument(
        "--reports-only", action="store_true",
        help="Rebuild reports from checkpoint.jsonl without database/model setup.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    dataset = args.dataset.resolve()
    all_records = load_dataset(dataset)
    records = all_records
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
    checkpoint_path = run_dir / "checkpoint.jsonl"
    completed = load_checkpoints(checkpoint_path)
    dataset_by_id = {record["id"]: record for record in all_records}
    # Checkpoints created before debug artifacts did not retain reference SQL.
    # Hydrate diagnostic-only fields from the hash-verified source dataset so
    # resumed historical runs get complete debug output too.
    for record_id, completed_record in completed.items():
        source_record = dataset_by_id.get(record_id, {})
        completed_record.setdefault("question", source_record.get("question"))
        completed_record.setdefault("reference_sql", source_record.get("reference_sql"))
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
        try:
            existing = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            if completed:
                raise RuntimeError(
                    "manifest.json is incomplete but checkpoint.jsonl contains "
                    "completed questions. Restore the manifest or use a new run directory."
                ) from exc
            print("WARNING: incomplete manifest with no checkpoints; rebuilding it safely.")
        else:
            for key in ("evaluator_version", "db_name", "db_type"):
                if existing.get(key) != manifest.get(key):
                    raise RuntimeError(f"Resume manifest mismatch for {key}.")
            old_dataset_hash = existing.get("dataset_sha256")
            if old_dataset_hash != manifest["dataset_sha256"]:
                print(
                    "Dataset changed since this run started; keeping all "
                    "completed checkpoint IDs and using the new dataset for "
                    "questions that have not run yet."
                )
                existing["dataset"] = str(dataset)
                existing["dataset_sha256"] = manifest["dataset_sha256"]
                existing["dataset_updated_at"] = utc_now()
            manifest = existing
    atomic_write_text(manifest_path, json.dumps(manifest, ensure_ascii=False, indent=2))
    if args.reports_only:
        write_reports(run_dir, list(completed.values()), manifest)
        print(f"Rebuilt reports from {checkpoint_path}")
        print(f"Report: {run_dir / 'report.html'}")
        return 0
    pipeline, manager, model_log = build_runtime(args, run_dir)
    setup_log_offset = model_log.stat().st_size if model_log.exists() else 0
    setup_started = time.perf_counter()
    introspection = pipeline.ensure_introspection(args.db_name)
    pipeline.enrichment.run(introspection, args.db_name)
    manifest["setup_latency_ms"] = round((time.perf_counter() - setup_started) * 1000, 3)
    setup_calls, log_offset = load_model_calls(model_log, setup_log_offset)
    manifest["setup_tokens"] = token_summary(setup_calls)
    atomic_write_text(manifest_path, json.dumps(manifest, ensure_ascii=False, indent=2))
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
