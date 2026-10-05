"""
planner.py – Question → Plan → SQL generation.

Takes the question, resolved date context, and retrieved semantic tables,
and produces an execution plan + Oracle SQL.

Two-step prompting:
  Step 1 (PLAN): LLM reasons about which tables/columns/filters to use
  Step 2 (SQL):  LLM writes the actual Oracle SQL using the plan

The plan is returned alongside the SQL so we can show reasoning.
"""

from __future__ import annotations

import json
from typing import Any

from loguru import logger

from app.answering.guard import clean_sql
from app.llm import call_llm, extract_json


# ─── Prompt Templates ─────────────────────────────────────────────────────────

_PLAN_PROMPT = """You are a senior Oracle SQL expert with deep knowledge of telecom databases.

The user asked: "{question}"

Date context resolved: {date_context}

Relevant tables in the semantic layer:
{table_context}

{conversation_context}

TASK: Write a concise PLAN (not SQL yet) explaining:
1. Which tables you need and why
2. Which joins to use (and the join keys)
3. Which WHERE filters to apply (including how to filter for "active", "current", etc.)
4. How to handle SCD Type 2 tables (which column to use for current records)
5. What to COUNT / SUM / GROUP BY
6. Any potential double-counting risks and how to avoid them
7. Whether this question can be answered at all from the available data

If the question CANNOT be answered (missing data, ambiguous beyond resolution),
state "UNANSWERABLE: <reason>" and stop.

Respond with a JSON object:
{{
  "can_answer": true/false,
  "unanswerable_reason": "<reason if can_answer=false, else null>",
  "tables_needed": ["SCHEMA.TABLE", ...],
  "joins": ["<join description>"],
  "filters": ["<filter description>"],
  "aggregations": ["<agg description>"],
  "scd_handling": "<description or null>",
  "counting_strategy": "<description>",
  "plan_summary": "<2-3 sentence plain English plan>"
}}
"""

_SQL_PROMPT = """You are a senior Oracle SQL expert. Write an Oracle 23ai SELECT query.

User question: "{question}"

Execution plan:
{plan_json}

Semantic layer for relevant tables:
{table_context}

Date literals to use (do NOT compute dates yourself, use these exactly):
{date_literals}

Rules:
1. Use Oracle SQL syntax (DATE 'YYYY-MM-DD', TRUNC(), NVL(), etc.)
2. Always qualify column names with table alias
3. For SCD Type 2 tables, use the scd_handling from the plan to filter current records
4. Use COUNT(DISTINCT ...) when counting unique entities
5. Never invent columns or tables not in the semantic layer
6. Add a comment at the top: -- Answers: <question summary>
7. Return ONLY the SQL, wrapped in ```sql ... ```

SQL:
"""


# ─── Context Builders ─────────────────────────────────────────────────────────

def _build_table_context(semantics: dict[str, Any]) -> str:
    lines = []
    for t in semantics["tables"]:
        sem = t.get("semantics", {})
        lines.append(f"\n### {t['full_name']}")
        lines.append(f"Entity: {sem.get('business_entity', '?')}")
        lines.append(f"Description: {sem.get('table_description', '?')}")
        lines.append(f"Grain: {sem.get('grain', '?')}")
        if sem.get("scd_note"):
            lines.append(f"SCD Note: {sem['scd_note']}")
        if sem.get("counting_warnings"):
            lines.append(f"Counting warnings: {'; '.join(sem['counting_warnings'])}")

        # Columns
        lines.append("Columns:")
        for col_name, col_info in sem.get("columns", {}).items():
            vm = col_info.get("value_map", {})
            vm_str = f" [values: {vm}]" if vm else ""
            lines.append(
                f"  - {col_name} ({col_info.get('semantic_type', '?')}): "
                f"{col_info.get('description', '')}{vm_str}"
            )

        # Joins
        for join in sem.get("suggested_joins", []):
            lines.append(f"Join: {join.get('on')} → {join.get('description', '')}")

    return "\n".join(lines)


def _build_date_literals(date_context: dict[str, Any]) -> str:
    lines = [f"Reference date: {date_context.get('reference_date', 'unknown')}"]
    if date_context.get("as_of"):
        lines.append(f"Point-in-time (AS OF): {date_context['as_of']}")
    for p in date_context.get("periods", []):
        lines.append(
            f"Period '{p['label']}': {p['start_sql']} to {p['end_sql']}"
        )
    lines.append(f"Interpretation: {date_context.get('interpretation', '')}")
    return "\n".join(lines)


def _build_conversation_context(conversation_id: str | None) -> str:
    if not conversation_id:
        return ""
    from app.answering.composer import get_conversation_history
    history = get_conversation_history(conversation_id)
    if not history:
        return ""
    lines = ["Previous conversation turns:"]
    for turn in history[-3:]:  # last 3 turns
        lines.append(f"  Q: {turn['question']}")
        lines.append(f"  SQL used: {turn.get('sql', '')[:200]}")
    return "\n".join(lines)


# ─── Public Interface ─────────────────────────────────────────────────────────

def plan_and_generate_sql(
    question: str,
    semantics: dict[str, Any],
    date_context: dict[str, Any],
    conversation_id: str | None = None,
) -> dict[str, Any]:
    """
    Two-step: plan then SQL generation.

    Returns:
        {
            "question": str,
            "plan": dict,           # structured plan from LLM
            "sql": str,             # final Oracle SQL
            "table_names": list,
            "date_context": dict,
        }

    Raises:
        ValueError: if the question is determined unanswerable.
    """
    table_context = _build_table_context(semantics)
    date_literals = _build_date_literals(date_context)
    conversation_context = _build_conversation_context(conversation_id)

    # ── Step 1: Plan ──────────────────────────────────────────────────────────
    plan_prompt = _PLAN_PROMPT.format(
        question=question,
        date_context=json.dumps(date_context, indent=2),
        table_context=table_context,
        conversation_context=conversation_context,
    )

    logger.info(f"Planning query for: {question[:80]}…")
    plan_response = call_llm(plan_prompt)
    plan = extract_json(plan_response)

    if not plan.get("can_answer", True):
        raise ValueError(
            plan.get("unanswerable_reason", "Question cannot be answered from available data.")
        )

    # ── Step 2: SQL Generation ────────────────────────────────────────────────
    sql_prompt = _SQL_PROMPT.format(
        question=question,
        plan_json=json.dumps(plan, indent=2),
        table_context=table_context,
        date_literals=date_literals,
    )

    logger.info("Generating SQL…")
    sql_response = call_llm(sql_prompt, bypass_cache=True)  # always fresh SQL
    sql = clean_sql(sql_response)

    logger.debug(f"Generated SQL:\n{sql}")

    return {
        "question": question,
        "plan": plan,
        "sql": sql,
        "table_names": semantics["table_names"],
        "date_context": date_context,
    }
