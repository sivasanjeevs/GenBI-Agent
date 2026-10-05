"""
guard.py – SQL safety validation.

All user-facing SQL passes through this module before execution.
Uses sqlglot to parse and check:
  1. Only SELECT statements allowed (no DML/DDL)
  2. No dangerous functions (e.g. UTL_FILE, DBMS_SCHEDULER)
  3. Statement parses without errors in Oracle dialect
"""

from __future__ import annotations

import re

import sqlglot
import sqlglot.expressions as exp
from loguru import logger


# ─── Blocklist ────────────────────────────────────────────────────────────────

_BLOCKED_KEYWORDS = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|TRUNCATE|ALTER|CREATE|GRANT|REVOKE"
    r"|EXECUTE|EXEC|CALL|MERGE|REPLACE|UTL_FILE|DBMS_SCHEDULER"
    r"|DBMS_PIPE|JAVA|SYS\.EXEC)\b",
    re.IGNORECASE,
)


# ─── Public Interface ─────────────────────────────────────────────────────────

def validate_select_only(sql: str) -> None:
    """
    Validate that `sql` is a safe SELECT-only statement.

    Raises:
        ValueError: if the SQL contains anything other than a SELECT.
    """
    sql = sql.strip()

    # Quick blocklist check (fast path before parsing)
    m = _BLOCKED_KEYWORDS.search(sql)
    if m:
        raise ValueError(
            f"Unsafe SQL detected: keyword '{m.group()}' is not allowed. "
            "Only SELECT queries are permitted."
        )

    # Parse with sqlglot in Oracle dialect
    try:
        statements = sqlglot.parse(sql, dialect="oracle")
    except sqlglot.errors.ParseError as exc:
        raise ValueError(f"SQL parse error: {exc}") from exc

    if not statements:
        raise ValueError("Empty SQL statement")

    for stmt in statements:
        if stmt is None:
            continue
        if not isinstance(stmt, exp.Select):
            raise ValueError(
                f"Only SELECT statements are allowed. Got: {type(stmt).__name__}"
            )

    logger.debug("SQL guard passed")


def clean_sql(sql: str) -> str:
    """
    Strip markdown code fences and normalise whitespace.
    LLMs often return SQL wrapped in ```sql ... ```.
    """
    # Remove code fences
    fenced = re.search(r"```(?:sql|oracle)?\s*([\s\S]+?)\s*```", sql, re.IGNORECASE)
    if fenced:
        sql = fenced.group(1)
    return sql.strip()
