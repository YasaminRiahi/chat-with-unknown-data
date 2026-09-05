"""Shared SQL safety checks for read-only analytical queries."""

from __future__ import annotations

import re


READ_ONLY_START = re.compile(r"^\s*(?:SELECT\b|WITH\b)", re.IGNORECASE)
FORBIDDEN_SQL = re.compile(
    r"\b(?:INSERT|UPDATE|DELETE|MERGE|DROP|ALTER|TRUNCATE|EXEC(?:UTE)?|"
    r"CREATE|GRANT|REVOKE|DENY|DBCC|BACKUP|RESTORE)\b",
    re.IGNORECASE,
)


def strip_sql_comments(sql: str) -> str:
    return re.sub(r"--[^\n]*|/\*.*?\*/", " ", str(sql or ""), flags=re.DOTALL)


def contains_forbidden_sql(sql: str) -> bool:
    return bool(FORBIDDEN_SQL.search(strip_sql_comments(sql)))


def is_read_only_sql(sql: str) -> bool:
    stripped = strip_sql_comments(sql)
    return bool(READ_ONLY_START.search(stripped)) and not FORBIDDEN_SQL.search(stripped)


def ensure_read_only_sql(sql: str) -> str:
    if not is_read_only_sql(sql):
        raise RuntimeError(
            "Only read-only SELECT queries are allowed. Data changes such as "
            "INSERT, UPDATE, DELETE, DROP, or ALTER are not supported."
        )
    return sql
