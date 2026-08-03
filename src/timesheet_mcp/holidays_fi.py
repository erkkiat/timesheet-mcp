"""Thin wrapper around the ``holidays`` package for Finnish public holidays.

Caches results per-year because the library recomputes moveable feasts
(e.g. Easter) for each year independently.
"""

from __future__ import annotations

import datetime

import holidays


# Per-year cache: year -> Country holidays object
_cache: dict[int, holidays.FI] = {}


def get_finnish_holidays(year: int) -> list[dict[str, str]]:
    """Return a list of known Finnish holidays for *year*.

    Format: ``[{"date": "YYYY-MM-DD", "name": "Holiday name"}, ...]``

    Results are cached per-year to avoid redundant lookups when the same
    year is requested multiple times (e.g. by the reports module).
    """
    if year not in _cache:
        _cache[year] = holidays.country_holidays("FI", years=[year])

    fi_holidays = _cache[year]

    result: list[dict[str, str]] = []
    for date, name in sorted(fi_holidays.items()):
        result.append(
            {"date": date.strftime("%Y-%m-%d"), "name": name}
        )

    return result


def get_finnish_holidays_raw(year: int) -> holidays.FI:
    """Return the raw ``holidays.FI`` object for *year* (internal only)."""
    if year not in _cache:
        _cache[year] = holidays.country_holidays("FI", years=[year])
    return _cache[year]


def is_working_day(d: datetime.date, *, year: int | None = None) -> bool:
    """Return ``True`` if *d* is a Monday–Friday and not a Finnish holiday.

    Parameters
    ----------
    d : datetime.date
        The date to check.
    year : int, optional
        Explicit year to validate against.  If *None*, inferred from *d*.
    """
    if year is None:
        year = d.year

    if d.weekday() >= 5:  # Saturday=5, Sunday=6
        return False

    return d not in get_finnish_holidays_raw(year)
