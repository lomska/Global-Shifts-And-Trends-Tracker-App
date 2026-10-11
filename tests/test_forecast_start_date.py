"""
Regression test for the forecast-period boundary. It used to be hardcoded (and went stale
every year), then computed from today's date. Now data_utils.forecast_start() reads it from
the data: the last year World Development Indicators (WDI) reports for total population is
the last estimated year, so the boundary is that year + 0.5. If WDI can't be reached it falls
back to the date rule (_compute_forecast_start): from August 1st onward, (this year - 1) + 0.5;
before that, one year earlier. This checks the WDI path, the fallback, and the date rule.
"""
import _pathfix  # noqa: F401
import datetime as dt
from unittest.mock import patch

import requests

import data_utils as du
from test_app2 import FAKE_LAST_ESTIMATE_YEAR, fake_get

# WDI path: last estimate year from the (mocked) API, + 0.5.
du.forecast_start.clear()
with patch.object(du._SESSION, "get", side_effect=fake_get):
    assert du.last_estimate_year() == FAKE_LAST_ESTIMATE_YEAR
    assert du.forecast_start() == FAKE_LAST_ESTIMATE_YEAR + 0.5, du.forecast_start()
print(f"OK: forecast_start() = last WDI estimate year + 0.5 ({FAKE_LAST_ESTIMATE_YEAR + 0.5})")


# Fallback: WDI unreachable, or an unexpected response shape -> the date rule.
def unreachable(*args, **kwargs):
    raise requests.ConnectionError("simulated: api.worldbank.org unreachable")


class EmptyResponse:
    def raise_for_status(self):
        return None

    def json(self):
        return [{"page": 1, "pages": 0, "total": 0}, None]  # WDI's shape when there's no data


for label, side_effect in [("unreachable", unreachable), ("no data", lambda *a, **k: EmptyResponse())]:
    du.forecast_start.clear()
    with patch.object(du._SESSION, "get", side_effect=side_effect):
        got = du.forecast_start()
    assert got == du._compute_forecast_start(dt.date.today()), got
    print(f"OK: WDI {label} -> falls back to the date rule ({got})")
du.forecast_start.clear()

# The date rule itself, across the August 1st boundary and a year rollover.
cases = [
    (dt.date(2026, 1, 1), 2024.5),    # early in the year, before August -> one year earlier
    (dt.date(2026, 7, 31), 2024.5),   # the last day before the August 1st cutover
    (dt.date(2026, 8, 1), 2025.5),    # cutover day itself -> last year now presumed final
    (dt.date(2026, 12, 31), 2025.5),  # rest of the year after the cutover
    (dt.date(2027, 8, 1), 2026.5),    # the same cutover, one year later
]
for d, expected in cases:
    got = du._compute_forecast_start(d)
    assert got == expected, f"{d}: expected {expected}, got {got}"
    print(f"OK: {d} -> {got}")

print("\nALL FORECAST START DATE TESTS PASSED")
