"""
profile.py – Column value profiling.

For each column we collect:
  - null_pct: fraction of NULLs
  - distinct_count: approximate cardinality
  - top_values: up to 20 most-frequent values + their counts
  - min / max (for numeric and date columns)
  - sample_values: random 10 values (for LLM enrichment context)

This is the raw material the LLM uses to infer meaning (e.g. that
STATUS='A' means "active", or that a date column named EFF_DT / EXP_DT
signals a slowly-changing dimension).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from loguru import logger
from tqdm import tqdm

from app.db import raw_execute
from app.learning.introspect import TableMeta


# ─── Data Classes ─────────────────────────────────────────────────────────────

@dataclass
class ColumnProfile:
    column_name: str
    data_type: str
    null_pct: float
    distinct_count: int
    top_values: list[dict[str, Any]]   # [{"value": ..., "count": ...}, ...]
    min_value: Any | None
    max_value: Any | None
    sample_values: list[Any]


@dataclass
class TableProfile:
    schema: str
    table_name: str
    row_count: int
    columns: list[ColumnProfile] = field(default_factory=list)

    @property
    def full_name(self) -> str:
        return f"{self.schema}.{self.table_name}"


# ─── Profiling Queries ────────────────────────────────────────────────────────

_NULL_PCT_SQL = """
SELECT
    ROUND(
        SUM(CASE WHEN {col} IS NULL THEN 1 ELSE 0 END) * 100.0 / COUNT(*),
        2
    ) AS null_pct
FROM {schema}.{table}
"""

_DISTINCT_SQL = """
SELECT COUNT(DISTINCT {col}) AS distinct_count FROM {schema}.{table}
"""

_TOP_VALUES_SQL = """
SELECT {col} AS val, COUNT(*) AS cnt
FROM {schema}.{table}
WHERE {col} IS NOT NULL
GROUP BY {col}
ORDER BY cnt DESC
FETCH FIRST 20 ROWS ONLY
"""

_MIN_MAX_SQL = """
SELECT MIN({col}) AS min_val, MAX({col}) AS max_val
FROM {schema}.{table}
"""

_SAMPLE_SQL = """
SELECT {col} AS val
FROM {schema}.{table}
SAMPLE(5)
WHERE {col} IS NOT NULL
FETCH FIRST 10 ROWS ONLY
"""


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _profile_column(
    schema: str,
    table: str,
    col_name: str,
    data_type: str,
    row_count: int,
) -> ColumnProfile:
    fmt = {"schema": schema, "table": table, "col": f'"{col_name.upper()}"'}

    # Null %
    try:
        null_pct_rows = raw_execute(_NULL_PCT_SQL.format(**fmt))
        null_pct = float(null_pct_rows[0]["null_pct"] or 0) if null_pct_rows else 0.0
    except Exception:
        null_pct = -1.0

    # Distinct count
    try:
        dist_rows = raw_execute(_DISTINCT_SQL.format(**fmt))
        distinct_count = int(dist_rows[0]["distinct_count"] or 0) if dist_rows else 0
    except Exception:
        distinct_count = -1

    # Top values (skip for LOB / CLOB types)
    top_values: list[dict[str, Any]] = []
    if data_type not in ("CLOB", "BLOB", "NCLOB", "XMLTYPE", "LONG"):
        try:
            top_rows = raw_execute(_TOP_VALUES_SQL.format(**fmt))
            top_values = [{"value": r["val"], "count": r["cnt"]} for r in top_rows]
        except Exception:
            pass

    # Min / Max
    min_val, max_val = None, None
    if data_type not in ("CLOB", "BLOB", "NCLOB", "XMLTYPE", "LONG"):
        try:
            mm_rows = raw_execute(_MIN_MAX_SQL.format(**fmt))
            if mm_rows:
                min_val = mm_rows[0]["min_val"]
                max_val = mm_rows[0]["max_val"]
        except Exception:
            pass

    # Sample values
    sample_values: list[Any] = []
    if data_type not in ("CLOB", "BLOB", "NCLOB", "XMLTYPE", "LONG"):
        try:
            samp_rows = raw_execute(_SAMPLE_SQL.format(**fmt))
            sample_values = [r["val"] for r in samp_rows]
        except Exception:
            # SAMPLE clause not available on all Oracle editions
            try:
                fallback_sql = f"""
                SELECT {fmt['col']} AS val
                FROM {schema}.{table}
                WHERE {fmt['col']} IS NOT NULL
                FETCH FIRST 10 ROWS ONLY
                """
                samp_rows = raw_execute(fallback_sql)
                sample_values = [r["val"] for r in samp_rows]
            except Exception:
                pass

    return ColumnProfile(
        column_name=col_name,
        data_type=data_type,
        null_pct=null_pct,
        distinct_count=distinct_count,
        top_values=top_values,
        min_value=min_val,
        max_value=max_val,
        sample_values=sample_values,
    )


# ─── Public Interface ─────────────────────────────────────────────────────────

def profile_schemas(tables: list[TableMeta]) -> list[TableProfile]:
    """
    Profile all columns in the given tables.
    Returns a list of TableProfile objects.
    """
    logger.info(f"Profiling {len(tables)} tables…")
    profiles: list[TableProfile] = []

    for table_meta in tqdm(tables, desc="Profiling tables"):
        row_count = table_meta.row_count or 0
        col_profiles = []

        for col in tqdm(
            table_meta.columns,
            desc=f"  {table_meta.full_name}",
            leave=False,
        ):
            cp = _profile_column(
                schema=table_meta.schema,
                table=table_meta.table_name,
                col_name=col.name,
                data_type=col.data_type,
                row_count=row_count,
            )
            col_profiles.append(cp)

        profiles.append(
            TableProfile(
                schema=table_meta.schema,
                table_name=table_meta.table_name,
                row_count=row_count,
                columns=col_profiles,
            )
        )
        logger.debug(f"Profiled {table_meta.full_name}: {len(col_profiles)} columns")

    logger.success(f"Profiling complete: {len(profiles)} tables")
    return profiles
