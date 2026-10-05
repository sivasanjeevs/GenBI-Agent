"""
retrieve.py – Semantic context retrieval (Phase 3 / Step 2).

Selects the 3-7 most relevant tables, columns, and verified business
concepts from the semantic layer for a given user question.

Two-stage retrieval pipeline
─────────────────────────────
Stage 1  BM25 ranking  (rank-bm25 library).
  Build a corpus of "documents", one per table, composed of:
    • table name / entity name / description
    • column names, display names, descriptions
    • value_map values (e.g. "Active", "Passive")
    • verified concept terms
  Run BM25 to score every table against the question tokens.
  Keep the top-15 candidates.

Stage 2  LLM scoring  (only if > top_k candidates remain).
  Send the top-15 summaries to the LLM via call_llm_structured.
  Ask it to return a ranked list of full_names → picks the final 3-7.

Output: a typed RetrievalResult Pydantic model.

Public API
──────────
    retrieve_relevant_semantics(question, top_k) -> RetrievalResult
"""

from __future__ import annotations

import re
from typing import Any

from loguru import logger
from pydantic import BaseModel, Field

from app.learning.store import load_semantic_layer
from app.llm import call_llm_structured


# ─── Pydantic Models ──────────────────────────────────────────────────────────

class RetrievalResult(BaseModel):
    """Typed output from the retrieval stage, consumed by planner.py."""
    tables: list[dict[str, Any]] = Field(
        ..., description="Full semantic layer dicts for selected tables"
    )
    table_names: list[str] = Field(
        ..., description="Ordered list of selected SCHEMA.TABLE names"
    )
    bm25_scores: dict[str, float] = Field(
        default_factory=dict,
        description="BM25 score per table (for transparency/debugging)",
    )


class _LLMRanking(BaseModel):
    """Structured LLM output for ranking step."""
    ranked_tables: list[str] = Field(
        ...,
        description=(
            "Ordered list of full table names (SCHEMA.TABLE) needed to "
            "answer the question. Most relevant first. Maximum 7."
        ),
    )
    reasoning: str = Field(
        "",
        description="One sentence explaining why these tables were selected.",
    )


# ─── BM25 Corpus Builder ──────────────────────────────────────────────────────

_STOP_WORDS = frozenset(
    {
        "a", "an", "the", "of", "in", "is", "are", "was", "were",
        "for", "to", "and", "or", "with", "that", "this", "it",
        "be", "by", "on", "at", "as", "from", "how", "many", "what",
        "which", "who", "do", "does", "show", "me", "give", "get",
        "count", "total", "number", "list",
    }
)


def _tokenize(text: str) -> list[str]:
    """Lower-case, remove punctuation, split on whitespace, drop stop-words."""
    tokens = re.sub(r"[^\w\s]", " ", text.lower()).split()
    return [t for t in tokens if len(t) > 2 and t not in _STOP_WORDS]


def _build_table_document(table: dict[str, Any]) -> list[str]:
    """
    Flatten a table's semantic layer entry into a list of tokens for BM25.
    Weights important fields by repetition.
    """
    sem: dict[str, Any] = table.get("semantics", {})
    tokens: list[str] = []

    # High-weight: name and entity (repeated × 3 for term frequency boost)
    table_name_tokens = _tokenize(table.get("table_name", "").replace("_", " "))
    entity_tokens = _tokenize(sem.get("business_entity", ""))
    tokens.extend(table_name_tokens * 3)
    tokens.extend(entity_tokens * 3)

    # Medium-weight: description, grain
    tokens.extend(_tokenize(sem.get("table_description", "")))
    tokens.extend(_tokenize(sem.get("grain", "")))

    # Column names, display names, descriptions, value maps
    for col_name, col_info in sem.get("columns", {}).items():
        tokens.extend(_tokenize(col_name.replace("_", " ")))
        tokens.extend(_tokenize(col_info.get("display_name", "")))
        tokens.extend(_tokenize(col_info.get("description", "")))
        for val in col_info.get("value_map", {}).values():
            tokens.extend(_tokenize(str(val)))

    # Verified concept terms (high relevance)
    for concept in table.get("verified_concepts", []):
        tokens.extend(_tokenize(concept.get("term", "")) * 2)
        tokens.extend(_tokenize(concept.get("rationale", "")))

    # Counting warnings, suggested joins
    for warning in sem.get("counting_warnings", []):
        tokens.extend(_tokenize(warning))

    return tokens


# ─── LLM Ranking Step ─────────────────────────────────────────────────────────

_RANKING_PROMPT_TEMPLATE = """You are an Oracle SQL expert helping select the right database tables.

USER QUESTION: "{question}"

CANDIDATE TABLES (from the semantic layer):
{table_summaries}

Select the tables actually needed to answer the question.
Order them from most to least relevant.
Include at most 7 tables. Do not hallucinate tables not listed above.
"""


def _llm_rank(
    question: str,
    candidates: list[dict[str, Any]],
) -> list[str]:
    """Use call_llm_structured to pick the final set of tables."""
    summaries = "\n".join(
        f"- {t['full_name']}: {t.get('semantics', {}).get('table_description', '')[:180]}"
        for t in candidates
    )
    prompt = _RANKING_PROMPT_TEMPLATE.format(
        question=question,
        table_summaries=summaries,
    )
    try:
        ranking: _LLMRanking = call_llm_structured(prompt, _LLMRanking)
        logger.debug("LLM ranking reasoning: {}", ranking.reasoning)
        return ranking.ranked_tables
    except Exception as exc:  # noqa: BLE001
        logger.warning("LLM ranking failed ({}); returning BM25 order.", exc)
        return [t["full_name"] for t in candidates]


# ─── Public Interface ─────────────────────────────────────────────────────────

def retrieve_relevant_semantics(
    question: str,
    *,
    top_k: int = 7,
) -> RetrievalResult:
    """
    Return the most relevant semantic layer tables for the question.

    Pipeline:
    1. Load semantic_layer.json.
    2. Build per-table BM25 documents and score against question tokens.
    3. If > top_k candidates, run LLM ranking to pick the final set.

    Args:
        question: Raw user question string.
        top_k:    Maximum number of tables to return (3-7 recommended).

    Returns:
        RetrievalResult with typed tables, names, and BM25 scores.

    Raises:
        ValueError: If the semantic layer has not been generated yet.
    """
    try:
        from rank_bm25 import BM25Okapi  # type: ignore[import-untyped]
    except ImportError as exc:
        raise ImportError(
            "rank-bm25 is required. Run: pip install rank-bm25"
        ) from exc

    layer = load_semantic_layer()
    if layer is None:
        raise ValueError("Semantic layer not found. Run /learn first.")

    all_tables: list[dict[str, Any]] = layer.get("tables", [])

    # ── Fast path: small layer ────────────────────────────────────────────────
    if len(all_tables) <= top_k:
        return RetrievalResult(
            tables=all_tables,
            table_names=[t["full_name"] for t in all_tables],
            bm25_scores={t["full_name"]: 1.0 for t in all_tables},
        )

    # ── Stage 1: BM25 ────────────────────────────────────────────────────────
    q_tokens = _tokenize(question)
    corpus: list[list[str]] = [_build_table_document(t) for t in all_tables]

    bm25 = BM25Okapi(corpus)
    raw_scores: list[float] = bm25.get_scores(q_tokens).tolist()

    scored: list[tuple[dict[str, Any], float]] = list(zip(all_tables, raw_scores))
    scored.sort(key=lambda x: x[1], reverse=True)

    bm25_scores = {t["full_name"]: round(s, 4) for t, s in scored}

    # Keep top-15 as candidates for the LLM stage (or top_k if no LLM needed)
    _BM25_CANDIDATES = 15
    candidates = [t for t, s in scored[:_BM25_CANDIDATES] if s > 0]
    if not candidates:
        # Nothing scored > 0: fall back to top tables by BM25 anyway
        candidates = [t for t, _ in scored[:_BM25_CANDIDATES]]

    # ── Stage 2: LLM ranking (only when BM25 returns more than top_k) ────────
    if len(candidates) > top_k:
        ranked_names = _llm_rank(question, candidates)
        name_map: dict[str, dict[str, Any]] = {t["full_name"]: t for t in candidates}
        selected: list[dict[str, Any]] = [
            name_map[n] for n in ranked_names if n in name_map
        ][:top_k]
        if not selected:
            selected = candidates[:top_k]
    else:
        selected = candidates[:top_k]

    logger.debug(
        "Retrieved {} tables for '{}': {}",
        len(selected),
        question[:60],
        [t["full_name"] for t in selected],
    )

    return RetrievalResult(
        tables=selected,
        table_names=[t["full_name"] for t in selected],
        bm25_scores={t["full_name"]: bm25_scores[t["full_name"]] for t in selected},
    )
