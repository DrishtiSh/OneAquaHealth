"""Shared weekly-date-grid helper so every stage (ingestion, weather, ...) aligns
on the exact same site x week index for joins later in the pipeline.
"""

from __future__ import annotations

from datetime import date, timedelta


def weekly_dates(n_weeks: int, anchor: date | None = None) -> list[date]:
    """Returns `n_weeks` consecutive Mondays, oldest first, ending at the most
    recent Monday on/before `anchor`.

    Defaults `anchor` to `date.today() - 14 days` (not "today") so the full
    week range, including its last day, stays inside the Open-Meteo archive's
    coverage -- it lags real-time by several days and rejects future dates.
    """
    anchor = anchor or (date.today() - timedelta(days=14))
    last_monday = anchor - timedelta(days=anchor.weekday())
    return [last_monday - timedelta(weeks=(n_weeks - 1 - i)) for i in range(n_weeks)]
