"""
dates.py – Deterministic date resolution.

Converts natural-language temporal references into concrete Oracle
date literals BEFORE the SQL is generated. This prevents the LLM
from guessing what "last month" or "as of today" means.

Examples:
  "last month"         → {period: "2026-09", start: "2026-09-01", end: "2026-09-30"}
  "July and August"    → {periods: ["2026-07", "2026-08"], ...}
  "as of 28 Aug 2026"  → {as_of: "2026-08-28"}
  "current"            → {as_of: "<today>"}
  "Q3 2026"            → {start: "2026-07-01", end: "2026-09-30"}
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any

from dateutil.relativedelta import relativedelta
from loguru import logger


# ─── Reference Date ───────────────────────────────────────────────────────────

def _today(date_context: str | None = None) -> date:
    """Return today or parse explicit context like 'today is 2026-08-28'."""
    if date_context:
        m = re.search(r"(\d{4}-\d{2}-\d{2})", date_context)
        if m:
            return date.fromisoformat(m.group(1))
    return date.today()


# ─── Pattern Matchers ─────────────────────────────────────────────────────────

_MONTH_NAMES = {
    "jan": 1, "january": 1,
    "feb": 2, "february": 2,
    "mar": 3, "march": 3,
    "apr": 4, "april": 4,
    "may": 5,
    "jun": 6, "june": 6,
    "jul": 7, "july": 7,
    "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10,
    "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}

_QUARTER_MAP = {1: (1, 3), 2: (4, 6), 3: (7, 9), 4: (10, 12)}


def _month_range(year: int, month: int) -> tuple[date, date]:
    start = date(year, month, 1)
    end = start + relativedelta(months=1) - timedelta(days=1)
    return start, end


def _quarter_range(year: int, q: int) -> tuple[date, date]:
    start_month, end_month = _QUARTER_MAP[q]
    start = date(year, start_month, 1)
    end = date(year, end_month, 1) + relativedelta(months=1) - timedelta(days=1)
    return start, end


def _oracle_date(d: date) -> str:
    return f"DATE '{d.isoformat()}'"


# ─── Resolution Logic ─────────────────────────────────────────────────────────

def resolve_dates(question: str, *, date_context: str | None = None) -> dict[str, Any]:
    """
    Parse the question for temporal references and return a dict of resolved dates.

    Returns a context dict that is passed downstream to the SQL planner so it
    can substitute concrete dates. Keys present depend on what was detected:
      - periods: list of {label, start_sql, end_sql, start_date, end_date}
      - as_of: str  (Oracle DATE literal for point-in-time queries)
      - reference_date: str (today's date as ISO string)
      - interpretation: str (human description for the answer)
    """
    today = _today(date_context)
    q_lower = question.lower()
    result: dict[str, Any] = {
        "reference_date": today.isoformat(),
        "periods": [],
        "as_of": None,
        "interpretation": "",
    }
    interpretations: list[str] = []

    # ── "as of <date>" ────────────────────────────────────────────────────────
    as_of_match = re.search(
        r"as\s+of\s+(\d{1,2})\s+(\w+)\s+(\d{4})", q_lower
    )
    if as_of_match:
        day = int(as_of_match.group(1))
        mon_str = as_of_match.group(2)
        year = int(as_of_match.group(3))
        mon = _MONTH_NAMES.get(mon_str)
        if mon:
            as_of = date(year, mon, day)
            result["as_of"] = _oracle_date(as_of)
            interpretations.append(f"as of {as_of.isoformat()}")

    # ── Explicit ISO date ─────────────────────────────────────────────────────
    iso_dates = re.findall(r"\b(\d{4}-\d{2}-\d{2})\b", question)
    if iso_dates and not result["as_of"]:
        result["as_of"] = _oracle_date(date.fromisoformat(iso_dates[0]))
        interpretations.append(f"as of {iso_dates[0]}")

    # ── "last month" ──────────────────────────────────────────────────────────
    if "last month" in q_lower:
        ref = today - relativedelta(months=1)
        s, e = _month_range(ref.year, ref.month)
        result["periods"].append(_make_period(f"{ref.year}-{ref.month:02d}", s, e))
        interpretations.append(f"last month = {s.strftime('%B %Y')}")

    # ── "this month" ─────────────────────────────────────────────────────────
    if "this month" in q_lower:
        s, e = _month_range(today.year, today.month)
        result["periods"].append(_make_period(f"{today.year}-{today.month:02d}", s, e))
        interpretations.append(f"this month = {s.strftime('%B %Y')}")

    # ── "last year" / "this year" ─────────────────────────────────────────────
    if "last year" in q_lower:
        y = today.year - 1
        s, e = date(y, 1, 1), date(y, 12, 31)
        result["periods"].append(_make_period(str(y), s, e))
        interpretations.append(f"last year = {y}")

    # ── Named months (July, August…) ──────────────────────────────────────────
    for mon_name, mon_num in _MONTH_NAMES.items():
        pattern = rf"\b{mon_name}\b"
        for match in re.finditer(pattern, q_lower):
            # Extract optional year after month name
            ctx = q_lower[match.start():match.start() + 20]
            yr_match = re.search(r"(\d{4})", ctx)
            year = int(yr_match.group(1)) if yr_match else today.year
            s, e = _month_range(year, mon_num)
            label = f"{year}-{mon_num:02d}"
            # Avoid duplicates
            if not any(p["label"] == label for p in result["periods"]):
                result["periods"].append(_make_period(label, s, e))
                interpretations.append(f"{mon_name.title()} → {s.isoformat()} to {e.isoformat()}")

    # ── Quarters ──────────────────────────────────────────────────────────────
    for q_match in re.finditer(r"q([1-4])\s*(\d{4})?", q_lower):
        qnum = int(q_match.group(1))
        yr_str = q_match.group(2)
        year = int(yr_str) if yr_str else today.year
        s, e = _quarter_range(year, qnum)
        label = f"Q{qnum} {year}"
        if not any(p["label"] == label for p in result["periods"]):
            result["periods"].append(_make_period(label, s, e))
            interpretations.append(f"Q{qnum} {year} = {s.isoformat()} to {e.isoformat()}")

    result["interpretation"] = "; ".join(interpretations) if interpretations else "no date filter detected"

    if result["periods"] or result["as_of"]:
        logger.debug(f"Date resolution: {result['interpretation']}")

    return result


def _make_period(label: str, start: date, end: date) -> dict[str, Any]:
    return {
        "label": label,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "start_sql": _oracle_date(start),
        "end_sql": _oracle_date(end),
    }
