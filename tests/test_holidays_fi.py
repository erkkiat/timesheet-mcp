"""Tests for :mod:`src.timesheet_mcp.holidays_fi`."""

import datetime

from timesheet_mcp.holidays_fi import get_finnish_holidays, is_working_day

# ── Known fixed and moveable Finnish holidays ────────────────────────────────

# 2025 fixed dates
_HOLIDAYS_2025 = {
    "2025-01-01": "New Year's Day",
    "2025-04-19": "Good Friday",
    "2025-04-21": "Easter Monday",
    "2025-05-01": "Labour Day",
    "2025-05-09": "Ascension Day",
    "2025-06-20": "Midsummer Eve",
    "2025-06-21": "Midsummer Day",
    "2025-11-01": "All Saints' Day",
    "2025-12-06": "Independence Day",
    "2025-12-25": "Christmas Day",
    "2025-12-26": "St Stephen's Day",
}

# 2026 fixed dates
_HOLIDAYS_2026 = {
    "2026-01-01": "New Year's Day",
    "2026-04-03": "Good Friday",
    "2026-04-06": "Easter Monday",
    "2026-05-01": "Labour Day",
    "2026-05-13": "Ascension Day",
    "2026-06-19": "Midsummer Eve",
    "2026-06-20": "Midsummer Day",
    "2026-11-07": "All Saints' Day",
    "2026-12-06": "Independence Day",
    "2026-12-25": "Christmas Day",
    "2026-12-26": "St Stephen's Day",
}


def _dates_to_set(holidays_list: list[dict[str, str]]) -> set[str]:
    """Extract just the date strings from a holiday list."""
    return {h["date"] for h in holidays_list}


class TestGetFinnishHolidays2025:
    """Known holidays present for 2025."""

    def test_returns_list_of_dicts(self):
        result = get_finnish_holidays(2025)
        assert isinstance(result, list)
        for item in result:
            assert isinstance(item, dict)
            assert "date" in item
            assert "name" in item

    def test_dates_are_sorted(self):
        result = get_finnish_holidays(2025)
        dates = [h["date"] for h in result]
        assert dates == sorted(dates)

    def test_new_year(self):
        dates = _dates_to_set(get_finnish_holidays(2025))
        assert "2025-01-01" in dates

    def test_independence_day(self):
        dates = _dates_to_set(get_finnish_holidays(2025))
        names = {h["date"]: h["name"] for h in get_finnish_holidays(2025)}
        assert "2025-12-06" in names  # Independence Day

    def test_good_friday_moveable(self):
        """Good Friday is moveable (depends on Easter)."""
        dates = _dates_to_set(get_finnish_holidays(2025))
        assert "2025-04-18" in dates

    def test_easter_monday_moveable(self):
        """Easter Monday is moveable (depends on Easter)."""
        dates = _dates_to_set(get_finnish_holidays(2025))
        assert "2025-04-21" in dates

    def test_midsummer(self):
        dates = _dates_to_set(get_finnish_holidays(2025))
        assert "2025-06-20" in dates
        assert "2025-06-21" in dates

    def test_christmas(self):
        dates = _dates_to_set(get_finnish_holidays(2025))
        assert "2025-12-25" in dates
        assert "2025-12-26" in dates

    def test_labour_day(self):
        dates = _dates_to_set(get_finnish_holidays(2025))
        assert "2025-05-01" in dates


class TestGetFinnishHolidays2026:
    """Known holidays present for 2026."""

    def test_independence_day(self):
        names = {h["date"]: h["name"] for h in get_finnish_holidays(2026)}
        assert "2026-12-06" in names

    def test_good_friday_moveable(self):
        dates = _dates_to_set(get_finnish_holidays(2026))
        assert "2026-04-03" in dates

    def test_easter_monday_moveable(self):
        dates = _dates_to_set(get_finnish_holidays(2026))
        assert "2026-04-06" in dates

    def test_midsummer(self):
        dates = _dates_to_set(get_finnish_holidays(2026))
        assert "2026-06-19" in dates
        assert "2026-06-20" in dates

    def test_yearly_cache_independent(self):
        """Different years produce different results (cache per year, not global)."""
        holidays_2025 = get_finnish_holidays(2025)
        holidays_2026 = get_finnish_holidays(2026)
        # Easter dates differ between years (moveable feast)
        dates_2025 = {h["date"] for h in holidays_2025}
        dates_2026 = {h["date"] for h in holidays_2026}
        assert dates_2025 != dates_2026


class TestIsWorkingDay:
    """Working-day logic: weekday + not a holiday."""

    def test_weekday_not_holiday(self):
        # 2025-01-02 is Thursday, not a holiday
        d = datetime.date(2025, 1, 2)
        assert is_working_day(d) is True

    def test_sunday(self):
        # 2025-01-05 is Sunday
        d = datetime.date(2025, 1, 5)
        assert is_working_day(d) is False

    def test_saturday(self):
        # 2025-01-04 is Saturday
        d = datetime.date(2025, 1, 4)
        assert is_working_day(d) is False

    def test_new_year_is_not_working_day(self):
        d = datetime.date(2025, 1, 1)
        assert is_working_day(d) is False

    def test_independence_day(self):
        # 2025-12-06 is Friday, but a holiday
        d = datetime.date(2025, 12, 6)
        assert is_working_day(d) is False

    def test_easter_monday(self):
        # 2025-04-21 is Monday, but a holiday
        d = datetime.date(2025, 4, 21)
        assert is_working_day(d) is False

    def test_midsummer_eve(self):
        # 2025-06-20 is Friday, but a holiday
        d = datetime.date(2025, 6, 20)
        assert is_working_day(d) is False

    def test_year_parameter(self):
        # Explicit year: 2026-12-06 is Friday, Independence Day
        d = datetime.date(2025, 12, 6)  # This is Friday in 2025, holiday
        # For 2026, 2025-12-06 doesn't matter; use a date that's different
        # Let's test a known Sunday
        d2 = datetime.date(2026, 12, 6)  # 2026-12-06 is Saturday
        # Independence day is still in the list for 2026
        assert is_working_day(d2, year=2026) is False

    def test_christmas_not_working_day(self):
        d = datetime.date(2025, 12, 25)
        assert is_working_day(d) is False

    def test_labour_day_not_working_day(self):
        d = datetime.date(2025, 5, 1)
        assert is_working_day(d) is False
