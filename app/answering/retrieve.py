"""
retrieve.py – Semantic retrieval: pick relevant tables for a question.

Uses keyword matching + LLM scoring to select the 3-7 most relevant
tables from the semantic layer for a given question.

Two stages:
  1. Fast keyword filter (entity names, column names, business terms)
  2. LLM ranking if more than 7 tables pass the keyword filter
"""

from __future__ import annotations

import re
from typing import Any

from loguru import logger

from app.learning.store import load_semantic_layer
from app.llm import call_llm, extract_json


# ─── Keyword Matching ─────────────────────────────────────────────────────────

def _build_keyword_index(tables: list[dict[str, Any]]) -> dict[str, list[str]]:
    """Map each table's full_name to a list of searchable terms."""
    index: dict[str, list[str]] = {}
    for t in tables:
        terms: list[str] = []
        sem = t.get("semantics", {})

        # Table-level terms
        terms.append(t["table_name"].lower().replace("_", " "))
        terms.append(sem.get("business_entity", "").lower())
        terms.extend(sem.get("table_description", "").lower().split())

        # Column-level terms
        for col_name, col_info in sem.get("columns", {}).items():
            terms.append(col_name.lower().replace("_", " "))
            terms.append(col_info.get("display_name", "").lower())
            terms.extend(col_info.get("description", "").lower().split())
            for v in col_info.get("value_map", {}).values():
                terms.append(str(v).lower())

        index[t["full_name"]] = [t for t in terms if t]
    return index


def _keyword_score(question_tokens: set[str], terms: list[str]) -> int:
    score = 0
    terms_set = set(" ".join(terms).split())
    for tok in question_tokens:
        if len(tok) > 2 and tok in terms_set:
            score += 1
    return score


# ─── LLM Ranking ─────────────────────────────────────────────────────────────

_RANKING_PROMPT = """You are a SQL expert helping pick the right database tables for a question.

Question: {question}

Available tables:
{table_summaries}

Return a JSON array of full table names (e.g. ["VID.SUBSCRIBERS", "VID.SHOPS"])
that are needed to answer the question. Include only the tables actually required.
Order them from most to least relevant. Maximum 7 tables.

JSON array only, no explanation:
"""


def _llm_rank(question: str, candidates: list[dict[str, Any]]) -> list[str]:
    summaries = "\n".join(
        f"- {t['full_name']}: {t.get('semantics', {}).get('table_description', '')[:150]}"
        for t in candidates
    )
    prompt = _RANKING_PROMPT.format(question=question, table_summaries=summaries)
    try:
        response = call_llm(prompt)
        ranked: list[str] = extract_json(response)
        return ranked
    except Exception as exc:
        logger.warning(f"LLM ranking failed: {exc}, returning all candidates")
        return [t["full_name"] for t in candidates]


# ─── Public Interface ─────────────────────────────────────────────────────────

def retrieve_relevant_semantics(question: str, *, top_k: int = 7) -> dict[str, Any]:
    """
    Return a subset of the semantic layer relevant to the question.

    Returns:
        {
            "tables": [<table_info>, ...],   # selected table semantics
            "table_names": ["SCHEMA.TABLE", ...],
        }
    """
    layer = load_semantic_layer()
    if layer is None:
        raise ValueError("Semantic layer not found. Run /learn first.")

    tables = layer["tables"]

    if len(tables) <= top_k:
        # Small enough – use all
        return {
            "tables": tables,
            "table_names": [t["full_name"] for t in tables],
        }

    # Stage 1: keyword filter
    q_tokens = set(re.sub(r"[^\w\s]", " ", question.lower()).split())
    keyword_index = _build_keyword_index(tables)

    scored = [
        (t, _keyword_score(q_tokens, keyword_index[t["full_name"]]))
        for t in tables
    ]
    scored.sort(key=lambda x: x[1], reverse=True)

    # Keep top 15 for LLM ranking
    candidates = [t for t, s in scored[:15] if s > 0]
    if not candidates:
        candidates = [t for t, _ in scored[:15]]

    # Stage 2: LLM ranking if still too many
    if len(candidates) > top_k:
        ranked_names = _llm_rank(question, candidates)
        name_to_table = {t["full_name"]: t for t in candidates}
        selected = [name_to_table[n] for n in ranked_names if n in name_to_table]
        selected = selected[:top_k]
    else:
        selected = candidates[:top_k]

    logger.debug(f"Retrieved {len(selected)} tables for question: {question[:60]}")
    return {
        "tables": selected,
        "table_names": [t["full_name"] for t in selected],
    }
