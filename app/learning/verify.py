"""
verify.py – SQL verification of learned concepts.

For each table we generate a small set of "proof queries" that
verify our semantic layer claims against the actual data, e.g.:

  - "Active shops" → SELECT COUNT(*) WHERE status='A' and confirm > 0
  - "SCD current record" → SELECT COUNT(*) WHERE is_current=1 confirm > 0
  - "Flag value map" → SELECT DISTINCT status FROM ... confirm values match

Verification results are stored alongside the semantic layer so
reviewers can see which concepts are data-backed.
"""

from __future__ import annotations

from typing import Any

from loguru import logger
from tqdm import tqdm

from app.db import raw_execute


# ─── Proof Query Generators ───────────────────────────────────────────────────

def _verify_scd(table_info: dict[str, Any]) -> list[dict[str, Any]]:
    """Verify SCD current-record filter returns > 0 rows."""
    proofs = []
    schema = table_info["schema"]
    table = table_info["table_name"]
    curr_col = table_info.get("scd_current_flag_col")
    eff_col = table_info.get("scd_eff_col")
    exp_col = table_info.get("scd_exp_col")

    if curr_col:
        sql = f"SELECT COUNT(*) AS cnt FROM {schema}.{table} WHERE {curr_col} = 1"
        try:
            rows = raw_execute(sql)
            cnt = rows[0]["cnt"] if rows else 0
            proofs.append({
                "name": "scd_current_flag",
                "sql": sql,
                "result": cnt,
                "passed": cnt > 0,
                "note": f"Current-flag '{curr_col}' = 1 yields {cnt} rows",
            })
        except Exception as exc:
            # Try 'Y' variant
            sql2 = f"SELECT COUNT(*) AS cnt FROM {schema}.{table} WHERE {curr_col} = 'Y'"
            try:
                rows2 = raw_execute(sql2)
                cnt2 = rows2[0]["cnt"] if rows2 else 0
                proofs.append({
                    "name": "scd_current_flag_Y",
                    "sql": sql2,
                    "result": cnt2,
                    "passed": cnt2 > 0,
                    "note": f"Current-flag '{curr_col}' = 'Y' yields {cnt2} rows",
                })
            except Exception:
                proofs.append({
                    "name": "scd_current_flag",
                    "sql": sql,
                    "result": None,
                    "passed": False,
                    "note": str(exc),
                })

    if eff_col and exp_col:
        sql = f"SELECT COUNT(*) AS cnt FROM {schema}.{table} WHERE {eff_col} <= SYSDATE AND {exp_col} > SYSDATE"
        try:
            rows = raw_execute(sql)
            cnt = rows[0]["cnt"] if rows else 0
            proofs.append({
                "name": "scd_date_range_active",
                "sql": sql,
                "result": cnt,
                "passed": cnt > 0,
                "note": f"Date-range current filter yields {cnt} rows",
            })
        except Exception as exc:
            proofs.append({
                "name": "scd_date_range_active",
                "sql": sql,
                "result": None,
                "passed": False,
                "note": str(exc),
            })

    return proofs


def _verify_value_map(table_info: dict[str, Any]) -> list[dict[str, Any]]:
    """Verify that decoded status values are actually present in the data."""
    proofs = []
    schema = table_info["schema"]
    table = table_info["table_name"]
    semantics = table_info.get("semantics", {})
    col_semantics = semantics.get("columns", {})

    for col_name, col_info in col_semantics.items():
        value_map = col_info.get("value_map", {})
        if not value_map:
            continue

        sql = f"SELECT DISTINCT {col_name} AS val FROM {schema}.{table} WHERE {col_name} IS NOT NULL"
        try:
            rows = raw_execute(sql)
            actual_vals = {str(r["val"]) for r in rows}
            declared_vals = set(str(k) for k in value_map.keys())
            matched = declared_vals & actual_vals
            proofs.append({
                "name": f"value_map_{col_name}",
                "sql": sql,
                "result": list(actual_vals),
                "passed": len(matched) > 0,
                "note": (
                    f"Value map for '{col_name}': declared={sorted(declared_vals)}, "
                    f"actual={sorted(actual_vals)}, matched={sorted(matched)}"
                ),
            })
        except Exception as exc:
            proofs.append({
                "name": f"value_map_{col_name}",
                "sql": sql,
                "result": None,
                "passed": False,
                "note": str(exc),
            })

    return proofs


def _verify_row_count(table_info: dict[str, Any]) -> dict[str, Any]:
    schema = table_info["schema"]
    table = table_info["table_name"]
    sql = f"SELECT COUNT(*) AS cnt FROM {schema}.{table}"
    try:
        rows = raw_execute(sql)
        cnt = rows[0]["cnt"] if rows else 0
        return {"name": "row_count", "sql": sql, "result": cnt, "passed": True, "note": ""}
    except Exception as exc:
        return {"name": "row_count", "sql": sql, "result": None, "passed": False, "note": str(exc)}


# ─── Public Interface ─────────────────────────────────────────────────────────

def verify_concepts(enriched: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Run proof queries for each table and attach results to the enriched dict.
    Returns the same list with a 'verification' key added to each entry.
    """
    logger.info(f"Verifying concepts for {len(enriched)} tables…")

    for table_info in tqdm(enriched, desc="Verifying"):
        proofs: list[dict[str, Any]] = []

        proofs.append(_verify_row_count(table_info))

        if table_info.get("is_scd"):
            proofs.extend(_verify_scd(table_info))

        proofs.extend(_verify_value_map(table_info))

        passed = sum(1 for p in proofs if p["passed"])
        table_info["verification"] = {
            "proofs": proofs,
            "passed": passed,
            "total": len(proofs),
            "score": round(passed / len(proofs), 2) if proofs else 1.0,
        }
        logger.debug(
            f"{table_info['full_name']}: verification {passed}/{len(proofs)}"
        )

    logger.success("Concept verification complete")
    return enriched
