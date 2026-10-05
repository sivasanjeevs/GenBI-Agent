"""
patterns.py – Structural pattern detection.

Detects automatically from schema + profile data:

1. GRAIN  – the level of uniqueness of each table (e.g. one row per
             subscriber per day, one row per order)
2. JOINS  – which tables are related (FK graph + name heuristics)
3. SCD    – slowly-changing dimension detection via eff_dt / exp_dt /
             is_current / latest_flag naming patterns
4. EVENTS – event/transaction tables: append-only, timestamped
5. FLAGS  – binary/status columns ("active", "available for sale", etc.)

Output enriches each TableProfile with a `patterns` dict.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from loguru import logger

from app.learning.profile import TableProfile


# ─── Pattern Heuristics ───────────────────────────────────────────────────────

# Column name patterns that suggest SCD Type 2
_SCD_EFF_PATTERNS = re.compile(
    r"(eff|start|valid|from|begin|strt).*(date|dt|ts|time)", re.I
)
_SCD_EXP_PATTERNS = re.compile(
    r"(exp|end|thru|to|until|term).*(date|dt|ts|time)", re.I
)
_SCD_CURRENT_FLAG = re.compile(
    r"(is.?current|current.?flag|latest|active.?flag|is.?latest)", re.I
)

# Column name patterns that suggest event/transaction table
_EVENT_TS_PATTERNS = re.compile(
    r"(created|inserted|event|txn|transaction|occurred).*(date|dt|ts|time|at)", re.I
)

# Column name patterns for status / flag columns
_STATUS_PATTERNS = re.compile(
    r"^(status|state|flag|is_.+|.+_flag|.+_status|.+_ind|active|enabled)$", re.I
)

# Common surrogate / natural key suffixes
_KEY_SUFFIXES = re.compile(r"(.*?)(id|key|no|num|code|cd)$", re.I)


# ─── Data Classes ─────────────────────────────────────────────────────────────

@dataclass
class PatternResult:
    grain_description: str
    grain_columns: list[str]         # columns that together uniquely identify a row
    table_type: str                  # "dimension" | "fact" | "event" | "bridge" | "lookup"
    is_scd: bool
    scd_eff_col: str | None
    scd_exp_col: str | None
    scd_current_flag_col: str | None
    join_candidates: list[dict[str, Any]]  # [{table, on_column, confidence}]
    status_columns: list[dict[str, Any]]   # [{column, top_values}]
    date_columns: list[str]
    numeric_measure_columns: list[str]


@dataclass
class ProfileWithPatterns:
    profile: TableProfile
    patterns: PatternResult


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _find_scd_signals(profile: TableProfile) -> tuple[str | None, str | None, str | None]:
    eff_col = exp_col = curr_col = None
    for c in profile.columns:
        if _SCD_EFF_PATTERNS.search(c.column_name) and eff_col is None:
            eff_col = c.column_name
        if _SCD_EXP_PATTERNS.search(c.column_name) and exp_col is None:
            exp_col = c.column_name
        if _SCD_CURRENT_FLAG.search(c.column_name) and curr_col is None:
            curr_col = c.column_name
    return eff_col, exp_col, curr_col


def _find_status_columns(profile: TableProfile) -> list[dict[str, Any]]:
    results = []
    for c in profile.columns:
        if _STATUS_PATTERNS.match(c.column_name):
            results.append({
                "column": c.column_name,
                "distinct_count": c.distinct_count,
                "top_values": c.top_values[:10],
            })
    return results


def _classify_table_type(
    profile: TableProfile,
    is_scd: bool,
    has_event_ts: bool,
) -> str:
    col_names = [c.column_name.lower() for c in profile.columns]
    n_date_cols = sum(1 for c in profile.columns if "DATE" in c.data_type or "TIMESTAMP" in c.data_type)
    n_num_cols = sum(1 for c in profile.columns if c.data_type in ("NUMBER", "FLOAT", "BINARY_FLOAT"))

    if is_scd:
        return "dimension"
    if has_event_ts and n_date_cols >= 1:
        return "event"
    if n_num_cols >= 3 and n_date_cols >= 1:
        return "fact"
    if profile.row_count is not None and profile.row_count < 1000 and n_num_cols == 0:
        return "lookup"
    return "dimension"


def _detect_grain(profile: TableProfile) -> tuple[str, list[str]]:
    """
    Infer the grain from PK-like column names.
    Returns (description, grain_columns).
    """
    # We don't have PK info here – use column name heuristics
    key_cols = [
        c.column_name
        for c in profile.columns
        if _KEY_SUFFIXES.match(c.column_name) and c.null_pct == 0
    ]
    if key_cols:
        return f"one row per ({', '.join(key_cols)})", key_cols
    return "grain unknown – no obvious key columns", []


def _find_date_cols(profile: TableProfile) -> list[str]:
    return [
        c.column_name
        for c in profile.columns
        if "DATE" in c.data_type or "TIMESTAMP" in c.data_type
    ]


def _find_numeric_measures(profile: TableProfile) -> list[str]:
    key_set = {c.column_name.lower() for c in profile.columns if _KEY_SUFFIXES.match(c.column_name)}
    return [
        c.column_name
        for c in profile.columns
        if c.data_type in ("NUMBER", "FLOAT", "BINARY_FLOAT")
        and c.column_name.lower() not in key_set
        and c.null_pct < 90  # skip near-empty columns
    ]


# ─── Public Interface ─────────────────────────────────────────────────────────

def detect_patterns(profiles: list[TableProfile]) -> list[ProfileWithPatterns]:
    """
    Run pattern detection over all table profiles.
    Returns ProfileWithPatterns for each table.
    """
    logger.info(f"Detecting patterns for {len(profiles)} tables…")

    # Build a name → profile map for cross-table join inference
    name_map = {p.table_name.upper(): p for p in profiles}
    all_col_names: dict[str, str] = {}  # col_name_upper → table_name
    for p in profiles:
        for c in p.columns:
            all_col_names[c.column_name.upper()] = p.table_name

    results: list[ProfileWithPatterns] = []

    for profile in profiles:
        col_names = [c.column_name.lower() for c in profile.columns]

        # SCD detection
        eff_col, exp_col, curr_col = _find_scd_signals(profile)
        is_scd = bool(eff_col and (exp_col or curr_col))

        # Event timestamp detection
        has_event_ts = any(
            _EVENT_TS_PATTERNS.search(c.column_name) for c in profile.columns
        )

        table_type = _classify_table_type(profile, is_scd, has_event_ts)
        grain_desc, grain_cols = _detect_grain(profile)
        status_cols = _find_status_columns(profile)
        date_cols = _find_date_cols(profile)
        measure_cols = _find_numeric_measures(profile)

        # Join candidates: look for columns whose name matches another table's
        # typical PK pattern (e.g. CUSTOMER_ID → CUSTOMER table)
        join_candidates: list[dict[str, Any]] = []
        for c in profile.columns:
            upper = c.column_name.upper()
            m = _KEY_SUFFIXES.match(upper)
            if m:
                base = m.group(1).rstrip("_")
                if base and base in name_map and base != profile.table_name.upper():
                    join_candidates.append({
                        "table": name_map[base].table_name,
                        "on_column": c.column_name,
                        "confidence": "high",
                    })

        pattern = PatternResult(
            grain_description=grain_desc,
            grain_columns=grain_cols,
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

        results.append(ProfileWithPatterns(profile=profile, patterns=pattern))
        logger.debug(
            f"{profile.full_name}: type={table_type}, scd={is_scd}, "
            f"flags={[s['column'] for s in status_cols]}"
        )

    logger.success(f"Pattern detection complete: {len(results)} tables")
    return results
