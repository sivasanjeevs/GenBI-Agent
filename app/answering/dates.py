"""
dates.py – Deterministic date resolution (Phase 3 / Step 1).

Converts natural-language temporal references into explicit Oracle date
ranges or literals BEFORE the LLM generates SQL.  This prevents the LLM
from guessing what "last month" means and makes the generated SQL auditable.

Design principles
──────────────────
• No LLM – pure Python + regex + dateutil.
• Half-open ranges: ``col >= start AND col < exclusive_end`` avoids
  double-counting at period boundaries (e.g. midnight on the last day).
• All Oracle date literals follow the canonical ``DATE 'YYYY-MM-DD'`` form.
• A ``DateContext`` Pydantic model is the typed output passed downstream.

Supported phrases (case-insensitive)
──────────────────────────────────────
  "today" / "current" / "now"
  "yesterday"
  "last N days" / "last N weeks"
  "last month" / "this month"
  "last year"  / "this year" / "year to date" / "ytd"
  "Q1"–"Q4" [YYYY]
  Named months ("January", "Feb", "August 2025", …)
  "as of <day> <month> <year>"
  ISO dates "2026-08-28"

Public API
──────────
    resolve_dates(question, date_context) -> DateContext
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any

from dateutil.relativedelta import relativedelta
from loguru import logger
from pydantic import BaseModel, Field


# ─── Pydantic Models ──────────────────────────────────────────────────────────

class DatePeriod(BaseModel):
    """A resolved calendar period (half-open range)."""
    label: str
    start_date: str          # ISO-8601 e.g. "2026-09-01"
    end_date: str            # ISO-8601 (inclusive last day, for human display)
    # Oracle half-open range: col >= start AND col < exclusive_end
    start_sql: str           # DATE '2026-09-01'
    exclusive_end_sql: str   # DATE '2026-10-01'  ← one day past end
    # Inclusive range variant kept for backwards compat
    end_sql: str             # DATE '2026-09-30'


class DateContext(BaseModel):
    """Fully resolved date context passed to planner.py."""
    reference_date: str = Field(..., description="ISO date of 'today' used for resolution")
    periods: list[DatePeriod] = Field(default_factory=list)
    as_of: str | None = Field(None, description="Oracle DATE literal for point-in-time queries")
    interpretation: str = Field("no date filter detected")

    def has_dates(self) -> bool:
        return bool(self.periods or self.as_of)

    def to_sql_hint(self) -> str:
        """
        Return a concise SQL hint string the planner injects into the prompt.

        Uses half-open ranges to prevent double-counting:
            col >= DATE 'YYYY-MM-DD' AND col < DATE 'YYYY-MM-DD'
        """
        lines: list[str] = [f"-- Reference date: {self.reference_date}"]
        if self.as_of:
            lines.append(f"-- Point-in-time filter: col <= {self.as_of}")
        for p in self.periods:
            lines.append(
                f"-- Period '{p.label}': "
                f"col >= {p.start_sql} AND col < {p.exclusive_end_sql}"
            )
        lines.append(f"-- Interpretation: {self.interpretation}")
        return "\n".join(lines)


# ─── Internal Constants ───────────────────────────────────────────────────────

_MONTH_NAMES: dict[str, int] = {
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

_QUARTER_MONTH_RANGE: dict[int, tuple[int, int]] = {
    1: (1, 3), 2: (4, 6), 3: (7, 9), 4: (10, 12)
}


# ─── Date Arithmetic Helpers ──────────────────────────────────────────────────

def _oracle_date(d: date) -> str:
    return f"DATE '{d.isoformat()}'"


def _make_period(label: str, start: date, end_inclusive: date) -> DatePeriod:
    """
    Build a DatePeriod with a half-open exclusive end for Oracle SQL.

    Exclusive end = end_inclusive + 1 day, so:
        col >= start AND col < exclusive_end
    correctly captures every timestamp on end_inclusive day.
    """
    exclusive_end = end_inclusive + timedelta(days=1)
    return DatePeriod(
        label=label,
        start_date=start.isoformat(),
        end_date=end_inclusive.isoformat(),
        start_sql=_oracle_date(start),
        exclusive_end_sql=_oracle_date(exclusive_end),
        end_sql=_oracle_date(end_inclusive),
    )


def _month_range(year: int, month: int) -> tuple[date, date]:
    start = date(year, month, 1)
    end = (start + relativedelta(months=1)) - timedelta(days=1)
    return start, end


def _quarter_range(year: int, q: int) -> tuple[date, date]:
    start_month, end_month = _QUARTER_MONTH_RANGE[q]
    start = date(year, start_month, 1)
    end = date(year, end_month, 1) + relativedelta(months=1) - timedelta(days=1)
    return start, end


def _parse_reference_date(date_context: str | None) -> date:
    """Return today or parse 'today is YYYY-MM-DD' from an explicit context string."""
    if date_context:
        m = re.search(r"(\d{4}-\d{2}-\d{2})", date_context)
        if m:
            return date.fromisoformat(m.group(1))
    return date.today()


# ─── Public API ───────────────────────────────────────────────────────────────

def resolve_dates(
    question: str,
    *,
    date_context: str | None = None,
) -> DateContext:
    """
    Parse ``question`` for temporal references and return a ``DateContext``.

    Args:
        question:     The raw user question string.
        date_context: Optional override string like "today is 2026-08-28".

    Returns:
        DateContext – typed, with half-open Oracle SQL date ranges.
    """
    today = _parse_reference_date(date_context)
    q = question.lower()

    periods: list[DatePeriod] = []
    as_of: str | None = None
    interpretations: list[str] = []

    # ── Deduplicate helper ────────────────────────────────────────────────────
    seen_labels: set[str] = set()

    def _add_period(p: DatePeriod) -> None:
        if p.label not in seen_labels:
            seen_labels.add(p.label)
            periods.append(p)

    # ── 1. "as of <day> <month> <year>" ──────────────────────────────────────
    as_of_m = re.search(r"as\s+of\s+(\d{1,2})\s+(\w+)\s+(\d{4})", q)
    if as_of_m:
        day, mon_str, year_str = as_of_m.group(1), as_of_m.group(2), as_of_m.group(3)
        mon = _MONTH_NAMES.get(mon_str)
        if mon:
            d = date(int(year_str), mon, int(day))
            as_of = _oracle_date(d)
            interpretations.append(f"as of {d.isoformat()}")

    # ── 2. ISO date literal "2026-08-28" ─────────────────────────────────────
    if not as_of:
        iso_dates = re.findall(r"\b(\d{4}-\d{2}-\d{2})\b", question)
        if iso_dates:
            d = date.fromisoformat(iso_dates[0])
            as_of = _oracle_date(d)
            interpretations.append(f"as of {d.isoformat()}")

    # ── 3. "today" / "current" / "now" ───────────────────────────────────────
    if re.search(r"\b(today|current|now)\b", q):
        as_of = as_of or _oracle_date(today)
        interpretations.append(f"current / today = {today.isoformat()}")

    # ── 4. "yesterday" ───────────────────────────────────────────────────────
    if "yesterday" in q:
        yesterday = today - timedelta(days=1)
        p = _make_period("yesterday", yesterday, yesterday)
        _add_period(p)
        interpretations.append(f"yesterday = {yesterday.isoformat()}")

    # ── 5. "last N days" ─────────────────────────────────────────────────────
    m_days = re.search(r"last\s+(\d+)\s+days?", q)
    if m_days:
        n = int(m_days.group(1))
        start = today - timedelta(days=n)
        p = _make_period(f"last {n} days", start, today - timedelta(days=1))
        _add_period(p)
        interpretations.append(f"last {n} days = {start.isoformat()} to {(today - timedelta(days=1)).isoformat()}")

    # ── 6. "last N weeks" ────────────────────────────────────────────────────
    m_weeks = re.search(r"last\s+(\d+)\s+weeks?", q)
    if m_weeks:
        n = int(m_weeks.group(1))
        start = today - timedelta(weeks=n)
        p = _make_period(f"last {n} weeks", start, today - timedelta(days=1))
        _add_period(p)
        interpretations.append(
            f"last {n} weeks = {start.isoformat()} to {(today - timedelta(days=1)).isoformat()}"
        )

    # ── 7. "last month" ──────────────────────────────────────────────────────
    if "last month" in q:
        ref = today - relativedelta(months=1)
        s, e = _month_range(ref.year, ref.month)
        p = _make_period(f"{ref.year}-{ref.month:02d}", s, e)
        _add_period(p)
        interpretations.append(f"last month = {s.strftime('%B %Y')}")

    # ── 8. "this month" ──────────────────────────────────────────────────────
    if "this month" in q:
        s, e = _month_range(today.year, today.month)
        p = _make_period(f"{today.year}-{today.month:02d}", s, e)
        _add_period(p)
        interpretations.append(f"this month = {s.strftime('%B %Y')}")

    # ── 9. "last year" ───────────────────────────────────────────────────────
    if "last year" in q:
        y = today.year - 1
        p = _make_period(str(y), date(y, 1, 1), date(y, 12, 31))
        _add_period(p)
        interpretations.append(f"last year = {y}")

    # ── 10. "this year" ──────────────────────────────────────────────────────
    if "this year" in q:
        s = date(today.year, 1, 1)
        p = _make_period(str(today.year), s, date(today.year, 12, 31))
        _add_period(p)
        interpretations.append(f"this year = {today.year}")

    # ── 11. "year to date" / "ytd" ───────────────────────────────────────────
    if re.search(r"\b(year.?to.?date|ytd)\b", q):
        s = date(today.year, 1, 1)
        p = _make_period(f"YTD {today.year}", s, today)
        _add_period(p)
        interpretations.append(f"year to date = {s.isoformat()} to {today.isoformat()}")

    # ── 12. Named months ─────────────────────────────────────────────────────
    # Sort by length descending so "september" is matched before "sep"
    for mon_name in sorted(_MONTH_NAMES.keys(), key=len, reverse=True):
        if not re.search(rf"\b{mon_name}\b", q):
            continue
        # Extract optional year immediately after the month name
        ctx_match = re.search(
            rf"\b{mon_name}\b\s*(\d{{4}})?", q
        )
        yr = int(ctx_match.group(1)) if ctx_match and ctx_match.group(1) else today.year
        mon_num = _MONTH_NAMES[mon_name]
        label = f"{yr}-{mon_num:02d}"
        s, e = _month_range(yr, mon_num)
        p = _make_period(label, s, e)
        _add_period(p)
        interpretations.append(
            f"{mon_name.title()} → {s.isoformat()} to {e.isoformat()}"
        )

    # ── 13. Quarters "Q1", "q3 2026" ─────────────────────────────────────────
    for qm in re.finditer(r"\bq([1-4])\s*(\d{4})?\b", q):
        qnum = int(qm.group(1))
        yr = int(qm.group(2)) if qm.group(2) else today.year
        s, e = _quarter_range(yr, qnum)
        label = f"Q{qnum} {yr}"
        p = _make_period(label, s, e)
        _add_period(p)
        interpretations.append(f"Q{qnum} {yr} = {s.isoformat()} to {e.isoformat()}")

    interp_str = "; ".join(interpretations) if interpretations else "no date filter detected"

    ctx = DateContext(
        reference_date=today.isoformat(),
        periods=periods,
        as_of=as_of,
        interpretation=interp_str,
    )

    if ctx.has_dates():
        logger.debug("Date resolution: {}", interp_str)

    return ctx
