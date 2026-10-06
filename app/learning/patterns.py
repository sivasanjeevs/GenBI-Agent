"""
patterns.py – Deterministic structural pattern detection (Phase 2 / Step 3).

No LLM calls.  Pure Python + lightweight SQL probes.

Detections

1. GRAIN        – smallest set of columns where COUNT(DISTINCT cols) == COUNT(*)
                  Verified with an actual SQL query against the DB.
2. JOIN INFER   – undeclared FKs: child col values ⊆ parent col values > 95%
                  (value-containment probe via SQL).
3. SCD TYPE 2   – eff/exp date pairs and/or is_current flag columns.
4. FLAGS/STATUS – low-cardinality (<= 20 distinct) columns matching name heuristics.
5. TABLE TYPE   – dimension | fact | event | bridge | lookup.

Pydantic models are used throughout so enrich.py gets typed inputs.

Public API

    detect_patterns(
        profiles: list[TableProfile],
        tables: list[TableMeta],          # for declared FKs
    ) -> list[ProfileWithPatterns]
"""

from __future__ import annotations

import re
from typing import Any

from loguru import logger
from pydantic import BaseModel, Field

from app.db import raw_execute
from app.learning.introspect import TableMeta
from app.learning.profile import TableProfile

_SCD_EFF = re.compile(
    r"(eff|start|valid|from|begin|strt|effective).*(date|dt|ts|time)", re.I
)
_SCD_EXP = re.compile(
    r"(exp|end|thru|to|until|term|expir).*(date|dt|ts|time)", re.I
)
_SCD_CURR = re.compile(
    r"(is.?current|current.?flag|latest|active.?flag|is.?latest|curr.?ind)", re.I
)
_EVENT_TS = re.compile(
    r"(created|inserted|event|txn|transaction|occurred|processed).*(date|dt|ts|time|at)",
    re.I,
)
_STATUS_COL = re.compile(
    r"^(status|state|flag|is_.+|.+_flag|.+_status|.+_ind|active|enabled|avail.*)$",
    re.I,
)
_KEY_SUFFIX = re.compile(r"^(.+?)(id|key|no|num|code|cd)$", re.I)

# Value-containment threshold for inferred FKs (95 %)
_FK_CONTAINMENT_THRESHOLD: float = 0.95

# Minimum rows in a table before we attempt FK containment probes
_FK_MIN_ROWS: int = 10

class JoinCandidate(BaseModel):
    """A potential join relationship (declared or inferred)."""
    source_column: str
    target_table: str
    target_column: str
    confidence: str          # "declared" | "high" | "medium" | "low"
    containment_pct: float | None = None   # only for inferred FKs

class StatusColumn(BaseModel):
    """A column that looks like a status/flag with known values."""
    column_name: str
    distinct_count: int
    top_values: list[dict[str, Any]] = Field(default_factory=list)

class PatternResult(BaseModel):
    """All detected patterns for one table."""
    grain_description: str
    grain_columns: list[str] = Field(default_factory=list)
    grain_verified: bool = False         # True if SQL COUNT probe confirmed grain

    table_type: str                      # dimension|fact|event|bridge|lookup
    is_scd: bool = False
    scd_eff_col: str | None = None
    scd_exp_col: str | None = None
    scd_current_flag_col: str | None = None

    join_candidates: list[JoinCandidate] = Field(default_factory=list)
    status_columns: list[StatusColumn] = Field(default_factory=list)
    date_columns: list[str] = Field(default_factory=list)
    numeric_measure_columns: list[str] = Field(default_factory=list)

class ProfileWithPatterns(BaseModel):
    """Combines a TableProfile with its detected PatternResult."""
    profile: TableProfile
    meta: TableMeta
    patterns: PatternResult

    model_config = {"arbitrary_types_allowed": True}

def _verify_grain_sql(schema: str, table: str, columns: list[str]) -> bool:
    """
    Run COUNT(*) vs COUNT(DISTINCT col_combo) to confirm uniqueness.
    Returns True when the column set is a unique grain.
    """
    if not columns:
        return False
    # Oracle doesn't support COUNT(DISTINCT (a, b)). We must concatenate.
    cols_expr = " || '|' || ".join(f'"{c.upper()}"' for c in columns)
    try:
        rows = raw_execute(
            f"SELECT COUNT(*) AS total, "
            f"COUNT(DISTINCT {cols_expr}) AS distinct_combo "
            f"FROM {schema}.{table}"
        )
        if rows:
            total = int(rows[0]["total"] or 0)
            distinct = int(rows[0]["distinct_combo"] or 0)
            return total > 0 and total == distinct
    except Exception as exc:  # noqa: BLE001
        logger.debug("Grain SQL failed for {}.{}: {}", schema, table, exc)
    return False

def _detect_grain(
    profile: TableProfile,
    meta: TableMeta,
) -> tuple[str, list[str], bool]:
    """
    Return (description, grain_columns, verified).

    Strategy (in priority order):
    1. Declared PK → verify with SQL.
    2. Columns with zero-null AND suffix pattern → try SQL verify.
    3. Name-heuristic only (unverified).
    """
    schema = profile.schema_name
    table = profile.table_name

    # 1. Declared PK
    pk_cols = meta.primary_key_columns
    if pk_cols:
        verified = _verify_grain_sql(schema, table, pk_cols)
        desc = f"one row per ({', '.join(pk_cols)}) [PK]"
        return desc, pk_cols, verified

    # 2. Zero-null key-like columns
    zero_null_key_cols = [
        c.column_name
        for c in profile.columns
        if c.null_pct == 0 and _KEY_SUFFIX.match(c.column_name)
    ]
    if zero_null_key_cols:
        verified = _verify_grain_sql(schema, table, zero_null_key_cols)
        if verified:
            desc = f"one row per ({', '.join(zero_null_key_cols)}) [inferred key]"
            return desc, zero_null_key_cols, True

    # 3. Unverified heuristic
    all_key_cols = [
        c.column_name for c in profile.columns if _KEY_SUFFIX.match(c.column_name)
    ]
    if all_key_cols:
        desc = f"grain unknown – candidate key columns: ({', '.join(all_key_cols)})"
        return desc, all_key_cols, False

    return "grain unknown – no obvious key columns", [], False

def _value_containment_pct(
    child_schema: str,
    child_table: str,
    child_col: str,
    parent_schema: str,
    parent_table: str,
    parent_col: str,
) -> float | None:
    """
    Estimate what percentage of non-null child values exist in the parent column.

    Uses a NOT EXISTS sub-select for correctness on large tables.
    Returns None on any SQL error.
    """
    sql = f"""
    SELECT
        COUNT(*) AS total_non_null,
        SUM(CASE WHEN EXISTS (
                SELECT 1
                FROM   {parent_schema}.{parent_table} p
                WHERE  p."{parent_col.upper()}" = c."{child_col.upper()}"
            ) THEN 1 ELSE 0 END) AS matched
    FROM {child_schema}.{child_table} c
    WHERE c."{child_col.upper()}" IS NOT NULL
    """
    try:
        rows = raw_execute(sql)
        if rows:
            total = int(rows[0]["total_non_null"] or 0)
            matched = int(rows[0]["matched"] or 0)
            return (matched / total) if total > 0 else None
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "Containment probe failed {}.{}.{} → {}.{}.{}: {}",
            child_schema, child_table, child_col,
            parent_schema, parent_table, parent_col,
            exc,
        )
    return None

def _infer_joins(
    profile: TableProfile,
    meta: TableMeta,
    all_profiles: dict[str, TableProfile],
    all_metas: dict[str, TableMeta],
) -> list[JoinCandidate]:
    """
    Build a list of JoinCandidates combining:
    1. Declared FK constraints (confidence = "declared").
    2. Value-containment inference for un-declared candidate joins.
    """
    candidates: list[JoinCandidate] = []
    seen: set[tuple[str, str, str]] = set()

    for fk in meta.foreign_keys:
        if fk.ref_table and fk.ref_columns:
            for src_col, tgt_col in zip(fk.columns, fk.ref_columns):
                key = (src_col, fk.ref_table, tgt_col)
                if key not in seen:
                    seen.add(key)
                    candidates.append(
                        JoinCandidate(
                            source_column=src_col,
                            target_table=fk.ref_table,
                            target_column=tgt_col,
                            confidence="declared",
                        )
                    )

    if (profile.row_count or 0) < _FK_MIN_ROWS:
        return candidates

    for col in profile.columns:
        m = _KEY_SUFFIX.match(col.column_name.upper())
        if not m:
            continue
        base = m.group(1).rstrip("_")
        if not base:
            continue

        # Look for a table whose name equals the base word
        for candidate_full, cand_profile in all_profiles.items():
            tgt_table_name = cand_profile.table_name.upper()
            if tgt_table_name != base and not tgt_table_name.startswith(base + "_"):
                continue
            if cand_profile.table_name == profile.table_name:
                continue

            # Find a PK or same-named col in the target
            tgt_meta = all_metas.get(candidate_full)
            tgt_pk = tgt_meta.primary_key_columns if tgt_meta else []
            tgt_col = (
                col.column_name
                if any(c.name == col.column_name for c in cand_profile.columns)
                else (tgt_pk[0] if tgt_pk else None)
            )
            if not tgt_col:
                continue

            key = (col.column_name, candidate_full, tgt_col)
            if key in seen:
                continue
            seen.add(key)

            pct = _value_containment_pct(
                profile.schema_name, profile.table_name, col.column_name,
                cand_profile.schema_name, cand_profile.table_name, tgt_col,
            )
            if pct is not None and pct >= _FK_CONTAINMENT_THRESHOLD:
                candidates.append(
                    JoinCandidate(
                        source_column=col.column_name,
                        target_table=f"{cand_profile.schema_name}.{cand_profile.table_name}",
                        target_column=tgt_col,
                        confidence="high" if pct >= 0.99 else "medium",
                        containment_pct=round(pct * 100, 1),
                    )
                )
                logger.debug(
                    "Inferred FK: {}.{} → {}.{} (containment={:.1f}%)",
                    profile.table_name, col.column_name,
                    cand_profile.table_name, tgt_col,
                    (pct or 0) * 100,
                )

    return candidates

def _find_scd_signals(
    profile: TableProfile,
) -> tuple[str | None, str | None, str | None]:
    eff_col = exp_col = curr_col = None
    for c in profile.columns:
        if _SCD_EFF.search(c.column_name) and eff_col is None:
            eff_col = c.column_name
        if _SCD_EXP.search(c.column_name) and exp_col is None:
            exp_col = c.column_name
        if _SCD_CURR.search(c.column_name) and curr_col is None:
            curr_col = c.column_name
    return eff_col, exp_col, curr_col

def _find_status_columns(profile: TableProfile) -> list[StatusColumn]:
    """Low-cardinality columns matching status/flag naming patterns."""
    results: list[StatusColumn] = []
    for c in profile.columns:
        if _STATUS_COL.match(c.column_name) and c.distinct_count <= 20:
            results.append(
                StatusColumn(
                    column_name=c.column_name,
                    distinct_count=c.distinct_count,
                    top_values=c.top_values[:10],
                )
            )
    return results

def _find_date_cols(profile: TableProfile) -> list[str]:
    return [
        c.column_name
        for c in profile.columns
        if "DATE" in c.data_type.upper() or "TIMESTAMP" in c.data_type.upper()
    ]

def _find_numeric_measures(profile: TableProfile) -> list[str]:
    """NUMBER columns that are not key-like and not nearly empty."""
    key_cols = {
        c.column_name.lower()
        for c in profile.columns
        if _KEY_SUFFIX.match(c.column_name)
    }
    return [
        c.column_name
        for c in profile.columns
        if c.data_type.upper() in {"NUMBER", "FLOAT", "BINARY_FLOAT", "BINARY_DOUBLE"}
        and c.column_name.lower() not in key_cols
        and c.null_pct < 90
    ]

def _classify_table_type(
    profile: TableProfile,
    is_scd: bool,
    has_event_ts: bool,
) -> str:
    n_date = sum(
        1 for c in profile.columns
        if "DATE" in c.data_type.upper() or "TIMESTAMP" in c.data_type.upper()
    )
    n_num = sum(
        1 for c in profile.columns
        if c.data_type.upper() in {"NUMBER", "FLOAT", "BINARY_FLOAT", "BINARY_DOUBLE"}
    )
    if is_scd:
        return "dimension"
    if has_event_ts and n_date >= 1:
        return "event"
    if n_num >= 3 and n_date >= 1:
        return "fact"
    if (profile.row_count or 0) < 1000 and n_num == 0:
        return "lookup"
    return "dimension"

def detect_patterns(
    profiles: list[TableProfile],
    tables: list[TableMeta],
) -> list[ProfileWithPatterns]:
    """
    Run all deterministic pattern detectors over every table profile.

    Args:
        profiles: Output of ``profile_schemas()``.
        tables:   Output of ``introspect_schemas()`` (needed for declared FKs
                  and grain verification).

    Returns:
        list[ProfileWithPatterns] – profiles annotated with detected patterns.
    """
    logger.info("Detecting patterns for {} tables…", len(profiles))

    # Build lookup maps for cross-table inference
    profile_map: dict[str, TableProfile] = {
        f"{p.schema_name}.{p.table_name}".upper(): p for p in profiles
    }
    meta_map: dict[str, TableMeta] = {
        f"{m.schema_name}.{m.table_name}".upper(): m for m in tables
    }

    results: list[ProfileWithPatterns] = []

    for profile in profiles:
        full_upper = profile.full_name.upper()
        meta = meta_map.get(full_upper)
        if meta is None:
            # Shouldn't happen, but be defensive
            meta = TableMeta(schema=profile.schema_name, table_name=profile.table_name)

        eff_col, exp_col, curr_col = _find_scd_signals(profile)
        is_scd = bool(eff_col and (exp_col or curr_col))

        has_event_ts = any(_EVENT_TS.search(c.column_name) for c in profile.columns)

        grain_desc, grain_cols, grain_verified = _detect_grain(profile, meta)

        join_candidates = _infer_joins(profile, meta, profile_map, meta_map)

        status_cols = _find_status_columns(profile)
        date_cols = _find_date_cols(profile)
        measure_cols = _find_numeric_measures(profile)
        table_type = _classify_table_type(profile, is_scd, has_event_ts)

        pattern = PatternResult(
            grain_description=grain_desc,
            grain_columns=grain_cols,
            grain_verified=grain_verified,
            table_type=table_type,
            is_scd=is_scd,
            scd_eff_col=eff_col,
            scd_exp_col=exp_col,
            scd_current_flag_col=curr_col,
            join_candidates=join_candidates,
            status_columns=status_cols,
            date_columns=date_cols,
            numeric_measure_columns=measure_cols,
        )
        results.append(ProfileWithPatterns(profile=profile, meta=meta, patterns=pattern))

        logger.debug(
            "{}: type={} scd={} grain_verified={} joins={} flags={}",
            profile.full_name, table_type, is_scd, grain_verified,
            len(join_candidates), [s.column_name for s in status_cols],
        )

    logger.success("Pattern detection complete: {} tables", len(results))
    return results
