"""
The Distributions tab's box plot per year (under "Global Distribution Shift By Year"): the per-year statistics
(quartiles, whiskers, outliers, the max/min countries, the log-axis exclusion), the figure (one
hover trace covering each year once, a trace count that doesn't grow with the years), and, in
the app, the chart for a linear and a log indicator with its two toggles (Yes/No, Show/Hide).
"""
import _pathfix  # noqa: F401
import json
import re
from unittest.mock import patch

import numpy as np
import pandas as pd

import data_utils as du
from test_app2 import fake_get

import app as app_mod

# --- Statistics on a small table ---
countries = pd.DataFrame({"country_code": list("ABCDE"), "country_name": [f"Country {c}" for c in "ABCDE"]})
wide = pd.DataFrame({2000: [1.0, 2.0, 3.0, 4.0, 100.0], 2001: [0.0, 10.0, 20.0, np.nan, 30.0]},
                    index=pd.Index(list("ABCDE"), name="country_code"))
stats, outliers, hidden = app_mod.yearly_box_stats(wide, countries, False)
s = stats.loc[2000]
# Linear interpolation (numpy "linear"): positions 1, 2, 3 of the sorted five values.
assert (s["q1"], s["median"], s["q3"]) == (2.0, 3.0, 4.0), s
assert s["mean"] == 22.0 and s["n"] == 5, s
# Fences 2 - 3 = -1 and 4 + 3 = 7: whiskers at 1 and 4, 100 is an outlier.
assert (s["lo_whisker"], s["hi_whisker"]) == (1.0, 4.0), s
assert (s["max"], s["max_country"], s["min"], s["min_country"]) == (100.0, "Country E", 1.0, "Country A"), s
assert outliers.to_dict("records") == [{"year": 2000, "value": 100.0, "country": "Country E"}], outliers
assert hidden == 0
assert stats.loc[2001, "n"] == 4 and stats.loc[2001, "min_country"] == "Country A"  # 0 is kept on a linear axis
# Log axis: the 0 is left out of 2001's box and statistics, and counted.
stats_log, _, hidden = app_mod.yearly_box_stats(wide, countries, True)
assert hidden == 1, hidden
s = stats_log.loc[2001]
assert s["n"] == 3 and s["min"] == 10.0 and s["min_country"] == "Country B" and s["mean"] == 20.0, s
assert (s["q1"], s["median"], s["q3"]) == (15.0, 20.0, 25.0), s
print("OK: yearly_box_stats")

# The log rule is the histogram's widening bins, through one helper.
assert app_mod.widening_bins(app_mod.DISTRIBUTION_INDICATORS["Total population"]["bins"])
assert not app_mod.widening_bins(app_mod.DISTRIBUTION_INDICATORS["Real GDP growth"]["bins"])


# --- The figure: fixed trace count, one hover trace ---
def boxes(n_years, split=np.inf, **kw):
    rng = np.random.default_rng(0)
    w = pd.DataFrame(rng.normal(size=(30, n_years)), columns=range(1960, 1960 + n_years),
                     index=pd.Index([f"C{i}" for i in range(30)], name="country_code"))
    names = pd.DataFrame({"country_code": w.index, "country_name": w.index})
    st_, out, _ = app_mod.yearly_box_stats(w, names, False)
    return st_, app_mod.distribution_boxes(st_, out, "Real GDP growth", "percent", split=split, log=False,
                                           fmt=",.1f", suffix="%", **kw)


def hover_traces(fig):
    return [tr for tr in fig.data if tr.hoverinfo != "skip"]


st10, fig10 = boxes(10, split=1965.5)
_, fig60 = boxes(60, split=1990.5)
assert len(fig10.data) == len(fig60.data), (len(fig10.data), len(fig60.data))
for fig, n in ((fig10, 10), (fig60, 60)):
    (hover,) = hover_traces(fig)  # exactly one, over observed and forecast years together
    assert list(hover.x) == list(range(1960, 1960 + n)), hover.x
    assert "Upper quartile" in hover.hovertemplate and "Mean:" in hover.hovertemplate
assert [tr.name for tr in fig10.data if tr.showlegend is not False] == ["Observed", "Forecast", "Median", "Mean"]
assert fig10.layout.xaxis.dtick == 5 and fig60.layout.xaxis.dtick == 10
assert tuple(fig10.layout.xaxis.range) == (1959, 1970)
title = fig10.layout.title.text
assert "<b>Distribution of Countries by Real GDP Growth, 1960–1969</b>" in title, title
_, no_mean = boxes(10, show_mean=False)
assert "Mean" not in hover_traces(no_mean)[0].hovertemplate
assert "Mean" not in [tr.name for tr in no_mean.data] and "Forecast" not in [tr.name for tr in no_mean.data]
_, fitted = boxes(10, fit=True)
lo, hi = st10["lo_whisker"].min(), st10["hi_whisker"].max()
pad = app_mod.BOX_FIT_PAD * (hi - lo)
assert np.allclose(fitted.layout.yaxis.range, (lo - pad, hi + pad)), fitted.layout.yaxis.range
assert [app_mod._short_count(v) for v in (1e3, 3e6, 1e9, 1e12, 1e13)] == ["1k", "3M", "1B", "1T", "10T"]
print("OK: distribution_boxes")


# --- In the app ---
def box_figure(at):
    for el in at.get("plotly_chart"):
        spec = json.loads(el.proto.spec)
        if re.search(r", \d{4}–\d{4}</b>", spec["layout"]["title"]["text"]):  # the histogram's ends "a vs. b"
            return spec
    raise AssertionError("no box plot on the page")


def check(at, what):
    assert not at.exception, [e.value for e in at.exception]
    print(f"OK: {what}")


du.clear_disk_cache()
with patch.object(du._SESSION, "get", side_effect=fake_get):
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file(_pathfix.APP_PATH, default_timeout=120)
    at.run()
    check(at, "app loads")
    assert at.selectbox(key="dist_indicator_Economics").value == "Real GDP growth"
    def toggles():
        return (at.segmented_control(key="dist_box_fit_Real GDP growth").value,
                at.segmented_control(key="dist_box_mean_Real GDP growth").value)

    assert toggles() == ("No", "Show"), toggles()
    fig = box_figure(at)
    assert fig["layout"]["title"]["text"].startswith("<b>Distribution of Countries by Real GDP Growth, "), fig
    assert fig["layout"]["yaxis"].get("type") != "log" and "range" not in fig["layout"]["yaxis"]
    hovers = [tr for tr in fig["data"] if tr.get("hoverinfo") != "skip"]
    assert len(hovers) == 1 and len(hovers[0]["x"]) == len(set(hovers[0]["x"])), hovers
    assert any(tr.get("name") == "Forecast" for tr in fig["data"])  # IMF projections
    footer = [m.value for m in at.tabs[0].markdown if "Source:" in m.value][-1]  # Distributions: the first tab
    assert "on are projections." in footer, footer
    n_traces = len(fig["data"])

    at.segmented_control(key="dist_box_fit_Real GDP growth").set_value("Yes").run()
    at.segmented_control(key="dist_box_mean_Real GDP growth").set_value("Hide").run()
    check(at, "toggles changed")
    fig = box_figure(at)
    assert "range" in fig["layout"]["yaxis"], fig["layout"]["yaxis"]
    assert not any(tr.get("name") == "Mean" for tr in fig["data"])
    assert len(fig["data"]) == n_traces - 3  # observed and forecast mean segments, and the legend key

    # Another indicator and back: both toggles are on their defaults again.
    at.selectbox(key="dist_indicator_Economics").set_value("Consumer prices").run()
    at.selectbox(key="dist_indicator_Economics").set_value("Real GDP growth").run()
    check(at, "indicator switched and back")
    assert toggles() == ("No", "Show"), toggles()
    # The same after a trip through another group.
    at.segmented_control(key="dist_box_fit_Real GDP growth").set_value("Yes").run()
    at.segmented_control(key="dist_section").set_value("Demographics").run()
    at.selectbox(key="dist_indicator_Demographics").set_value("Total population").run()
    check(at, "log indicator")
    fig = box_figure(at)
    assert fig["layout"]["yaxis"]["type"] == "log", fig["layout"]["yaxis"]
    assert "log scale" in fig["layout"]["title"]["text"]
    assert all(t in ("1", "10", "100", "1k", "10k", "100k") or t[-1] in "kMBT"
               for t in fig["layout"]["yaxis"]["ticktext"]), fig["layout"]["yaxis"]["ticktext"]
    at.segmented_control(key="dist_section").set_value("Economics").run()
    check(at, "back to Economics")
    assert toggles()[0] == "No", toggles()

du.clear_disk_cache()
print("\nALL BOX PLOT CHECKS PASSED")
