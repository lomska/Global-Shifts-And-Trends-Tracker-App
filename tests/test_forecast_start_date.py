"""
Regression test for the forecast-period boundary of the population data. It used to be hardcoded
(and went stale every year), then computed from today's date. Now the population source reads it
from the data: the last year World Development Indicators (WDI) reports for total population is the
last estimated year (sources.last_estimate_year), so later years are flagged is_projection and the
charts split at that year + 0.5 (data_utils.projection_starts / series_split). If WDI can't be
reached it falls back to the date rule (sources.date_rule_last_estimate): from August 1st onward,
last year; before that, the year before. This checks the WDI path, the fallback, the date rule and
the flags the population fetch sets.
"""
import _pathfix  # noqa: F401
import datetime as dt
from unittest.mock import patch

import requests

import data_utils as du
import sources as ds
from test_app2 import FAKE_LAST_ESTIMATE_YEAR, fake_get


class Session:
    """A stand-in requests session whose get() is the given fake."""

    def __init__(self, get):
        self.get = get


# WDI path: last estimate year from the (mocked) API.
assert ds.last_estimate_year(Session(fake_get)) == FAKE_LAST_ESTIMATE_YEAR
print(f"OK: last_estimate_year() = last WDI estimate year ({FAKE_LAST_ESTIMATE_YEAR})")


# Fallback: WDI unreachable, or an unexpected response shape -> the date rule.
def unreachable(*args, **kwargs):
    raise requests.ConnectionError("simulated: api.worldbank.org unreachable")


class EmptyResponse:
    def raise_for_status(self):
        return None

    def json(self):
        return [{"page": 1, "pages": 0, "total": 0}, None]  # WDI's shape when there's no data


for label, get in [("unreachable", unreachable), ("no data", lambda *a, **k: EmptyResponse())]:
    got = ds.last_estimate_year(Session(get))
    assert got == ds.date_rule_last_estimate(dt.date.today()), got
    print(f"OK: WDI {label} -> falls back to the date rule ({got})")

# The date rule itself, across the August 1st boundary and a year rollover.
cases = [
    (dt.date(2026, 1, 1), 2024),    # early in the year, before August -> the year before last
    (dt.date(2026, 7, 31), 2024),   # the last day before the August 1st cutover
    (dt.date(2026, 8, 1), 2025),    # cutover day itself -> last year now presumed estimated
    (dt.date(2026, 12, 31), 2025),  # rest of the year after the cutover
    (dt.date(2027, 8, 1), 2026),    # the same cutover, one year later
]
for d, expected in cases:
    got = ds.date_rule_last_estimate(d)
    assert got == expected, f"{d}: expected {expected}, got {got}"
    print(f"OK: {d} -> {got}")


# The population fetch flags every year after the last estimate as a projection, and the charts
# split there -- also when the lookup fails (date rule).
def population_split(get):
    table, _ = ds.fetch_population(Session(get))
    flags = table.groupby("year")["is_projection"].agg(["min", "max"])
    assert (flags["min"] == flags["max"]).all(), "a year is a projection for every series or for none"
    return du.projection_starts(table)[du.POP_TOTAL]


assert population_split(fake_get) == FAKE_LAST_ESTIMATE_YEAR + 0.5


def lookup_down(url, *args, **kwargs):
    if url == ds.LAST_ESTIMATE_URL:
        unreachable()
    return fake_get(url, *args, **kwargs)


with patch.object(ds, "date_rule_last_estimate", lambda today=None: 2019):
    assert population_split(lookup_down) == 2019.5
print("OK: the population data is flagged as projected after the last estimate year, with or without WDI")

print("\nALL FORECAST START DATE TESTS PASSED")
