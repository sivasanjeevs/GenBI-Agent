"""
compare.py – Result comparison for evaluation.

The hackathon spec says: "Compare the answers (the data), not the query text."
Column order, row order, and column names are ignored.

Comparison modes:
  1. Exact data match (after normalisation)
  2. Numeric tolerance match (for aggregated values)
  3. Subset match (expected ⊆ actual, for partial results)
"""

from __future__ import annotations

import math
from decimal import Decimal
from typing import Any


# ─── Normalisation ────────────────────────────────────────────────────────────

def _norm_value(v: Any) -> str:
    """Normalise a value for comparison."""
    if v is None:
        return "NULL"
    if isinstance(v, float):
        if math.isnan(v) or math.isinf(v):
            return str(v)
        # Round to 4 decimal places to avoid floating-point noise
        return str(round(v, 4))
    if isinstance(v, Decimal):
        return str(round(float(v), 4))
    return str(v).strip().upper()


def _norm_row(row: dict[str, Any]) -> frozenset[tuple[str, str]]:
    """Normalise a row dict to a frozenset of (value,) pairs (column-order-agnostic)."""
    return frozenset(_norm_value(v) for v in row.values())


def _norm_result(rows: list[dict[str, Any]]) -> frozenset[frozenset[tuple[str, str]]]:
    return frozenset(_norm_row(r) for r in rows)


# ─── Public Interface ─────────────────────────────────────────────────────────

def compare_results(
    actual: list[dict[str, Any]],
    expected: list[dict[str, Any]] | Any,
    *,
    allow_subset: bool = False,
    numeric_tolerance: float = 0.01,
) -> bool:
    """
    Compare two result sets.

    Args:
        actual: Rows returned by the agent's query.
        expected: Expected rows (from benchmark). Can also be a scalar.
        allow_subset: If True, pass if expected ⊆ actual.
        numeric_tolerance: Relative tolerance for numeric comparisons.

    Returns:
        True if results match within tolerance.
    """
    # Handle scalar expected (e.g. a single count)
    if not isinstance(expected, list):
        # Check if actual has a single numeric cell equal to expected
        if len(actual) == 1 and len(actual[0]) == 1:
            actual_val = list(actual[0].values())[0]
            try:
                a = float(str(actual_val))
                e = float(str(expected))
                if e == 0:
                    return a == 0
                return abs(a - e) / abs(e) <= numeric_tolerance
            except (ValueError, TypeError):
                return _norm_value(actual_val) == _norm_value(expected)
        return False

    if not actual and not expected:
        return True
    if not actual or not expected:
        return False

    norm_actual = _norm_result(actual)
    norm_expected = _norm_result(expected)

    if allow_subset:
        return norm_expected.issubset(norm_actual)

    return norm_actual == norm_expected


def diff_results(
    actual: list[dict[str, Any]],
    expected: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Return a diff showing rows in expected but not in actual, and vice versa.
    Useful for debugging failed eval questions.
    """
    norm_actual = _norm_result(actual)
    norm_expected = _norm_result(expected)

    missing = norm_expected - norm_actual    # in expected but not actual
    extra = norm_actual - norm_expected      # in actual but not expected

    return {
        "match": norm_actual == norm_expected,
        "actual_count": len(actual),
        "expected_count": len(expected),
        "missing_rows": len(missing),
        "extra_rows": len(extra),
    }
