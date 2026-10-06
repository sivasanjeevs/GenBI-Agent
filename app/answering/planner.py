"""
planner.py – Step-by-step reasoning and SQL generation (Phase 3 / Step 3).

Forces the LLM to think before generating code via two structured calls:

Call 1 → QueryPlan (Pydantic)
    answerable, tables, joins, filters, grain, scd_handling,
    counting_strategy, reasoning

Call 2 → SqlOutput (Pydantic)
    sql (the actual Oracle SELECT statement)

Both calls use call_llm_structured with response_schema so the output is
guaranteed to be valid JSON conforming to the declared schema.

The final output is an AnsweringState Pydantic model that carries the
question, plan, SQL, and date context through the rest of the pipeline.

Public API

    plan_and_generate_sql(
        question, retrieval, date_ctx, conversation_id
    ) -> AnsweringState
"""

from __future__ import annotations

import json
from typing import Any

from loguru import logger
from pydantic import BaseModel, Field

from app.answering.dates import DateContext
from app.answering.guard import clean_sql, validate_select_only
from app.answering.retrieve import RetrievalResult
from app.llm import call_llm_structured

class QueryPlan(BaseModel):
    """Step-by-step reasoning output from the planning LLM call."""
    answerable: bool = Field(..., description="Can this question be answered from the available data?")
    needs_clarification: bool = Field(False, description="Is the request genuinely ambiguous and needs user clarification?")
    clarifying_question: str | None = Field(None, description="If needs_clarification is true, the question to ask the user.")
    unanswerable_reason: str | None = Field(
        None,
        description="If answerable=false, explain why.",
    )
    tables: list[str] = Field(
        default_factory=list,
        description="SCHEMA.TABLE names required, in join order.",
    )
    joins: list[str] = Field(
        default_factory=list,
        description="Each join as 'A.col = B.col' with context.",
    )
    filters: list[str] = Field(
        default_factory=list,
        description="WHERE-clause conditions to apply (English, not SQL).",
    )
    grain: str = Field(
        "",
        description="What each row in the result represents.",
    )
    scd_handling: str | None = Field(
        None,
        description="How to filter SCD Type-2 tables for current records.",
    )
    counting_strategy: str = Field(
        "",
        description="How to COUNT correctly (DISTINCT, etc.).",
    )
    reasoning: str = Field(
        "",
        description="2-4 sentence plain-English reasoning trace.",
    )

class SqlOutput(BaseModel):
    """SQL generation output from the second LLM call."""
    sql: str = Field(
        ...,
        description=(
            "A single, complete Oracle 23ai SELECT statement. "
            "No markdown fences. No trailing semicolons."
        ),
    )
    comment: str = Field(
        "",
        description="One-line description of what the query computes.",
    )

class AnsweringState(BaseModel):
    """Shared state object threaded through the entire answering pipeline."""
    question: str
    plan: QueryPlan
    sql: str                           # cleaned, guard-validated SQL
    table_names: list[str]
    date_context: DateContext
    # Populated by executor.py:
    result: dict[str, Any] = Field(default_factory=dict)
    attempts: int = 0
    repaired: bool = False
    abstained: bool = False
    abstain_reason: str = ""

_PLAN_PROMPT = """You are a senior Oracle SQL expert with deep knowledge of telecom databases.
Think step-by-step before answering.

USER QUESTION: "{question}"

DATE CONTEXT (use these exact Oracle literals – do NOT compute dates yourself):
{date_sql_hint}

AVAILABLE TABLES IN THE SEMANTIC LAYER:
{table_context}

{conversation_context}

YOUR TASK (PLAN ONLY – no SQL yet):
1. Identify which tables are required and WHY.
2. Specify exact JOIN keys.
3. Determine WHERE filters (including SCD current-record filter if needed).
4. State what the grain of the result should be.
5. Note any double-counting risk and how to avoid it.
6. State whether the question can be answered.
7. If the request is genuinely ambiguous, set needs_clarification=true and provide a clarifying_question.

If the question CANNOT be answered with the available tables/columns, set
answerable=false and explain in unanswerable_reason.
"""

_SQL_PROMPT = """You are a senior Oracle 23ai SQL expert.
You have already produced a query plan. Now write the final SQL.

USER QUESTION: "{question}"

APPROVED PLAN:
{plan_json}

DATE LITERALS (copy-paste exactly – never compute dates yourself):
{date_sql_hint}

SEMANTIC LAYER CONTEXT:
{table_context}

ORACLE SQL RULES:
1. Always qualify every column with a table alias (e.g. s.status).
2. Use DATE 'YYYY-MM-DD' for date literals.
3. Use half-open date ranges: col >= DATE '...' AND col < DATE '...' (prevents double-counting).
4. For SCD Type-2 tables apply the scd_handling filter from the plan. If asked for "active" or "current" entities, always ensure you filter for active records (e.g. _edt >= SYSDATE) if an end-date column exists.
5. Use COUNT(DISTINCT <key>) when counting unique entities.
6. Never invent columns or tables not present in the semantic layer.
7. Use NVL(), TRUNC(), DECODE() – not IFNULL, FLOOR, IF().
8. Return a single SELECT statement. No trailing semicolon.
9. Start the query with a comment: -- Answers: <one-line summary>
10. When asked to "list" entities, include standard descriptive columns (like ID, Name) and add a logical ORDER BY clause.
11. When asked for the "highest", "lowest", or "top" category, DO NOT wrap the query to return only 1 row (no ROWNUM = 1). Return the full grouped result set ORDER BY the aggregate metric DESC (or ASC).
12. Pay close attention to verbs. "Assigned in June" means the Start Date (SDT) is in June. "Active in June" means the record overlaps June.

Write ONLY the SQL. No markdown. No explanation.
"""

def _build_table_context(retrieval: RetrievalResult) -> str:
    """Flatten retrieved semantic layer tables into a dense prompt string."""
    lines: list[str] = []
    for t in retrieval.tables:
        sem: dict[str, Any] = t.get("semantics", {})
        bm25 = retrieval.bm25_scores.get(t["full_name"], 0.0)
        lines.append(f"\n### {t['full_name']}  (BM25={bm25:.2f})")
        lines.append(f"Entity    : {sem.get('business_entity', '?')}")
        lines.append(f"Description: {sem.get('table_description', '?')}")
        lines.append(f"Grain     : {sem.get('grain', '?')}")
        if sem.get("scd_note"):
            lines.append(f"SCD Note  : {sem['scd_note']}")
        for w in sem.get("counting_warnings", []):
            lines.append(f"⚠ Counting: {w}")

        # Columns (name, type, description, value_map)
        cols_block: list[str] = []
        for col_name, col_info in sem.get("columns", {}).items():
            vm = col_info.get("value_map", {})
            vm_str = f"  values={json.dumps(vm)}" if vm else ""
            cols_block.append(
                f"  {col_name} ({col_info.get('semantic_type','?')}): "
                f"{col_info.get('description', '')}{vm_str}"
            )
        if cols_block:
            lines.append("Columns:\n" + "\n".join(cols_block))

        # Verified concepts
        high_concepts = [
            v for v in t.get("verified_concepts", []) if v.get("confidence") == "high"
        ]
        if high_concepts:
            lines.append("Verified business concepts:")
            for vc in high_concepts[:5]:
                lines.append(
                    f"  '{vc['term']}' → WHERE {vc['filter_sql']}  "
                    f"(count={vc.get('count', '?')})"
                )

        # Suggested joins
        for join in sem.get("suggested_joins", []):
            lines.append(f"Join: {join.get('on')} → {join.get('description', '')}")

    return "\n".join(lines)

def _build_conversation_context(conversation_id: str | None) -> str:
    if not conversation_id:
        return ""
    from app.answering.composer import get_conversation_history
    history = get_conversation_history(conversation_id)
    if not history:
        return ""
    lines = ["PREVIOUS CONVERSATION TURNS (for follow-up context):"]
    for turn in history[-3:]:
        lines.append(f"  Q: {turn['question']}")
        lines.append(f"  SQL: {turn.get('sql', '')[:200]}")
    return "\n".join(lines)

def plan_and_generate_sql(
    question: str,
    retrieval: RetrievalResult,
    date_ctx: DateContext,
    conversation_id: str | None = None,
) -> AnsweringState:
    """
    Two-step structured LLM pipeline: plan then SQL.

    Step 1: call_llm_structured → QueryPlan (reasoning trace).
    Step 2: call_llm_structured → SqlOutput (Oracle SELECT).
    The SQL is then validated by the security guard before being returned.

    Args:
        question:        Raw user question.
        retrieval:       Output of retrieve_relevant_semantics().
        date_ctx:        Output of resolve_dates().
        conversation_id: Optional conversation ID for multi-turn context.

    Returns:
        AnsweringState – ready for executor.py.

    Raises:
        ValueError: If the plan determines the question is unanswerable.
    """
    table_context = _build_table_context(retrieval)
    date_sql_hint = date_ctx.to_sql_hint()
    conversation_context = _build_conversation_context(conversation_id)

    plan_prompt = _PLAN_PROMPT.format(
        question=question,
        date_sql_hint=date_sql_hint,
        table_context=table_context,
        conversation_context=conversation_context,
    )

    logger.info("Planning query for: {}…", question[:80])
    plan: QueryPlan = call_llm_structured(plan_prompt, QueryPlan)

    if plan.needs_clarification and plan.clarifying_question:
        from app.answering.composer import _store_turn
        import uuid
        _store_turn(
            conversation_id,
            str(uuid.uuid4()),
            question,
            {"answer": plan.clarifying_question, "sql": ""}
        )
        raise ValueError(plan.clarifying_question)

    if not plan.answerable:
        from app.answering.composer import _store_turn
        import uuid
        msg = plan.unanswerable_reason or "Question cannot be answered from available data."
        _store_turn(
            conversation_id,
            str(uuid.uuid4()),
            question,
            {"answer": msg, "sql": ""}
        )
        raise ValueError(msg)

    logger.debug("Plan: tables={} filters={}", plan.tables, plan.filters)

    sql_prompt = _SQL_PROMPT.format(
        question=question,
        plan_json=plan.model_dump_json(indent=2),
        date_sql_hint=date_sql_hint,
        table_context=table_context,
    )

    logger.info("Generating SQL…")
    sql_output: SqlOutput = call_llm_structured(
        sql_prompt, SqlOutput, bypass_cache=True
    )

    sql = clean_sql(sql_output.sql)
    validate_select_only(sql)   # raises ValueError on non-SELECT

    logger.debug("Generated SQL:\n{}", sql)

    return AnsweringState(
        question=question,
        plan=plan,
        sql=sql,
        table_names=retrieval.table_names,
        date_context=date_ctx,
    )
