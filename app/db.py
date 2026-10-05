"""
db.py – Oracle DB connection pool + safe SQL execution.

Uses oracledb in thin mode (no Oracle Instant Client needed).
All queries go through `safe_execute` which:
  - validates the query is SELECT-only via guard.py
  - enforces row limits and timeouts
  - returns rows as list[dict]
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Any, Generator

import oracledb
from loguru import logger

from app.config import settings


# ─── Connection Pool ──────────────────────────────────────────────────────────

_pool: oracledb.ConnectionPool | None = None


def init_pool() -> None:
    """Initialise the Oracle connection pool (call once at startup)."""
    global _pool
    if _pool is not None:
        return

    logger.info(
        f"Initialising Oracle pool → {settings.oracle_user}@{settings.dsn}"
    )
    _pool = oracledb.create_pool(
        user=settings.oracle_user,
        password=settings.oracle_password,
        dsn=settings.dsn,
        min=1,
        max=5,
        increment=1,
        # thin mode is default in oracledb >= 1.x
    )
    logger.success("Oracle pool ready")


def close_pool() -> None:
    """Drain and close the pool gracefully."""
    global _pool
    if _pool:
        _pool.close()
        _pool = None
        logger.info("Oracle pool closed")


@contextmanager
def get_connection() -> Generator[oracledb.Connection, None, None]:
    """Yield a pooled Oracle connection as a context manager."""
    if _pool is None:
        init_pool()
    conn = _pool.acquire()  # type: ignore[union-attr]
    try:
        yield conn
    finally:
        _pool.release(conn)  # type: ignore[union-attr]


# ─── Safe Execution ───────────────────────────────────────────────────────────

def safe_execute(
    sql: str,
    params: dict[str, Any] | None = None,
    *,
    max_rows: int | None = None,
    timeout: int | None = None,
) -> dict[str, Any]:
    """
    Execute a validated SELECT query and return results.

    Returns:
        {
            "columns": [...],
            "rows": [...],        # list[dict]
            "row_count": int,
            "elapsed_ms": float,
            "sql": str,
        }

    Raises:
        ValueError  – if the query is not SELECT-only
        RuntimeError – if execution fails after guard passes
    """
    # Inline import to avoid circular dependency at module load time
    from app.answering.guard import validate_select_only

    validate_select_only(sql)  # raises ValueError if not safe

    _max_rows = max_rows or settings.sql_max_rows
    _timeout = timeout or settings.sql_timeout_seconds

    start = time.perf_counter()
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            # Oracle: set query timeout via call_timeout (ms)
            conn.call_timeout = _timeout * 1_000

            cursor.execute(sql, params or {})
            columns = [col[0].lower() for col in cursor.description]
            raw_rows = cursor.fetchmany(_max_rows)

            rows = [dict(zip(columns, row)) for row in raw_rows]
            elapsed_ms = (time.perf_counter() - start) * 1000

            logger.debug(
                f"Query OK | rows={len(rows)} | elapsed={elapsed_ms:.1f}ms"
            )
            return {
                "columns": columns,
                "rows": rows,
                "row_count": len(rows),
                "elapsed_ms": round(elapsed_ms, 2),
                "sql": sql,
            }
    except oracledb.DatabaseError as exc:
        elapsed_ms = (time.perf_counter() - start) * 1000
        logger.error(f"DB error after {elapsed_ms:.1f}ms: {exc}")
        raise RuntimeError(str(exc)) from exc


def raw_execute(
    sql: str,
    params: dict[str, Any] | None = None,
    *,
    fetch_all: bool = True,
) -> list[dict[str, Any]]:
    """
    Low-level execute without guard (for introspection queries that are
    already known-safe internal calls).
    """
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(sql, params or {})
        columns = [col[0].lower() for col in cursor.description]
        rows = cursor.fetchall() if fetch_all else cursor.fetchmany(1000)
        return [dict(zip(columns, row)) for row in rows]
