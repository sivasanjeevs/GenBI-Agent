"""
profile.py – Column-level value profiling (Phase 2 / Step 2).

Gathers statistics for every column in every table WITHOUT calling the LLM.
Results feed directly into patterns.py (deterministic analysis) and
enrich.py (LLM enrichment context).

Per-column statistics
──────────────────────
• total_rows        – from the parent table's COUNT(*)
• non_null_count    – COUNT(col) (Oracle counts non-NULLs natively)
• null_pct          – 100.0 * null_count / total_rows
• distinct_count    – COUNT(DISTINCT col)
• min_value / max_value  – for NUMBER / DATE / TIMESTAMP cols
• top_values        – top 15 (val, count) pairs for cols with < 50 distinct
• sample_values     – up to 10 non-null raw values for LLM context

Parallelism
───────────
A ThreadPoolExecutor batches the column profiling queries so that all
columns of a table are profiled concurrently (bounded at 8 threads to
respect the connection pool size of 5 – Oracle handles the queueing).

Public API
──────────
    profile_schemas(tables: list[TableMeta]) -> list[TableProfile]
"""

from __future__ import annotations

import concurrent.futures as cf
from typing import Any

from loguru import logger
from pydantic import BaseModel, Field
from tqdm import tqdm

from app.db import raw_execute
from app.learning.introspect import TableMeta


# ─── Constants ────────────────────────────────────────────────────────────────

# Columns with at most this many distinct values get a top-values histogram.
_LOW_CARDINALITY_THRESHOLD: int = 50

# How many top values to fetch for low-cardinality columns.
_TOP_N: int = 15

# Thread-pool cap (kept ≤ Oracle pool max to avoid connection starvation).
_MAX_WORKERS: int = 4

# Oracle data types we skip for aggregation (not comparable / too large).
_SKIP_AGG_TYPES = frozenset(
    {"CLOB", "BLOB", "NCLOB", "XMLTYPE", "LONG", "LONG RAW", "RAW", "BFILE"}
)

# Types that support MIN / MAX in Oracle
_MINMAX_TYPES = frozenset(
    {
        "NUMBER", "FLOAT", "BINARY_FLOAT", "BINARY_DOUBLE",
        "DATE", "TIMESTAMP", "TIMESTAMP WITH TIME ZONE",
        "TIMESTAMP WITH LOCAL TIME ZONE",
        "VARCHAR2", "NVARCHAR2", "CHAR", "NCHAR",
    }
)


# ─── Pydantic Models ──────────────────────────────────────────────────────────

class ColumnProfile(BaseModel):
    """Statistical profile of a single column."""
    column_name: str
    data_type: str
    total_rows: int
    non_null_count: int
    null_pct: float                          # 0–100
    distinct_count: int
    is_low_cardinality: bool                 # distinct_count < threshold
    top_values: list[dict[str, Any]] = Field(default_factory=list)
    # [{\"value\": <v>, \"count\": <n>}, ...]  – only for low-cardinality cols
    min_value: Any | None = None
    max_value: Any | None = None
    sample_values: list[Any] = Field(default_factory=list)


class TableProfile(BaseModel):
    """Aggregated profile for one table."""
    schema_name: str = Field(..., alias="schema")
    table_name: str
    row_count: int
    columns: list[ColumnProfile] = Field(default_factory=list)

    model_config = {"populate_by_name": True}

    @property
    def full_name(self) -> str:
        return f"{self.schema_name}.{self.table_name}"


# ─── SQL Templates ────────────────────────────────────────────────────────────

# Single-pass stats query per column (avoids multiple round-trips).
# COUNT(col) counts non-NULLs in Oracle – no CASE needed.
_STATS_SQL = """
SELECT
    COUNT(*)              AS total_rows,
    COUNT({col})          AS non_null_count,
    COUNT(DISTINCT {col}) AS distinct_count
FROM {schema}.{table}
"""

_MINMAX_SQL = """
SELECT MIN({col}) AS min_val, MAX({col}) AS max_val
FROM   {schema}.{table}
"""

# Top-N most-frequent values (skips NULLs automatically via WHERE).
_TOP_VALUES_SQL = """
SELECT {col} AS val, COUNT(*) AS cnt
FROM   {schema}.{table}
WHERE  {col} IS NOT NULL
GROUP  BY {col}
ORDER  BY cnt DESC
FETCH  FIRST {top_n} ROWS ONLY
"""

# Reservoir-style sample with Oracle SAMPLE clause; falls back to FETCH FIRST.
_SAMPLE_SQL = """
SELECT {col} AS val
FROM   {schema}.{table}
SAMPLE(5)
WHERE  {col} IS NOT NULL
FETCH  FIRST 10 ROWS ONLY
"""

_SAMPLE_FALLBACK_SQL = """
SELECT {col} AS val
FROM   {schema}.{table}
WHERE  {col} IS NOT NULL
FETCH  FIRST 10 ROWS ONLY
"""


# ─── Per-column Profiling ─────────────────────────────────────────────────────

def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v) if v is not None else default
    except (TypeError, ValueError):
        return default


def _safe_int(v: Any, default: int = 0) -> int:
    try:
        return int(v) if v is not None else default
    except (TypeError, ValueError):
        return default


def _profile_column(
    schema: str,
    table: str,
    col_name: str,
    data_type: str,
    total_rows: int,
) -> ColumnProfile:
    """
    Gather statistics for a single column.

    Uses raw_execute (no SQL guard needed – these are fixed internal queries).
    All exceptions are caught per-stat so a single bad column doesn't abort
    the entire table profile.
    """
    q = {
        "schema": schema,
        "table": table,
        "col": f'"{col_name.upper()}"',
        "top_n": _TOP_N,
    }

    skip_agg = data_type.upper() in _SKIP_AGG_TYPES

    # ── Core stats (total_rows, non_null_count, distinct_count) ──────────────
    non_null_count = total_rows
    distinct_count = 0
    if not skip_agg:
        try:
            rows = raw_execute(_STATS_SQL.format(**q))
            if rows:
                total_rows = _safe_int(rows[0]["total_rows"], total_rows)
                non_null_count = _safe_int(rows[0]["non_null_count"], total_rows)
                distinct_count = _safe_int(rows[0]["distinct_count"], 0)
        except Exception as exc:  # noqa: BLE001
            logger.debug("Stats query failed for {}.{}.{}: {}", schema, table, col_name, exc)

    null_count = total_rows - non_null_count
    null_pct = round((null_count / total_rows * 100.0) if total_rows > 0 else 0.0, 2)
    is_low_card = distinct_count > 0 and distinct_count < _LOW_CARDINALITY_THRESHOLD

    # ── Top values (only for low-cardinality, non-LOB columns) ───────────────
    top_values: list[dict[str, Any]] = []
    if is_low_card and not skip_agg:
        try:
            tv_rows = raw_execute(_TOP_VALUES_SQL.format(**q))
            top_values = [{"value": r["val"], "count": _safe_int(r["cnt"])} for r in tv_rows]
        except Exception as exc:  # noqa: BLE001
            logger.debug("Top-values query failed for {}.{}.{}: {}", schema, table, col_name, exc)

    # ── Min / Max ─────────────────────────────────────────────────────────────
    min_val: Any = None
    max_val: Any = None
    if data_type.upper() in _MINMAX_TYPES and not skip_agg:
        try:
            mm_rows = raw_execute(_MINMAX_SQL.format(**q))
            if mm_rows:
                min_val = mm_rows[0]["min_val"]
                max_val = mm_rows[0]["max_val"]
        except Exception as exc:  # noqa: BLE001
            logger.debug("MinMax query failed for {}.{}.{}: {}", schema, table, col_name, exc)

    # ── Sample values ─────────────────────────────────────────────────────────
    sample_values: list[Any] = []
    if not skip_agg:
        try:
            samp_rows = raw_execute(_SAMPLE_SQL.format(**q))
            sample_values = [r["val"] for r in samp_rows]
        except Exception:  # noqa: BLE001
            # SAMPLE clause not available on all Oracle editions / views
            try:
                samp_rows = raw_execute(_SAMPLE_FALLBACK_SQL.format(**q))
                sample_values = [r["val"] for r in samp_rows]
            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    "Sample query failed for {}.{}.{}: {}", schema, table, col_name, exc
                )

    return ColumnProfile(
        column_name=col_name,
        data_type=data_type,
        total_rows=total_rows,
        non_null_count=non_null_count,
        null_pct=null_pct,
        distinct_count=distinct_count,
        is_low_cardinality=is_low_card,
        top_values=top_values,
        min_value=min_val,
        max_value=max_val,
        sample_values=sample_values,
    )


# ─── Public Interface ─────────────────────────────────────────────────────────

def profile_schemas(tables: list[TableMeta]) -> list[TableProfile]:
    """
    Profile all columns across all provided tables.

    Columns within a single table are profiled in parallel using a
    ThreadPoolExecutor (bounded at _MAX_WORKERS threads).

    Args:
        tables: Output of ``introspect_schemas()``.

    Returns:
        list[TableProfile] – one entry per table, same ordering as input.
    """
    logger.info("Profiling {} tables…", len(tables))
    profiles: list[TableProfile] = []

    for table_meta in tqdm(tables, desc="Profiling tables"):
        schema = table_meta.schema_name
        table = table_meta.table_name
        total_rows = table_meta.row_count or 0

        col_profiles: list[ColumnProfile] = [None] * len(table_meta.columns)  # type: ignore[list-item]

        def _task(idx: int, col: "any") -> tuple[int, ColumnProfile]:  # noqa: ANN001
            return idx, _profile_column(
                schema=schema,
                table=table,
                col_name=col.name,
                data_type=col.data_type,
                total_rows=total_rows,
            )

        with cf.ThreadPoolExecutor(max_workers=_MAX_WORKERS) as pool:
            futures = {
                pool.submit(_task, i, col): i
                for i, col in enumerate(table_meta.columns)
            }
            for fut in tqdm(
                cf.as_completed(futures),
                total=len(futures),
                desc=f"  {schema}.{table}",
                leave=False,
            ):
                idx, cp = fut.result()
                col_profiles[idx] = cp

        profiles.append(
            TableProfile(
                schema=schema,
                table_name=table,
                row_count=total_rows,
                columns=col_profiles,
            )
        )
        logger.debug(
            "Profiled {}.{}: {} columns | total_rows={}",
            schema, table, len(col_profiles), total_rows,
        )

    logger.success("Profiling complete: {} tables", len(profiles))
    return profiles

Table
{
    "schema_name": vid
    "table_name": table 1,
    "row_count": 10
    "column_name": [
        {
            "col_name": col1
        }
    ]
    
    
}