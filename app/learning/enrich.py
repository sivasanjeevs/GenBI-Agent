"""
enrich.py – LLM-powered semantic enrichment.

Takes the output of patterns.py and asks the LLM to produce rich
semantic descriptions for every table and column, including:

  - Human-readable business description
  - Decoded flag/status values (e.g. STATUS='A' → "Active subscriber")
  - Identified business entities (Customer, Subscription, Shop, etc.)
  - Grain confirmation
  - SCD handling instructions
  - Suggested display names
  - Warnings about common counting errors (e.g. "count distinct subscriber_id")
"""

from __future__ import annotations

import json
from typing import Any

from loguru import logger
from tqdm import tqdm

from app.llm import call_llm, extract_json
from app.learning.patterns import ProfileWithPatterns


# ─── Prompt Templates ─────────────────────────────────────────────────────────

_TABLE_PROMPT = """You are a senior data analyst helping build a semantic layer for a telecom database.

Here is the raw introspection data for table **{full_name}**:

Table type detected: {table_type}
Row count: {row_count}
Is SCD Type 2: {is_scd}
SCD effective date column: {scd_eff_col}
SCD expiry date column: {scd_exp_col}
SCD current-flag column: {scd_current_flag_col}
Grain description: {grain_description}
Grain columns: {grain_columns}

Columns:
{columns_json}

Status/flag columns with value distributions:
{status_json}

Date columns: {date_columns}
Numeric measure columns: {measure_columns}

Potential join candidates (inferred from column names):
{join_candidates}

---

Respond with a JSON object matching this schema (no other text):
{{
  "table_description": "<business description in 2-3 sentences>",
  "business_entity": "<e.g. Subscriber, Shop, Tariff, Campaign>",
  "grain": "<one row per X>",
  "scd_note": "<how to query current records, or null if not SCD>",
  "columns": {{
    "<column_name>": {{
      "description": "<business meaning>",
      "display_name": "<human friendly name>",
      "value_map": {{}},   // e.g. {{"A": "Active", "P": "Passive"}}; omit if not applicable
      "is_measure": true/false,
      "is_dimension": true/false,
      "semantic_type": "<date|timestamp|status|id|measure|text|flag|category>"
    }}
  }},
  "counting_warnings": ["<e.g. Use COUNT(DISTINCT subscriber_id) not COUNT(*) to count customers>"],
  "suggested_joins": [
    {{"table": "<other.table>", "on": "<col> = <other_col>", "description": "<why>"}}
  ]
}}
"""


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _format_columns_for_prompt(pwp: ProfileWithPatterns) -> str:
    items = []
    for c in pwp.profile.columns:
        item = {
            "name": c.column_name,
            "type": c.data_type,
            "null_pct": c.null_pct,
            "distinct_count": c.distinct_count,
            "top_values": c.top_values[:10],
            "min": str(c.min_value) if c.min_value is not None else None,
            "max": str(c.max_value) if c.max_value is not None else None,
            "sample": [str(v) for v in c.sample_values[:5]],
        }
        items.append(item)
    return json.dumps(items, indent=2, default=str)


# ─── Public Interface ─────────────────────────────────────────────────────────

def enrich_with_llm(
    tables: list[ProfileWithPatterns],
    *,
    bypass_cache: bool = False,
) -> list[dict[str, Any]]:
    """
    Enrich each table with LLM-generated semantic descriptions.

    Returns a list of dicts, each containing:
      - All raw profile/pattern data
      - A "semantics" key with the LLM enrichment
    """
    logger.info(f"LLM enrichment for {len(tables)} tables…")
    enriched: list[dict[str, Any]] = []

    for pwp in tqdm(tables, desc="Enriching with LLM"):
        profile = pwp.profile
        patterns = pwp.patterns

        col_json = _format_columns_for_prompt(pwp)

        prompt = _TABLE_PROMPT.format(
            full_name=profile.full_name,
            table_type=patterns.table_type,
            row_count=profile.row_count,
            is_scd=patterns.is_scd,
            scd_eff_col=patterns.scd_eff_col,
            scd_exp_col=patterns.scd_exp_col,
            scd_current_flag_col=patterns.scd_current_flag_col,
            grain_description=patterns.grain_description,
            grain_columns=patterns.grain_columns,
            columns_json=col_json,
            status_json=json.dumps(patterns.status_columns, indent=2, default=str),
            date_columns=patterns.date_columns,
            measure_columns=patterns.numeric_measure_columns,
            join_candidates=json.dumps(patterns.join_candidates, indent=2),
        )

        try:
            response = call_llm(prompt, bypass_cache=bypass_cache)
            semantics = extract_json(response)
        except Exception as exc:
            logger.warning(f"LLM enrichment failed for {profile.full_name}: {exc}")
            semantics = {
                "table_description": f"Table {profile.full_name} (enrichment failed)",
                "business_entity": profile.table_name,
                "grain": patterns.grain_description,
                "scd_note": None,
                "columns": {},
                "counting_warnings": [],
                "suggested_joins": [],
            }

        enriched.append(
            {
                "schema": profile.schema,
                "table_name": profile.table_name,
                "full_name": profile.full_name,
                "row_count": profile.row_count,
                "table_type": patterns.table_type,
                "is_scd": patterns.is_scd,
                "scd_eff_col": patterns.scd_eff_col,
                "scd_exp_col": patterns.scd_exp_col,
                "scd_current_flag_col": patterns.scd_current_flag_col,
                "grain_columns": patterns.grain_columns,
                "date_columns": patterns.date_columns,
                "measure_columns": patterns.numeric_measure_columns,
                "status_columns": [s["column"] for s in patterns.status_columns],
                "join_candidates": patterns.join_candidates,
                "raw_columns": [
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
                "semantics": semantics,
            }
        )
        logger.debug(f"Enriched {profile.full_name}: {semantics.get('business_entity', '?')}")

    logger.success(f"LLM enrichment complete: {len(enriched)} tables")
    return enriched
