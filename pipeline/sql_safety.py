"""Shared SQL safety checks for read-only analytical queries."""

from __future__ import annotations

import re


READ_ONLY_START = re.compile(r"^\s*(?:SELECT\b|WITH\b)", re.IGNORECASE)
FORBIDDEN_SQL = re.compile(
    r"\b(?:INSERT|UPDATE|DELETE|MERGE|DROP|ALTER|TRUNCATE|EXEC(?:UTE)?|"
    r"CREATE|GRANT|REVOKE|DENY|DBCC|BACKUP|RESTORE|INTO|USE|SET|DECLARE|"
    r"BEGIN|COMMIT|ROLLBACK|WAITFOR|OPENROWSET|OPENDATASOURCE|OPENQUERY|"
    r"BULK|KILL|SHUTDOWN)\b",
    re.IGNORECASE,
)


def strip_sql_comments(sql: str) -> str:
    return re.sub(r"--[^\n]*|/\*.*?\*/", " ", str(sql or ""), flags=re.DOTALL)


def _scan_sql(sql: str) -> tuple[str, bool]:
    """Return executable tokens while masking literals, comments, and identifiers."""
    source = str(sql or "")
    output: list[str] = []
    index = 0
    state = "code"

    while index < len(source):
        char = source[index]
        following = source[index + 1] if index + 1 < len(source) else ""

        if state == "code":
            if char == "-" and following == "-":
                output.extend((" ", " "))
                index += 2
                state = "line_comment"
                continue
            if char == "/" and following == "*":
                output.extend((" ", " "))
                index += 2
                state = "block_comment"
                continue
            if char == "'":
                output.append(" ")
                index += 1
                state = "string"
                continue
            if char == "[":
                output.append(" ")
                index += 1
                state = "bracket_identifier"
                continue
            if char == '"':
                output.append(" ")
                index += 1
                state = "quoted_identifier"
                continue
            output.append(char)
            index += 1
            continue

        if state == "line_comment":
            output.append("\n" if char == "\n" else " ")
            index += 1
            if char == "\n":
                state = "code"
            continue

        if state == "block_comment":
            if char == "*" and following == "/":
                output.extend((" ", " "))
                index += 2
                state = "code"
            else:
                output.append("\n" if char == "\n" else " ")
                index += 1
            continue

        closing = {
            "string": "'",
            "bracket_identifier": "]",
            "quoted_identifier": '"',
        }[state]
        output.append(" ")
        index += 1
        if char != closing:
            continue
        if index < len(source) and source[index] == closing:
            output.append(" ")
            index += 1
        else:
            state = "code"

    return "".join(output), state in {"code", "line_comment"}


def sql_code_only(sql: str) -> str:
    """Mask data literals and quoted identifiers before policy inspection."""
    return _scan_sql(sql)[0]


def has_multiple_statements(sql: str) -> bool:
    statements = [
        part.strip()
        for part in sql_code_only(sql).split(";")
        if part.strip()
    ]
    return len(statements) > 1


def contains_forbidden_sql(sql: str) -> bool:
    return bool(FORBIDDEN_SQL.search(sql_code_only(sql)))


def is_read_only_sql(sql: str) -> bool:
    code, balanced = _scan_sql(sql)
    code = code.strip()
    if not balanced or not code or has_multiple_statements(code):
        return False
    if not READ_ONLY_START.search(code) or FORBIDDEN_SQL.search(code):
        return False
    # A WITH clause is permitted only when it ultimately produces a SELECT.
    return code.upper().startswith("SELECT") or bool(
        re.search(r"\bSELECT\b", code, re.I)
    )


def ensure_read_only_sql(sql: str) -> str:
    if not is_read_only_sql(sql):
        raise RuntimeError(
            "Only read-only SELECT queries are allowed. Data-changing clauses, "
            "SELECT INTO, multiple statements, and administrative commands are blocked."
        )
    return sql
