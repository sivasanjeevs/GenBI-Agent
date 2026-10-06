"""
compare.py – Robust data comparator for evaluation (Phase 4 / Step 1).

Crucial Rule: Compare the answers (the data), not the query text.
Equivalent queries are fully accepted.

Normalisation rules:
1. Ignore column names and column order.
2. Ignore row order (but respect duplicate rows).
3. Round floats/decimals to 2 decimal places.
4. Convert dates/timestamps to canonical string formats.
5. All strings are stripped and uppercased.
"""

from __future__ import annotations

import math
from collections import Counter
from datetime import date, datetime
from decimal import Decimal
from typing import Any

def _norm_value(v: Any) -> str:
    """
    Normalise a single cell value.
    - Floats/Decimals: rounded to 2 decimal places.
    - Dates: canonical string YYYY-MM-DD (or full ISO).
    - Strings: stripped and uppercased.
    - None: "NULL"
    """
    if v is None:
        return "NULL"

    # Numbers
    if isinstance(v, float):
        if math.isnan(v) or math.isinf(v):
            return str(v)
        return f"{v:.2f}"
    if isinstance(v, Decimal):
        return f"{float(v):.2f}"
    # Sometimes ints come back as floats from JSON
    if isinstance(v, int):
        return str(v)

    # Dates
    if isinstance(v, datetime):
        return v.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(v, date):
        return v.strftime("%Y-%m-%d")

    # Strings
    return str(v).strip().upper()

def _norm_row(row: dict[str, Any]) -> tuple[str, ...]:
    """
    Normalise a row dictionary into a sorted tuple of its values.
    Sorting the values ignores column names and column order.
    Using a tuple (rather than a set) preserves duplicate values in the same row.
    """
    return tuple(sorted(_norm_value(v) for v in row.values()))

def _norm_result(rows: list[dict[str, Any]]) -> Counter[tuple[str, ...]]:
    """
    Normalise a list of rows into a Counter of row-tuples.
    This ignores row order entirely but strictly enforces exact row multiplicities.
    """
    return Counter(_norm_row(r) for r in rows)

def compare_results(
    actual: list[dict[str, Any]],
    expected: list[dict[str, Any]] | Any,
) -> bool:
    """
    Compare two result sets exactly on data content.

    Args:
        actual: Rows returned by the agent's query.
        expected: Expected rows (from benchmark). Can also be a scalar.

    Returns:
        True if the data matches perfectly after normalisation.
    """

    if not isinstance(expected, list):
        if len(actual) == 1 and len(actual[0]) == 1:
            actual_val = list(actual[0].values())[0]
            # Try numeric tolerance first for scalars
            try:
                a = float(str(actual_val))
                e = float(str(expected))
                if e == 0:
                    return a == 0
                return abs(a - e) / abs(e) <= 0.01  # 1% tolerance
            except (ValueError, TypeError):
                # Fallback to string match
                return _norm_value(actual_val) == _norm_value(expected)
        return False

    if not actual and not expected:
        return True
    if not actual or not expected:
        return False

    norm_actual = _norm_result(actual)
    norm_expected = _norm_result(expected)

    return norm_actual == norm_expected

def test_norm_value_float_rounding():
    assert _norm_value(3.14159) == "3.14"
    assert _norm_value(Decimal("3.14159")) == "3.14"
    assert _norm_value(10.0) == "10.00"

def test_norm_value_dates():
    assert _norm_value(date(2026, 8, 28)) == "2026-08-28"
    assert _norm_value(datetime(2026, 8, 28, 14, 30, 0)) == "2026-08-28 14:30:00"

def test_norm_value_strings():
    assert _norm_value("  Active ") == "ACTIVE"
    assert _norm_value(None) == "NULL"

def test_row_column_order_ignored():
    row1 = {"col_a": "X", "col_b": "Y"}
    row2 = {"col_b": "Y", "col_a": "X"}
    row3 = {"foo": "Y", "bar": "X"}  # different column names
    assert _norm_row(row1) == ("X", "Y")
    assert _norm_row(row1) == _norm_row(row2)
    assert _norm_row(row1) == _norm_row(row3)

def test_row_duplicates_preserved():
    # A row with two identical values shouldn't collapse to one
    row = {"a": 1, "b": 1}
    assert _norm_row(row) == ("1", "1")

def test_result_row_order_ignored():
    actual = [
        {"id": 1, "status": "A"},
        {"id": 2, "status": "B"},
    ]
    expected = [
        {"uid": 2, "state": "B"},
        {"uid": 1, "state": "A"},
    ]
    assert compare_results(actual, expected) is True

def test_result_row_multiplicity_enforced():
    actual = [
        {"val": "X"},
        {"val": "X"},
    ]
    expected = [
        {"val": "X"},
    ]
    assert compare_results(actual, expected) is False

def test_compare_scalar():
    actual = [{"cnt": 42}]
    assert compare_results(actual, 42) is True
    assert compare_results(actual, 42.0) is True
    assert compare_results(actual, "42") is True
    assert compare_results(actual, 43) is False

def test_compare_scalar_tolerance():
    actual = [{"avg_val": 3.14159}]
    # Within 1% tolerance
    assert compare_results(actual, 3.14) is True
    assert compare_results(actual, 3.16) is True
    assert compare_results(actual, 4.00) is False
