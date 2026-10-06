"""
enrich.py – LLM-powered semantic enrichment (Phase 2 / Step 4).

Converts raw profile + pattern data into human-readable business concepts
using the structured LLM wrapper built in Phase 1.

Key design decisions

• ``BusinessConcept``   – Pydantic model for a single filterable concept
  (e.g. "Active Subscribers → status = 'A'").
• ``TableSemantics``    – Pydantic model for the complete LLM output per table.
• Uses ``call_llm_structured`` (not the legacy ``call_llm``) so Gemini
  returns guaranteed JSON conforming to the schema via ``response_schema``.
• Caching is keyed by (model, prompt, schema_name) – so schema changes
  invalidate the cache automatically.
• ``generate_concepts`` is the entry point called by verify.py's repair loop.
  It accepts an optional ``error_context`` string appended to the prompt for
  the validation-error retry path.

Public API

    enrich_table(pwp: ProfileWithPatterns, bypass_cache: bool) -> TableEnrichment
    enrich_all(tables: list[ProfileWithPatterns], bypass_cache: bool) -> list[TableEnrichment]
"""

from __future__ import annotations

import json
from typing import Any

from loguru import logger
from pydantic import BaseModel, Field
from tqdm import tqdm

from app.llm import call_llm_structured
from app.learning.patterns import ProfileWithPatterns

class BusinessConcept(BaseModel):
    """
    A single verifiable business filter concept.

    ``filter_sql`` is a WHERE-clause fragment (no SELECT/FROM) that will be
    wrapped as ``SELECT COUNT(*) FROM <table> WHERE <filter_sql>`` in verify.py.

    Examples:
        term       = "Active Subscribers"
        filter_sql = "status = 'A' AND is_current = 1"
        rationale  = "STATUS='A' means the SIM is active per the value map;
                      is_current=1 selects the latest SCD record."
    """
    term: str = Field(..., description="Short, human-readable concept name")
    filter_sql: str = Field(
        ...,
        description=(
            "A valid Oracle WHERE-clause fragment (no SELECT/FROM/WHERE keyword). "
            "Use actual column names from the table."
        ),
    )
    rationale: str = Field(
        ..., description="One-sentence explanation backed by the data values"
    )

class ColumnSemantics(BaseModel):
    """LLM-generated semantics for a single column."""
    description: str = ""
    display_name: str = ""
    value_map: dict[str, str] = Field(default_factory=dict)
    is_measure: bool = False
    is_dimension: bool = True
    semantic_type: str = "text"   # date|timestamp|status|id|measure|text|flag|category

class TableSemantics(BaseModel):
    """Complete LLM output for one table."""
    table_description: str
    business_entity: str
    grain: str
    scd_note: str | None = None
    concepts: list[BusinessConcept] = Field(default_factory=list)
    columns: dict[str, ColumnSemantics] = Field(default_factory=dict)
    counting_warnings: list[str] = Field(default_factory=list)
    suggested_joins: list[dict[str, str]] = Field(default_factory=list)

class TableEnrichment(BaseModel):
    """Everything about one table: profile, patterns, and LLM semantics."""
    schema_name: str
    table_name: str
    full_name: str
    row_count: int
    table_type: str
    is_scd: bool
    scd_eff_col: str | None
    scd_exp_col: str | None
    scd_current_flag_col: str | None
    grain_columns: list[str]
    grain_verified: bool
    date_columns: list[str]
    measure_columns: list[str]
    status_column_names: list[str]
    join_candidates: list[dict[str, Any]]
    raw_columns: list[dict[str, Any]]
    semantics: TableSemantics
    # Populated later by verify.py:
    verified_concepts: list[dict[str, Any]] = Field(default_factory=list)

def _build_prompt(
    pwp: ProfileWithPatterns,
    error_context: str | None = None,
) -> str:
    """
    Construct the LLM prompt for one table.

    ``error_context`` is appended when verify.py sends a concept back
    for repair after a SQL failure.
    """
    profile = pwp.profile
    patterns = pwp.patterns

    col_summaries = []
    for c in profile.columns[:40]:   # cap at 40 cols for prompt size
        entry: dict[str, Any] = {
            "name": c.column_name,
            "type": c.data_type,
            "null_pct": c.null_pct,
            "distinct_count": c.distinct_count,
        }
        if c.top_values:
            entry["top_values"] = c.top_values[:10]
        if c.min_value is not None:
            entry["min"] = str(c.min_value)
        if c.max_value is not None:
            entry["max"] = str(c.max_value)
        if c.sample_values:
            entry["sample"] = [str(v) for v in c.sample_values[:5]]
        col_summaries.append(entry)

    status_json = json.dumps(
        [s.model_dump() for s in patterns.status_columns], indent=2, default=str
    )
    join_json = json.dumps(
        [j.model_dump() for j in patterns.join_candidates], indent=2, default=str
    )

    prompt = f"""You are a senior data analyst building a semantic layer for a telecom Oracle database.

TABLE: {profile.full_name}
Row count: {profile.row_count:,}
Detected type: {patterns.table_type}
Is SCD Type 2: {patterns.is_scd}
SCD effective date col: {patterns.scd_eff_col}
SCD expiry date col: {patterns.scd_exp_col}
SCD current-flag col: {patterns.scd_current_flag_col}
Grain: {patterns.grain_description}
Grain verified by SQL: {patterns.grain_verified}

COLUMNS (with statistics):
{json.dumps(col_summaries, indent=2, default=str)}

STATUS / FLAG COLUMNS (low-cardinality, with value distributions):
{status_json}

DATE COLUMNS: {patterns.date_columns}
NUMERIC MEASURE COLUMNS: {patterns.numeric_measure_columns}
JOIN CANDIDATES: {join_json}

TASK

1. Write a 2-3 sentence business description of this table.
2. Identify the business entity (e.g. Subscriber, Shop, Tariff, Campaign).
3. Confirm or refine the grain statement.
4. For each status/flag column, decode the value codes (e.g. STATUS='A' → "Active").
5. Generate 2-5 BUSINESS CONCEPTS – each concept must have:
   • term       : short label (e.g. "Active Subscribers")
   • filter_sql : a valid Oracle WHERE-clause FRAGMENT using ONLY columns
                  listed above. Do NOT include SELECT / FROM / WHERE keyword.
                  Example: "status = 'A' AND is_current = 1"
   • rationale  : one sentence citing the data values that justify it.
6. Add counting warnings (e.g. "use COUNT(DISTINCT subscriber_id) not COUNT(*)").

Return ONLY a JSON object – no markdown fences, no explanation text."""

    if error_context:
        prompt += f"\n\nPREVIOUS ATTEMPT FAILED:\n{error_context}\nPlease correct your response."

    return prompt

def generate_concepts(
    pwp: ProfileWithPatterns,
    *,
    bypass_cache: bool = False,
    error_context: str | None = None,
) -> TableSemantics:
    """
    Call the LLM to produce structured semantics for one table.

    Called by both enrich_table() (initial) and verify.py (repair retries).

    Args:
        pwp:           Profile + patterns for the table.
        bypass_cache:  Skip disk cache lookup.
        error_context: Optional error text from a failed SQL verification,
                       appended to the prompt for self-repair.

    Returns:
        TableSemantics Pydantic model.
    """
    prompt = _build_prompt(pwp, error_context=error_context)
    return call_llm_structured(
        prompt,
        TableSemantics,
        bypass_cache=bypass_cache or (error_context is not None),
    )

def enrich_table(
    pwp: ProfileWithPatterns,
    *,
    bypass_cache: bool = False,
) -> TableEnrichment:
    """
    Enrich a single table with LLM-generated semantics.

    On LLM failure, a minimal fallback TableSemantics is used so the
    pipeline can continue.
    """
    profile = pwp.profile
    patterns = pwp.patterns

    try:
        semantics = generate_concepts(pwp, bypass_cache=bypass_cache)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "LLM enrichment failed for {}: {} – using fallback",
            profile.full_name, exc,
        )
        semantics = TableSemantics(
            table_description=f"Table {profile.full_name} (enrichment failed: {exc})",
            business_entity=profile.table_name.title(),
            grain=patterns.grain_description,
            concepts=[],
            columns={},
            counting_warnings=[],
        )

    return TableEnrichment(
        schema_name=profile.schema_name,
        table_name=profile.table_name,
        full_name=profile.full_name,
        row_count=profile.row_count,
        table_type=patterns.table_type,
        is_scd=patterns.is_scd,
        scd_eff_col=patterns.scd_eff_col,
        scd_exp_col=patterns.scd_exp_col,
        scd_current_flag_col=patterns.scd_current_flag_col,
        grain_columns=patterns.grain_columns,
        grain_verified=patterns.grain_verified,
        date_columns=patterns.date_columns,
        measure_columns=patterns.numeric_measure_columns,
        status_column_names=[s.column_name for s in patterns.status_columns],
        join_candidates=[j.model_dump() for j in patterns.join_candidates],
        raw_columns=[
            {
                "name": c.column_name,
                "type": c.data_type,
                "nullable": c.null_pct < 100,
                "null_pct": c.null_pct,
                "distinct_count": c.distinct_count,
                "top_values": c.top_values,
                "min": str(c.min_value) if c.min_value is not None else None,
                "max": str(c.max_value) if c.max_value is not None else None,
            }
            for c in profile.columns
        ],
        semantics=semantics,
    )

def enrich_all(
    tables: list[ProfileWithPatterns],
    *,
    bypass_cache: bool = False,
) -> list[TableEnrichment]:
    """
    Enrich every table in the list.

    Args:
        tables:       Output of ``detect_patterns()``.
        bypass_cache: If True, ignore the LLM disk cache.

    Returns:
        list[TableEnrichment] – one per table.
    """
    logger.info("LLM enrichment for {} tables…", len(tables))
    enriched: list[TableEnrichment] = []

    for pwp in tqdm(tables, desc="Enriching with LLM"):
        te = enrich_table(pwp, bypass_cache=bypass_cache)
        enriched.append(te)
        logger.debug(
            "Enriched {}: entity='{}' concepts={}",
            te.full_name,
            te.semantics.business_entity,
            len(te.semantics.concepts),
        )

    logger.success("LLM enrichment complete: {} tables", len(enriched))
    return enriched
