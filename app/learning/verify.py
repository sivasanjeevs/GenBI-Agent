"""
verify.py – Agentic SQL-verification loop (Phase 2 / Step 5).

The LLM is creative but not infallible.  This module wraps every
``BusinessConcept.filter_sql`` in a ``SELECT COUNT(*) FROM <table>
WHERE <filter_sql>`` and tests the result.

Failure conditions (any one → repair)

• Oracle raises an error (bad column name, syntax error, etc.).
• The count == 0              (concept selects nothing – vacuous filter).
• The count == table.row_count (concept selects everything – trivially true).

Repair loop

1. Format a targeted error message that names the problem and lists the
   valid column names for the table.
2. Call ``enrich.generate_concepts()`` with ``error_context`` set, which
   appends the error to the prompt and bypasses cache.
3. Replace the failed concept with the repaired version.
4. Re-verify the repaired concept (counts as attempt #2).
5. After ``MAX_REPAIR_ATTEMPTS`` (2) failures the concept is marked
   ``confidence: "low"`` and retained (not silently dropped) so operators
   can review it.

Public API

    verify_all(enrichments: list[TableEnrichment],
               pwp_map: dict[str, ProfileWithPatterns]) -> list[TableEnrichment]
"""

from __future__ import annotations

from typing import Any

from loguru import logger
from tqdm import tqdm

from app.db import run_query
from app.learning.enrich import TableEnrichment, generate_concepts
from app.learning.patterns import ProfileWithPatterns

# Maximum repair attempts per concept before marking it low-confidence.
MAX_REPAIR_ATTEMPTS: int = 2

class _ConceptVerificationError(Exception):
    """Raised internally when a concept fails verification."""

def _build_count_sql(schema: str, table: str, filter_sql: str) -> str:
    return f'SELECT COUNT(*) AS cnt FROM {schema}.{table} WHERE {filter_sql}'

def _verify_concept_sql(
    schema: str,
    table_name: str,
    filter_sql: str,
    table_row_count: int,
    valid_columns: list[str],
) -> dict[str, Any]:
    """
    Execute the wrapped count query and decide pass / fail.

    Returns a dict:
        {
            "sql":        str,
            "count":      int | None,
            "passed":     bool,
            "confidence": "high" | "low",
            "error":      str | None,
            "repair_hint": str | None,  # set on failure, fed back to LLM
        }
    """
    sql = _build_count_sql(schema, table_name, filter_sql)
    col_list = ", ".join(valid_columns[:30])  # truncate for hint readability

    try:
        result = run_query(sql, max_rows=1, timeout=30)
        rows = result.get("rows", [])
        cnt = int(rows[0]["cnt"]) if rows else 0
    except (ValueError, RuntimeError) as exc:
        # SQL guard or DB error
        hint = (
            f"Execution failed with: {exc}\n"
            f"Valid column names for {schema}.{table_name} are: {col_list}.\n"
            "Rewrite filter_sql using ONLY those exact column names."
        )
        return {
            "sql": sql,
            "count": None,
            "passed": False,
            "confidence": "low",
            "error": str(exc),
            "repair_hint": hint,
        }

    if cnt == 0:
        hint = (
            f"The filter returned 0 rows out of {table_row_count:,} total. "
            "The filter is too restrictive or uses wrong values. "
            f"Check the 'top_values' in the column statistics. "
            f"Valid column names: {col_list}."
        )
        return {
            "sql": sql,
            "count": 0,
            "passed": False,
            "confidence": "low",
            "error": "filter returned 0 rows",
            "repair_hint": hint,
        }

    if table_row_count > 0 and cnt == table_row_count:
        hint = (
            f"The filter returned ALL {table_row_count:,} rows (trivially true). "
            "The filter does not actually filter anything useful. "
            "Add a more specific condition. "
            f"Valid column names: {col_list}."
        )
        return {
            "sql": sql,
            "count": cnt,
            "passed": False,
            "confidence": "low",
            "error": "filter returned 100% of rows (vacuous)",
            "repair_hint": hint,
        }

    return {
        "sql": sql,
        "count": cnt,
        "passed": True,
        "confidence": "high",
        "error": None,
        "repair_hint": None,
    }

def _verify_and_repair_concept(
    concept_term: str,
    filter_sql: str,
    rationale: str,
    schema: str,
    table_name: str,
    table_row_count: int,
    valid_columns: list[str],
    pwp: ProfileWithPatterns,
) -> dict[str, Any]:
    """
    Attempt to verify ``filter_sql`` for a single concept.
    If it fails, call enrich.generate_concepts() up to MAX_REPAIR_ATTEMPTS times.

    Returns a fully-populated concept verification dict.
    """
    current_filter = filter_sql
    current_rationale = rationale
    last_result: dict[str, Any] = {}

    for attempt in range(1, MAX_REPAIR_ATTEMPTS + 2):  # attempts: 1, 2, 3
        result = _verify_concept_sql(
            schema=schema,
            table_name=table_name,
            filter_sql=current_filter,
            table_row_count=table_row_count,
            valid_columns=valid_columns,
        )

        if result["passed"]:
            return {
                "term": concept_term,
                "filter_sql": current_filter,
                "rationale": current_rationale,
                "confidence": "high",
                "verified": True,
                "count": result["count"],
                "verification_sql": result["sql"],
                "repair_attempts": attempt - 1,
            }

        last_result = result
        logger.warning(
            "Concept '{}' failed (attempt {}/{}): {}",
            concept_term, attempt, MAX_REPAIR_ATTEMPTS + 1, result["error"],
        )

        if attempt > MAX_REPAIR_ATTEMPTS:
            break

        error_context = (
            f"Concept: '{concept_term}'\n"
            f"filter_sql: {current_filter!r}\n"
            f"Problem: {result['repair_hint']}"
        )
        try:
            repaired_semantics = generate_concepts(
                pwp,
                bypass_cache=True,
                error_context=error_context,
            )
            # Find the same concept by term in the repaired output
            repaired_concept = next(
                (c for c in repaired_semantics.concepts if c.term == concept_term),
                None,
            )
            if repaired_concept is None:
                # LLM dropped the concept or renamed it – take first new concept
                repaired_concept = next(
                    iter(repaired_semantics.concepts), None
                )

            if repaired_concept:
                current_filter = repaired_concept.filter_sql
                current_rationale = repaired_concept.rationale
            else:
                logger.warning(
                    "Repair attempt {} for '{}' returned no concepts.",
                    attempt, concept_term,
                )
                break

        except Exception as exc:  # noqa: BLE001
            logger.error("Repair LLM call failed for '{}': {}", concept_term, exc)
            break

    return {
        "term": concept_term,
        "filter_sql": current_filter,
        "rationale": current_rationale,
        "confidence": "low",
        "verified": False,
        "count": last_result.get("count"),
        "verification_sql": last_result.get("sql", ""),
        "error": last_result.get("error", "unknown"),
        "repair_attempts": MAX_REPAIR_ATTEMPTS,
    }

def verify_all(
    enrichments: list[TableEnrichment],
    pwp_map: dict[str, ProfileWithPatterns],
) -> list[TableEnrichment]:
    """
    Verify every BusinessConcept's ``filter_sql`` and apply repair loops.

    Args:
        enrichments: Output of ``enrich_all()``.
        pwp_map:     Dict mapping ``full_name.upper()`` → ProfileWithPatterns,
                     needed to call generate_concepts() during repair.

    Returns:
        The same list of TableEnrichment objects, each with
        ``verified_concepts`` populated.
    """
    logger.info("Verifying concepts for {} tables…", len(enrichments))

    for te in tqdm(enrichments, desc="Verifying concepts"):
        schema = te.schema_name
        table_name = te.table_name
        row_count = te.row_count
        valid_cols = [col["name"] for col in te.raw_columns]

        pwp = pwp_map.get(te.full_name.upper())
        if pwp is None:
            logger.warning(
                "No ProfileWithPatterns found for {}; skipping verification.",
                te.full_name,
            )
            te.verified_concepts = []
            continue

        concepts = te.semantics.concepts
        if not concepts:
            logger.debug("{}: no concepts to verify", te.full_name)
            te.verified_concepts = []
            continue

        verified: list[dict[str, Any]] = []
        for concept in concepts:
            vc = _verify_and_repair_concept(
                concept_term=concept.term,
                filter_sql=concept.filter_sql,
                rationale=concept.rationale,
                schema=schema,
                table_name=table_name,
                table_row_count=row_count,
                valid_columns=valid_cols,
                pwp=pwp,
            )
            verified.append(vc)
            status = "✓" if vc["verified"] else "✗"
            logger.debug(
                "{} Concept '{}': {} (repairs={})",
                status, concept.term, vc.get("error") or f"count={vc['count']}", vc["repair_attempts"],
            )

        te.verified_concepts = verified
        high = sum(1 for v in verified if v["confidence"] == "high")
        logger.info(
            "{}: {}/{} concepts verified at high confidence",
            te.full_name, high, len(verified),
        )

    logger.success("Concept verification complete")
    return enrichments
