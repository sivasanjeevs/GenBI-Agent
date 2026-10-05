"""
guard.py – Strict SQL security guardrail (Phase 3 / Step 4).

All LLM-generated SQL passes through this module before execution.
The agent must remain a strictly Read-Only Analytics Engine.

Validation pipeline
────────────────────
1. Strip markdown fences and normalise whitespace.
2. Quick keyword blocklist (fast regex path).
3. sqlglot parse in Oracle dialect.
4. Enforce exactly ONE SELECT statement – any other statement type is an
   immediate security failure with a descriptive error.

Public API
──────────
    validate_select_only(sql: str) -> None      # raises ValueError on failure
    clean_sql(sql: str) -> str                  # strip fences + semicolons
"""

from __future__ import annotations

import re

import sqlglot
import sqlglot.expressions as exp
from loguru import logger


# ─── Keyword Blocklist ────────────────────────────────────────────────────────
# Fast path: reject obvious mutations before handing off to sqlglot.

_BLOCKED = re.compile(
    r"\b("
    r"INSERT|UPDATE|DELETE|DROP|TRUNCATE|ALTER|CREATE|GRANT|REVOKE"
    r"|EXECUTE|EXEC|CALL|MERGE|REPLACE"
    r"|UTL_FILE|DBMS_SCHEDULER|DBMS_PIPE|DBMS_SQL|DBMS_UTILITY"
    r"|JAVA|SYS\.EXEC|PRAGMA"
    r")\b",
    re.IGNORECASE,
)


# ─── Public Functions ─────────────────────────────────────────────────────────

def clean_sql(raw: str) -> str:
    """
    Strip markdown code fences and trailing semicolons from LLM-generated SQL.

    Handles:
    • ```sql … ```
    • ```oracle … ```
    • Bare ``` … ```
    • Trailing semicolons (one or more)
    """
    # Remove fenced code blocks
    fenced = re.search(
        r"```(?:sql|oracle|plsql)?\s*([\s\S]+?)\s*```",
        raw,
        re.IGNORECASE,
    )
    sql = fenced.group(1) if fenced else raw
    # Normalise: strip outer whitespace and trailing semicolons
    return sql.strip().rstrip(";").strip()


def validate_select_only(sql: str) -> None:
    """
    Validate that ``sql`` is a safe, single SELECT statement.

    Security levels:
    1. Keyword blocklist – reject immediately if any forbidden keyword appears.
    2. sqlglot parse (Oracle dialect) – raises on syntax errors.
    3. Type check – every parsed statement must be an ``exp.Select``.
    4. Single statement – multiple statements (e.g. "SELECT 1; DROP …") are
       rejected regardless of order.

    Args:
        sql: Cleaned SQL string (no markdown fences, no semicolons).

    Raises:
        ValueError: With a descriptive security message on any violation.
    """
    sql = sql.strip()

    # ── Level 1: keyword blocklist ────────────────────────────────────────────
    m = _BLOCKED.search(sql)
    if m:
        raise ValueError(
            f"SECURITY: Forbidden keyword '{m.group()}' detected. "
            "Only SELECT statements are permitted. "
            "The agent is a read-only analytics engine."
        )

    # ── Level 2: sqlglot parse ────────────────────────────────────────────────
    try:
        statements = sqlglot.parse(sql, dialect="oracle")
    except sqlglot.errors.ParseError as exc:
        raise ValueError(f"SQL parse error (Oracle dialect): {exc}") from exc

    if not statements or all(s is None for s in statements):
        raise ValueError("Empty or un-parseable SQL statement.")

    non_none = [s for s in statements if s is not None]

    # ── Level 3: single statement ─────────────────────────────────────────────
    if len(non_none) != 1:
        raise ValueError(
            f"SECURITY: Only a single SELECT statement is allowed; "
            f"received {len(non_none)} statement(s). "
            "Multi-statement SQL is not permitted."
        )

    # ── Level 4: SELECT type check ────────────────────────────────────────────
    stmt = non_none[0]
    if not isinstance(stmt, exp.Select):
        raise ValueError(
            f"SECURITY: Statement type '{type(stmt).__name__}' is not permitted. "
            "Only SELECT statements are allowed. "
            "The agent is a read-only analytics engine."
        )

    logger.debug("SQL guard passed: single SELECT, no forbidden keywords.")
