"""
db.py – Oracle DB connection pool + hardened SQL execution.

Architecture
────────────
• Uses oracledb in *thin* mode (no Oracle Instant Client needed).
• A small connection pool (min=1, max=5) is created lazily on first use
  and shared for the lifetime of the process.
• run_query() is the public entry-point for all user-facing SQL.
  It runs the full security pipeline: strip → guard → execute → serialise.
• raw_execute() is a bypass for known-safe internal introspection queries.

Security pipeline (run_query)
──────────────────────────────
1. Strip trailing semicolons and whitespace.
2. Parse with sqlglot (Oracle dialect) – reject anything that is not a
   single SELECT statement (no DML / DDL / multi-statement).
3. Enforce row-cap and per-query call_timeout.
4. Serialise Decimal, datetime, date, bytes (LOB) to JSON-safe types.
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from decimal import Decimal
from typing import Any, Generator

import oracledb
import sqlglot
import sqlglot.expressions as exp
from loguru import logger

from app.config import settings


# ─── Type Aliases ────────────────────────────────────────────────────────────

QueryResult = dict[str, Any]
"""
{
    "columns": list[str],
    "rows":    list[dict[str, Any]],
    "row_count": int,
    "elapsed_ms": float,
    "sql": str,
}
"""


# ─── Connection Pool ──────────────────────────────────────────────────────────

_pool: oracledb.ConnectionPool | None = None


def init_pool() -> None:
    """Initialise the Oracle connection pool (call once at startup).

    Safe to call multiple times – subsequent calls are no-ops.
    """
    global _pool
    if _pool is not None:
        return

    logger.info(
        "Initialising Oracle pool → {}@{}",
        settings.oracle_user,
        settings.dsn,
    )
    # Thin mode is the default in oracledb ≥ 1.x; no Instant Client required.
    _pool = oracledb.create_pool(
        user=settings.oracle_user,
        password=settings.oracle_password,
        dsn=settings.dsn,
        min=1,
        max=5,
        increment=1,
    )
    logger.success("Oracle pool ready (thin mode)")


def close_pool() -> None:
    """Drain and close the pool gracefully (call at shutdown)."""
    global _pool
    if _pool:
        _pool.close()
        _pool = None
        logger.info("Oracle pool closed")


@contextmanager
def get_connection() -> Generator[oracledb.Connection, None, None]:
    """Yield a pooled Oracle connection; auto-release on exit."""
    if _pool is None:
        init_pool()
    conn: oracledb.Connection = _pool.acquire()  # type: ignore[union-attr]
    try:
        yield conn
    finally:
        _pool.release(conn)  # type: ignore[union-attr]


# ─── SQL Guard ────────────────────────────────────────────────────────────────

#: Regex-level quick-reject (fast path, before sqlglot parse)
import re as _re

_BLOCKED = _re.compile(
    r"\b("
    r"INSERT|UPDATE|DELETE|DROP|TRUNCATE|ALTER|CREATE|GRANT|REVOKE"
    r"|EXECUTE|EXEC|CALL|MERGE|REPLACE|UTL_FILE|DBMS_SCHEDULER"
    r"|DBMS_PIPE|JAVA|SYS\.EXEC"
    r")\b",
    _re.IGNORECASE,
)


def _strip_sql(sql: str) -> str:
    """Strip whitespace, trailing semicolons, and markdown fences."""
    # Remove optional ```sql ... ``` fences that LLMs sometimes add
    fenced = _re.search(r"```(?:sql|oracle)?\s*([\s\S]+?)\s*```", sql, _re.IGNORECASE)
    if fenced:
        sql = fenced.group(1)
    # Strip trailing semicolons (multiple) and whitespace
    return sql.strip().rstrip(";").strip()


def _guard_select_only(sql: str) -> str:
    """
    Validate that *sql* is a single SELECT statement.

    Returns the cleaned SQL string.

    Raises:
        ValueError – if the SQL is unsafe or unparseable.
    """
    sql = _strip_sql(sql)

    # --- 1. Keyword blocklist (fast) ---
    m = _BLOCKED.search(sql)
    if m:
        raise ValueError(
            f"Unsafe SQL: keyword '{m.group()}' is not permitted. "
            "Only SELECT queries are allowed."
        )

    # --- 2. Parse with sqlglot (Oracle dialect) ---
    try:
        statements = sqlglot.parse(sql, dialect="oracle")
    except sqlglot.errors.ParseError as exc:
        raise ValueError(f"SQL parse error: {exc}") from exc

    if not statements or all(s is None for s in statements):
        raise ValueError("Empty or un-parseable SQL statement.")

    # --- 3. Enforce single SELECT ---
    non_none = [s for s in statements if s is not None]
    if len(non_none) != 1:
        raise ValueError(
            f"Only a single SELECT statement is permitted; "
            f"got {len(non_none)} statement(s)."
        )
    stmt = non_none[0]
    if not isinstance(stmt, exp.Select):
        raise ValueError(
            f"Only SELECT statements are allowed. "
            f"Got: {type(stmt).__name__}"
        )

    logger.debug("SQL guard passed")
    return sql


# ─── Value Serialisation ──────────────────────────────────────────────────────

import datetime as _dt


def _to_json_safe(value: Any) -> Any:
    """
    Recursively convert Oracle-specific types to JSON-serialisable Python types.

    Handled:
    • decimal.Decimal  → float (or int if whole number)
    • datetime.datetime / datetime.date / datetime.time → ISO-8601 str
    • bytes / bytearray (LOB snapshots)  → hex str prefixed with "0x"
    • oracledb.LOB objects              → decoded str / hex str
    • None                              → None (pass-through)
    """
    if value is None:
        return None
    if isinstance(value, Decimal):
        # Return int when there is no fractional part to avoid float noise
        return int(value) if value % 1 == 0 else float(value)
    if isinstance(value, _dt.datetime):
        return value.isoformat()
    if isinstance(value, _dt.date):
        return value.isoformat()
    if isinstance(value, _dt.time):
        return value.isoformat()
    if isinstance(value, (bytes, bytearray)):
        return "0x" + value.hex()
    # oracledb LOB objects expose a .read() method
    if hasattr(value, "read") and callable(value.read):
        try:
            raw = value.read()
            if isinstance(raw, bytes):
                return "0x" + raw.hex()
            return str(raw)
        except Exception:  # noqa: BLE001
            return "<LOB read error>"
    return value


def _serialise_row(row: tuple[Any, ...], columns: list[str]) -> dict[str, Any]:
    return {col: _to_json_safe(val) for col, val in zip(columns, row)}


# ─── Public Interface ─────────────────────────────────────────────────────────


def run_query(
    sql: str,
    max_rows: int = 100,
    timeout: int = 30,
) -> QueryResult:
    """
    Execute a validated SELECT query and return JSON-safe results.

    Security pipeline:
      1. Strip fences / trailing semicolons.
      2. sqlglot guard – reject anything that is not a single SELECT.
      3. Execute with call_timeout and row cap.
      4. Serialise all values to JSON-safe Python types.

    Args:
        sql:      Raw SQL string (may include markdown fences from LLM output).
        max_rows: Maximum number of rows to fetch.  Defaults to 100;
                  hard-capped at settings.sql_max_rows.
        timeout:  Per-query timeout in **seconds**.  Defaults to 30.

    Returns:
        QueryResult dict::

            {
                "columns":   ["col_a", "col_b", ...],
                "rows":      [{"col_a": 1, "col_b": "x"}, ...],
                "row_count": int,
                "elapsed_ms": float,
                "sql":       str,   # the cleaned, executed SQL
            }

    Raises:
        ValueError   – SQL failed the security guard.
        RuntimeError – DB-level execution error.
    """
    # Honour hard cap from config
    effective_max_rows = min(max_rows, settings.sql_max_rows)
    effective_timeout = timeout or settings.sql_timeout_seconds

    # Security gate – raises ValueError on failure
    clean = _guard_select_only(sql)

    start = time.perf_counter()
    try:
        with get_connection() as conn:
            # Oracle call_timeout is in milliseconds
            conn.call_timeout = effective_timeout * 1_000

            cursor = conn.cursor()
            cursor.execute(clean)

            columns: list[str] = [col[0].lower() for col in (cursor.description or [])]
            raw_rows: list[tuple[Any, ...]] = cursor.fetchmany(effective_max_rows)

    except oracledb.DatabaseError as exc:
        elapsed_ms = (time.perf_counter() - start) * 1000
        logger.error("DB error after {:.1f}ms: {}", elapsed_ms, exc)
        raise RuntimeError(f"Database error: {exc}") from exc

    elapsed_ms = (time.perf_counter() - start) * 1000

    rows = [_serialise_row(row, columns) for row in raw_rows]

    logger.debug(
        "Query OK | rows={} | elapsed={:.1f}ms",
        len(rows),
        elapsed_ms,
    )
    return {
        "columns": columns,
        "rows": rows,
        "row_count": len(rows),
        "elapsed_ms": round(elapsed_ms, 2),
        "sql": clean,
    }


def safe_execute(
    sql: str,
    params: dict[str, Any] | None = None,
    *,
    max_rows: int | None = None,
    timeout: int | None = None,
) -> QueryResult:
    """
    Backwards-compatible wrapper around run_query that also accepts
    bind parameters (used by internal introspection callers).

    Named params (```:name``` style) are supported; positional params are not.
    """
    _max_rows = max_rows or settings.sql_max_rows
    _timeout = timeout or settings.sql_timeout_seconds
    clean = _guard_select_only(sql)

    start = time.perf_counter()
    try:
        with get_connection() as conn:
            conn.call_timeout = _timeout * 1_000
            cursor = conn.cursor()
            cursor.execute(clean, params or {})

            columns = [col[0].lower() for col in (cursor.description or [])]
            raw_rows = cursor.fetchmany(_max_rows)

    except oracledb.DatabaseError as exc:
        elapsed_ms = (time.perf_counter() - start) * 1000
        logger.error("DB error after {:.1f}ms: {}", elapsed_ms, exc)
        raise RuntimeError(str(exc)) from exc

    elapsed_ms = (time.perf_counter() - start) * 1000
    rows = [_serialise_row(row, columns) for row in raw_rows]

    logger.debug("Query OK | rows={} | elapsed={:.1f}ms", len(rows), elapsed_ms)
    return {
        "columns": columns,
        "rows": rows,
        "row_count": len(rows),
        "elapsed_ms": round(elapsed_ms, 2),
        "sql": clean,
    }


def raw_execute(
    sql: str,
    params: dict[str, Any] | None = None,
    *,
    fetch_all: bool = True,
) -> list[dict[str, Any]]:
    """
    Low-level execute **without** the SQL guard.

    Reserved for known-safe internal introspection queries (e.g. querying
    ALL_TABLES). Do **not** pass user-supplied SQL here.
    """
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(sql, params or {})
        columns = [col[0].lower() for col in (cursor.description or [])]
        raw_rows = cursor.fetchall() if fetch_all else cursor.fetchmany(1000)
        return [_serialise_row(row, columns) for row in raw_rows]
