"""
composer.py – Answer composition + conversation history.

Takes the question, plan, SQL result, and date context and produces:
  1. A human-readable plain-English answer
  2. An explanation of how the date was interpreted
  3. Conversation history for follow-up support (Bonus CP5)
  4. Optional chart suggestion (Bonus CP6)
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any

from loguru import logger

from app.llm import call_llm


# ─── In-Memory Conversation Store ────────────────────────────────────────────
# For production, replace with Redis or a DB table.

_conversations: dict[str, list[dict[str, Any]]] = {}


# ─── Composition Prompt ───────────────────────────────────────────────────────

_COMPOSE_PROMPT = """You are a data analyst presenting results to a business user.

Question: "{question}"

SQL query that was run:
```sql
{sql}
```

Query results ({row_count} rows):
{results_preview}

Date interpretation: {date_interpretation}

Write a SHORT, direct plain-English answer that:
1. Directly answers the question with the actual numbers
2. Notes how any date references were interpreted (e.g. "last month = September 2026")
3. Mentions if results were capped (max {max_rows} rows shown)
4. If the data is unexpected or the result is 0, note that honestly

Keep the answer under 4 sentences. Use bullet points only if listing items.
"""

_CHART_PROMPT = """Given these query results, suggest the best chart type and configuration.

Question: "{question}"
Columns: {columns}
Row count: {row_count}
First few rows: {preview}

Respond with JSON:
{{
  "chart_type": "bar|line|pie|table|scatter|none",
  "x_column": "<column name or null>",
  "y_column": "<column name or null>",
  "title": "<chart title>",
  "reason": "<why this chart type>"
}}
"""


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _results_preview(result: dict[str, Any], max_preview: int = 20) -> str:
    rows = result.get("rows", [])[:max_preview]
    if not rows:
        return "(no rows returned)"
    return json.dumps(rows, indent=2, default=str)


def _suggest_chart(
    question: str,
    result: dict[str, Any],
) -> dict[str, Any] | None:
    try:
        prompt = _CHART_PROMPT.format(
            question=question,
            columns=result.get("columns", []),
            row_count=result.get("row_count", 0),
            preview=json.dumps(result.get("rows", [])[:5], default=str),
        )
        from app.llm import extract_json
        response = call_llm(prompt)
        return extract_json(response)
    except Exception as exc:
        logger.debug(f"Chart suggestion failed: {exc}")
        return None


# ─── Public Interface ─────────────────────────────────────────────────────────

def compose_answer(
    question: str,
    plan: dict[str, Any],
    result: dict[str, Any],
    date_context: dict[str, Any],
    question_id: str,
    conversation_id: str | None = None,
    include_chart: bool = True,
) -> dict[str, Any]:
    """
    Compose the final answer dict for the API response.
    """
    from app.config import settings

    rows = result.get("rows", [])
    row_count = result.get("row_count", 0)
    sql = result.get("final_sql", plan.get("sql", ""))
    elapsed_ms = result.get("elapsed_ms", 0.0)
    date_interp = date_context.get("interpretation", "")

    # Generate plain-English answer
    compose_prompt = _COMPOSE_PROMPT.format(
        question=question,
        sql=sql,
        row_count=row_count,
        results_preview=_results_preview(result),
        date_interpretation=date_interp or "no date filters applied",
        max_rows=settings.sql_max_rows,
    )

    try:
        answer_text = call_llm(compose_prompt)
    except Exception:
        # Fallback: just dump the results
        answer_text = f"Query returned {row_count} rows."

    # Optional chart suggestion
    chart = _suggest_chart(question, result) if include_chart else None

    # Build response dict
    response = {
        "question_id": question_id,
        "answer": answer_text.strip(),
        "sql": sql,
        "data": rows,
        "columns": result.get("columns", []),
        "row_count": row_count,
        "elapsed_ms": elapsed_ms,
        "date_interpretation": date_interp or None,
        "explanation": plan.get("plan", {}).get("plan_summary", ""),
        "chart": chart,
    }

    # Store in conversation history
    _store_turn(conversation_id, question_id, question, response)

    logger.info(f"Answer composed for question_id={question_id}")
    return response


def _store_turn(
    conversation_id: str | None,
    question_id: str,
    question: str,
    response: dict[str, Any],
) -> None:
    """Store a conversation turn for follow-up questions (CP5)."""
    cid = conversation_id or question_id  # use question_id as root for new conversations
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


def get_conversation_history(conversation_id: str) -> list[dict[str, Any]]:
    """Return all turns for a conversation."""
    return _conversations.get(conversation_id, [])
