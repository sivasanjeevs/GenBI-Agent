"""
executor.py – SQL execution with auto-repair loop and majority vote.

Flow:
  1. Run the SQL via db.safe_execute
  2. If it errors, ask the LLM to repair and retry (up to N times)
  3. For consistency, optionally run N times and take majority vote on result

The repair loop passes the Oracle error message back to the LLM with
the original question and plan context, so it can make targeted fixes.
"""

from __future__ import annotations

import time
from collections import Counter
from typing import Any

from loguru import logger

from app.answering.guard import clean_sql
from app.config import settings
from app.db import safe_execute
from app.llm import call_llm


# ─── Repair Prompt ────────────────────────────────────────────────────────────

_REPAIR_PROMPT = """You are an Oracle SQL expert. The following Oracle SQL query failed.

Original question: "{question}"

Failed SQL:
```sql
{sql}
```

Error message:
{error}

Fix the SQL so it runs correctly on Oracle 23ai. Common issues:
- Missing schema prefix (use SCHEMA.TABLE_NAME)
- Oracle date syntax (use DATE 'YYYY-MM-DD' not '2026-01-01')
- Column name typos (check the schema below)
- Oracle-specific functions (use NVL not IFNULL, ROWNUM not LIMIT)
- Subquery alias requirements

Available schema context:
{schema_context}

Return ONLY the corrected SQL wrapped in ```sql ... ```:
"""


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _schema_context_from_plan(plan_dict: dict[str, Any]) -> str:
    """Build a brief schema hint from the plan's table list."""
    tables = plan_dict.get("tables_needed", [])
    return f"Tables involved: {', '.join(tables)}"


def _results_equal(a: list[dict], b: list[dict]) -> bool:
    """Compare two result sets ignoring row/column order."""
    def normalise(rows: list[dict]) -> frozenset:
        return frozenset(
            frozenset((k, str(v)) for k, v in row.items())
            for row in rows
        )
    return normalise(a) == normalise(b)


# ─── Public Interface ─────────────────────────────────────────────────────────

def execute_with_repair(plan: dict[str, Any]) -> dict[str, Any]:
    """
    Execute the SQL from `plan`, with auto-repair on failure.

    Args:
        plan: dict from planner.plan_and_generate_sql

    Returns:
        Result dict from db.safe_execute plus:
          - "attempts": number of attempts made
          - "repaired": bool – was the SQL repaired?
          - "final_sql": the SQL that actually ran
    """
    sql = plan["sql"]
    question = plan["question"]
    plan_info = plan.get("plan", {})
    max_attempts = settings.sql_repair_attempts

    last_error: str | None = None

    for attempt in range(1, max_attempts + 1):
        try:
            logger.info(f"Executing SQL (attempt {attempt}/{max_attempts})")
            result = safe_execute(sql)
            result["attempts"] = attempt
            result["repaired"] = attempt > 1
            result["final_sql"] = sql
            return result

        except (ValueError, RuntimeError) as exc:
            last_error = str(exc)
            logger.warning(f"SQL attempt {attempt} failed: {last_error[:200]}")

            if attempt >= max_attempts:
                break

            # Ask LLM to repair
            schema_ctx = _schema_context_from_plan(plan_info)
            repair_prompt = _REPAIR_PROMPT.format(
                question=question,
                sql=sql,
                error=last_error,
                schema_context=schema_ctx,
            )
            try:
                repair_response = call_llm(repair_prompt, bypass_cache=True)
                sql = clean_sql(repair_response)
                logger.info(f"Repaired SQL (attempt {attempt + 1}):\n{sql[:300]}…")
            except Exception as repair_exc:
                logger.error(f"Repair LLM call failed: {repair_exc}")
                break

    # All attempts exhausted
    raise RuntimeError(
        f"SQL execution failed after {max_attempts} attempts. "
        f"Last error: {last_error}"
    )


def execute_with_vote(
    plan: dict[str, Any],
    runs: int = 3,
) -> dict[str, Any]:
    """
    Run the query `runs` times and return the majority result.
    Used by the eval harness for consistency checking.
    """
    results = []
    for i in range(runs):
        try:
            r = execute_with_repair(plan)
            results.append(r)
        except Exception as exc:
            logger.warning(f"Vote run {i+1} failed: {exc}")

    if not results:
        raise RuntimeError("All vote runs failed")

    if len(results) == 1:
        return results[0]

    # Pick the result that appears most frequently (by data content)
    # Represent each result as a frozen set of row tuples
    def key(r: dict[str, Any]) -> str:
        import json
        return json.dumps(r["rows"], sort_keys=True, default=str)

    counts = Counter(key(r) for r in results)
    winner_key = counts.most_common(1)[0][0]
    winning = next(r for r in results if key(r) == winner_key)
    winning["vote_count"] = counts[winner_key]
    winning["total_runs"] = len(results)
    return winning
