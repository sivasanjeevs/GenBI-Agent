"""
composer.py – Final answer composition (Phase 3 / Step 6).

Takes the raw query result and the full AnsweringState and produces a
human-readable plain-English response explaining what was found and how.

Two structured LLM calls (both via call_llm_structured)
──────────────────────────────────────────────────────────
Call 1 → FriendlyAnswer   (answer text + explanation + chart suggestion)
Call 2 → (implicit) None  – chart is included in Call 1's response

Conversation history is stored in-memory (keyed by conversation_id) for
multi-turn follow-up support.  In production, replace _conversations with
a Redis or database-backed store.

Public API
──────────
    compose_answer(state, question_id, conversation_id, include_chart) -> dict
    get_conversation_history(conversation_id) -> list[dict]
"""

from __future__ import annotations

import json
import time
from typing import Any

from loguru import logger
from pydantic import BaseModel, Field

from app.answering.planner import AnsweringState
from app.llm import call_llm_structured


# ─── Pydantic Response Models ─────────────────────────────────────────────────

class ChartSuggestion(BaseModel):
    """Optional visualisation suggestion."""
    chart_type: str = Field(
        ...,
        description="One of: bar, line, pie, table, scatter, none",
    )
    x_column: str | None = Field(None, description="Column name for x-axis, or null")
    y_column: str | None = Field(None, description="Column name for y-axis, or null")
    title: str = Field("", description="Short chart title")
    reason: str = Field("", description="Why this chart type suits the data")


class FriendlyAnswer(BaseModel):
    """LLM-generated plain-English answer."""
    answer: str = Field(
        ...,
        description=(
            "2-4 sentences directly answering the question with actual numbers. "
            "Notes how date references were interpreted. "
            "Honest about 0 results or unexpected data."
        ),
    )
    explanation: str = Field(
        "",
        description="1-2 sentences describing the SQL logic / evidence used.",
    )
    chart: ChartSuggestion | None = Field(
        None,
        description="Best visualisation for these results, or null if not applicable.",
    )


# ─── In-Memory Conversation Store ────────────────────────────────────────────
# Replace with Redis / DB in production.

_conversations: dict[str, list[dict[str, Any]]] = {}


# ─── Prompt ───────────────────────────────────────────────────────────────────

_COMPOSE_PROMPT = """You are a data analyst presenting results to a business user. Be direct and concise.

ORIGINAL QUESTION: "{question}"

SQL THAT WAS EXECUTED:
{sql}

QUERY RESULTS ({row_count} rows returned):
{results_preview}

DATE INTERPRETATION: {date_interpretation}
QUERY PLAN SUMMARY: {plan_summary}
ABSTAINED: {abstained}
ABSTAIN REASON: {abstain_reason}

INSTRUCTIONS:
1. Write a SHORT, direct plain-English answer (2-4 sentences) with the actual numbers.
2. Explicitly state how any date references were resolved (e.g. "last month = September 2026").
3. If 0 rows were returned, say so honestly and suggest why.
4. If the agent abstained (couldn't execute the query), acknowledge that and apologise.
5. In the explanation field, briefly describe the SQL logic / tables used.
6. In the chart field, suggest the best visualisation type for this data.
   - Use "none" if results are a single number or not suitable for charting.
   - "bar" for ranked/grouped counts; "line" for time series; "pie" for <=6 categories.
"""


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _results_preview(result: dict[str, Any], max_rows: int = 20) -> str:
    rows = result.get("rows", [])[:max_rows]
    if not rows:
        return "(no rows returned)"
    return json.dumps(rows, indent=2, default=str)


def _store_turn(
    conversation_id: str | None,
    question_id: str,
    question: str,
    response: dict[str, Any],
) -> None:
    """Append a turn to the in-memory conversation store."""
    cid = conversation_id or question_id
    if cid not in _conversations:
        _conversations[cid] = []
    _conversations[cid].append(
        {
            "question_id": question_id,
            "question": question,
            "answer": response.get("answer"),
            "sql": response.get("sql"),
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
    )


# ─── Public Interface ─────────────────────────────────────────────────────────

def compose_answer(
    state: AnsweringState,
    question_id: str,
    conversation_id: str | None = None,
    include_chart: bool = True,
) -> dict[str, Any]:
    """
    Generate a human-readable answer from the AnsweringState.

    Args:
        state:           Complete AnsweringState (includes result, plan, sql).
        question_id:     UUID for this request.
        conversation_id: Optional conversation ID for multi-turn support.
        include_chart:   If True, ask the LLM to suggest a chart.

    Returns:
        dict matching the AskResponse Pydantic model in main.py.
    """
    result = state.result
    rows = result.get("rows", [])
    row_count = result.get("row_count", 0)
    sql = result.get("sql", state.sql)
    elapsed_ms = result.get("elapsed_ms", 0.0)
    date_interp = state.date_context.interpretation

    prompt = _COMPOSE_PROMPT.format(
        question=state.question,
        sql=sql,
        row_count=row_count,
        results_preview=_results_preview(result),
        date_interpretation=date_interp or "none",
        plan_summary=state.plan.reasoning or state.plan.counting_strategy or "N/A",
        abstained=state.abstained,
        abstain_reason=state.abstain_reason or "N/A",
    )

    try:
        friendly: FriendlyAnswer = call_llm_structured(prompt, FriendlyAnswer)
        answer_text = friendly.answer
        explanation = friendly.explanation
        chart = friendly.chart.model_dump() if (include_chart and friendly.chart) else None
    except Exception as exc:  # noqa: BLE001
        logger.warning("Compose LLM call failed: {} – using fallback.", exc)
        if state.abstained:
            answer_text = (
                f"I was unable to answer this question after {state.attempts} attempt(s). "
                f"Reason: {state.abstain_reason}"
            )
        else:
            answer_text = f"The query returned {row_count} row(s)."
        explanation = ""
        chart = None

    response: dict[str, Any] = {
        "question_id": question_id,
        "answer": answer_text.strip(),
        "sql": sql,
        "data": rows,
        "columns": result.get("columns", []),
        "row_count": row_count,
        "elapsed_ms": elapsed_ms,
        "date_interpretation": date_interp or None,
        "explanation": explanation,
        "chart": chart,
        "attempts": state.attempts,
        "repaired": state.repaired,
        "abstained": state.abstained,
    }

    _store_turn(conversation_id, question_id, state.question, response)
    logger.info(
        "Answer composed | question_id={} | rows={} | abstained={}",
        question_id, row_count, state.abstained,
    )
    return response


def get_conversation_history(conversation_id: str) -> list[dict[str, Any]]:
    """Return all turns for a conversation ID (for multi-turn follow-up)."""
    return _conversations.get(conversation_id, [])
