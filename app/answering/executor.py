"""
executor.py – Self-healing SQL execution loop (Phase 3 / Step 5).

Executes the SQL from an AnsweringState and automatically repairs it on
failure using a targeted LLM call.  All execution goes through db.run_query()
(Phase 1) which enforces the SQL guard, row caps, and timeouts.

Failure detection (any one triggers repair)
─────────────────────────────────────────────
1. db.run_query() raises ValueError (guard failure) or RuntimeError (ORA-*).
2. Result is structurally wrong:
   • Empty result set (0 rows) for a non-aggregate query.
   • Fan-out detected: row_count > expected_max (heuristic: > 10× the table's
     known row count suggests a missing join condition).

Repair loop
────────────
1. Format a targeted repair prompt including:
   • The error message or structural-failure description.
   • The failed SQL.
   • Valid column names from the retrieved semantic context.
2. Call call_llm_structured → SqlOutput for the repaired SQL.
3. Re-validate with guard and re-execute.
4. Hard limit: MAX_REPAIR_ATTEMPTS = 3.
5. After all attempts fail → set state.abstained = True, do NOT raise.

Public API
──────────
    execute_with_repair(state: AnsweringState) -> AnsweringState
    execute_with_vote(state, runs) -> AnsweringState   (eval harness)
"""

from __future__ import annotations

import json
import time
from collections import Counter
from typing import Any

from loguru import logger
from pydantic import BaseModel, Field

from app.answering.guard import clean_sql, validate_select_only
from app.answering.planner import AnsweringState, SqlOutput
from app.config import settings
from app.db import run_query
from app.llm import call_llm_structured

# Hard limit on repair attempts before abstaining.
MAX_REPAIR_ATTEMPTS: int = 3

# Row-count multiplier that suggests a fan-out (missing join predicate).
_FANOUT_MULTIPLIER: int = 10


# ─── Structural Failure Detection ────────────────────────────────────────────

def _detect_structural_failure(
    result: dict[str, Any],
    expected_max_rows: int | None,
) -> str | None:
    """
    Return a description of a structural failure, or None if the result looks OK.

    Checks:
    • Row count == 0 with no aggregation columns (suggests a bad filter).
    • Row count is far larger than the largest known table row count
      (suggests a Cartesian / fan-out join).
    """
    rows = result.get("rows", [])
    row_count = result.get("row_count", 0)

    # Empty result – only flag if this is likely a filter bug (not an aggregate).
    # Heuristics for "this is an aggregate query that intentionally returned 0":
    # 1. Single column with an aggregate-sounding name.
    # 2. Single row returned (most aggregates collapse to one row; a real
    #    0-row miss on a filter would return nothing, not one empty row).
    # 3. Query comment starts with an aggregate keyword.
    cols = result.get("columns", [])
    _AGGREGATE_COL_NAMES = {
        "cnt", "count", "total", "n", "num", "row_count",
        "sum", "avg", "average", "min", "max", "median",
    }
    is_aggregate = (
        # single-column with known aggregate name
        (len(cols) == 1 and cols[0].lower().split("_")[0] in _AGGREGATE_COL_NAMES)
        # or single-column with any numeric result (likely COUNT/SUM)
        or (len(cols) == 1 and len(rows) <= 1)
        # or multi-column but row-count is exactly 1 (GROUP BY with SUM/COUNT columns)
        or (len(cols) > 1 and row_count == 1)
    )
    if row_count == 0 and not is_aggregate:
        return (
            "The query returned 0 rows. This likely means a WHERE filter is "
            "too restrictive or uses incorrect column values."
        )

    # Fan-out detection
    if expected_max_rows and row_count > expected_max_rows * _FANOUT_MULTIPLIER:
        return (
            f"The query returned {row_count:,} rows, which is "
            f"{row_count / max(expected_max_rows, 1):.0f}× the expected maximum "
            f"({expected_max_rows:,}). This suggests a missing JOIN condition "
            "causing a Cartesian product (fan-out)."
        )

    return None


# ─── Repair Prompt ────────────────────────────────────────────────────────────

_REPAIR_PROMPT = """You are an Oracle 23ai SQL expert. Fix the following failed query.

ORIGINAL QUESTION: "{question}"

FAILED SQL:
{sql}

FAILURE REASON:
{error}

VALID TABLE COLUMNS (from semantic layer):
{schema_hint}

DATE CONTEXT:
{date_hint}

ORACLE SQL RULES:
- Use schema-qualified names: SCHEMA.TABLE_NAME
- Use DATE 'YYYY-MM-DD' for literals (never TO_DATE with implicit format)
- Half-open date ranges: col >= DATE '...' AND col < DATE '...'
- Use COUNT(DISTINCT col) for unique-entity counts
- Never use LIMIT – use FETCH FIRST N ROWS ONLY
- Fix only the root cause. Return the complete corrected SELECT statement.
- No markdown fences. No semicolons.
"""


def _build_schema_hint(state: AnsweringState) -> str:
    """Extract column names from the retrieved semantic layer tables."""
    lines: list[str] = []
    for table_name in state.table_names[:7]:
        # Load from the in-memory retrieval result (stored via plan.tables)
        lines.append(f"Table: {table_name}")
    # We don't re-load the full layer here; use the plan's table list as the hint.
    tables_in_plan = state.plan.tables
    return (
        "Tables in plan: " + ", ".join(tables_in_plan) + "\n"
        "Refer to the semantic layer for exact column names."
    )


def _repair_sql(
    state: AnsweringState,
    error: str,
) -> str | None:
    """
    Ask the LLM to produce a repaired SQL statement.

    Returns the cleaned, guard-validated SQL string, or None on failure.
    """
    prompt = _REPAIR_PROMPT.format(
        question=state.question,
        sql=state.sql,
        error=error,
        schema_hint=_build_schema_hint(state),
        date_hint=state.date_context.to_sql_hint(),
    )
    try:
        sql_out: SqlOutput = call_llm_structured(
            prompt, SqlOutput, bypass_cache=True
        )
        repaired = clean_sql(sql_out.sql)
        validate_select_only(repaired)
        return repaired
    except Exception as exc:  # noqa: BLE001
        logger.error("Repair LLM call failed: {}", exc)
        return None


# ─── Public Interface ─────────────────────────────────────────────────────────

def execute_with_repair(state: AnsweringState) -> AnsweringState:
    """
    Execute ``state.sql`` against Oracle, auto-repairing on failure.

    Mutates ``state`` in place (updates sql, result, attempts, repaired,
    abstained, abstain_reason) and returns it.

    Args:
        state: AnsweringState from plan_and_generate_sql().

    Returns:
        The same state object with result populated (or abstained=True).
    """
    # Expected maximum rows = largest table in plan (for fan-out detection).
    # We use sql_max_rows from config as a conservative proxy.
    expected_max = settings.sql_max_rows

    last_error: str = ""
    loop_start = time.perf_counter()  # track total elapsed even on abstain

    for attempt in range(1, MAX_REPAIR_ATTEMPTS + 1):
        logger.info("Executing SQL (attempt {}/{})", attempt, MAX_REPAIR_ATTEMPTS)

        try:
            result = run_query(
                state.sql,
                max_rows=settings.sql_max_rows,
                timeout=settings.sql_timeout_seconds,
            )
        except (ValueError, RuntimeError) as exc:
            last_error = str(exc)
            logger.warning("SQL attempt {} failed: {}", attempt, last_error[:300])
        else:
            # ── Structural failure check ──────────────────────────────────────
            structural_err = _detect_structural_failure(result, expected_max)
            if structural_err:
                last_error = structural_err
                logger.warning("Structural failure on attempt {}: {}", attempt, structural_err)
            else:
                # ── Success ───────────────────────────────────────────────────
                state.result = result
                state.attempts = attempt
                state.repaired = attempt > 1
                logger.info(
                    "SQL succeeded on attempt {} | rows={} | elapsed={:.0f}ms",
                    attempt, result.get("row_count", 0), result.get("elapsed_ms", 0),
                )
                return state

        # ── Repair if not on last attempt ─────────────────────────────────────
        if attempt < MAX_REPAIR_ATTEMPTS:
            repaired_sql = _repair_sql(state, last_error)
            if repaired_sql:
                state.sql = repaired_sql
                logger.info("SQL repaired for attempt {}.", attempt + 1)
            else:
                logger.warning("Repair failed; keeping previous SQL for next attempt.")

    # ── Abstain ───────────────────────────────────────────────────────────────
    total_elapsed_ms = (time.perf_counter() - loop_start) * 1000
    state.abstained = True
    state.abstain_reason = (
        f"SQL execution failed after {MAX_REPAIR_ATTEMPTS} attempts. "
        f"Last error: {last_error}"
    )
    state.attempts = MAX_REPAIR_ATTEMPTS
    state.result = {
        "columns": [],
        "rows": [],
        "row_count": 0,
        "elapsed_ms": total_elapsed_ms,
        "sql": state.sql,
    }
    logger.error(
        "Abstaining after {} attempts ({:.0f}ms). Reason: {}",
        MAX_REPAIR_ATTEMPTS, total_elapsed_ms, last_error,
    )
    return state


def execute_with_vote(
    state: AnsweringState,
    *,
    runs: int = 3,
) -> AnsweringState:
    """
    Run the query ``runs`` times (each with repair) and return the majority result.

    Used by the evaluation harness for consistency checking.
    The returned state reflects the winning majority result.
    """
    import copy

    results: list[dict[str, Any]] = []
    for i in range(runs):
        run_state = copy.deepcopy(state)
        run_state = execute_with_repair(run_state)
        if not run_state.abstained:
            results.append(run_state.result)

    if not results:
        state.abstained = True
        state.abstain_reason = "All vote runs failed or abstained."
        return state

    if len(results) == 1:
        state.result = results[0]
        state.attempts = runs
        return state

    def _result_key(r: dict[str, Any]) -> str:
        return json.dumps(r.get("rows", []), sort_keys=True, default=str)

    counts: Counter[str] = Counter(_result_key(r) for r in results)
    winner_key = counts.most_common(1)[0][0]
    state.result = next(r for r in results if _result_key(r) == winner_key)
    state.result["vote_count"] = counts[winner_key]
    state.result["total_runs"] = runs
    state.attempts = runs
    return state
