"""
Regression test for the forecast-period marker: charts don't shade the forecast period
with a grey band (no rect or line shapes at x); instead trend_chart draws each series
solid up to forecast_start() and dotted from there on, and trend_stacked_bar draws
forecast years at half strength.
"""
import _pathfix  # noqa: F401
from unittest.mock import patch

import data_utils as du
from test_app2 import FAKE_LAST_ESTIMATE_YEAR, fake_get

du.clear_disk_cache()

with patch.object(du._SESSION, "get", side_effect=fake_get):
    df, countries = du.load_data()
    du.forecast_start.clear()
    split = du.forecast_start()  # cached from here on, so the charts below reuse this value
assert split == FAKE_LAST_ESTIMATE_YEAR + 0.5, split

import app as app_mod

t = du.trends_data(df, "WLD")


def assert_no_shading(fig, name):
    bands = [s for s in fig.layout.shapes if s.type in ("rect", "line") and s.xref == "x"]
    assert not bands, f"{name}: expected no forecast shading/vline shapes, got {bands}"


lines = {"Birth rate": t["SP.DYN.CBRT.IN"], "Death rate": t["SP.DYN.CDRT.IN"]}
fig = app_mod.trend_chart(lines, {}, title="t")
assert_no_shading(fig, "trend_chart")
print("OK: trend_chart draws no forecast shading")

# Each series: a solid legend trace before the split, a dotted trace from it on, a dotted bridge
# between them (none of them answering hover), and an invisible hover trace over all its years.
drawn = [tr for tr in fig.data if tr.line.width != 0]
solid = [tr for tr in drawn if tr.line.dash is None]
dotted = [tr for tr in drawn if tr.line.dash == "dot" and min(tr.x) >= split]
bridges = [tr for tr in drawn if tr.line.dash == "dot" and len(tr.x) == 2 and min(tr.x) < split]
assert len(solid) == len(dotted) == len(bridges) == len(lines) and len(drawn) == 3 * len(lines)
assert all(max(tr.x) < split for tr in solid)
assert all(tr.hoverinfo == "skip" for tr in drawn)
assert all(tr.showlegend is False for tr in dotted + bridges) and all(tr.showlegend is not False for tr in solid)
print("OK: each series is split into a solid observed line and a dotted forecast line")


def assert_one_hover_trace(fig, lines, name, split):
    """Regression (2026-10-11): next to the split, the solid and dotted pieces both answered the
    "x unified" hover, so the tooltip listed each series twice. Exactly one trace per series must
    answer hover, covering each of its years once; it is invisible (no line swatch in the
    tooltip) and adds " (forecast)" after the value in forecast years."""
    hover = [tr for tr in fig.data if tr.hoverinfo != "skip"]
    assert [tr.legendgroup for tr in hover] == list(lines), f"{name}: {[tr.legendgroup for tr in hover]}"
    for tr, (label, s) in zip(hover, lines.items()):
        years = list(tr.x)
        assert len(years) == len(set(years)), f"{name}: {label} has a year twice in its hover trace"
        assert sorted(years) == sorted(s.dropna().index), f"{name}: {label} hover misses years"
        assert label in tr.hovertemplate and "%{text}<extra>" in tr.hovertemplate
        assert tr.line.width == 0 and tr.line.color == "rgba(0,0,0,0)" and tr.showlegend is False
        assert [t == " (forecast)" for t in tr.text] == [y >= split for y in years], f"{name}: {label} text"
        assert all(t in ("", " (forecast)") for t in tr.text)


assert_one_hover_trace(fig, lines, "trend_chart", split)
assert any(min(s.index) < split < max(s.index) for s in lines.values()), "fixture must span the split"
no_fcst = {"Observed only": t["SP.DYN.CBRT.IN"]}
plain = app_mod.trend_chart(no_fcst, {}, title="t", forecast_x=float("inf"))
assert len(plain.data) == 2 and plain.data[0].line.dash is None and plain.data[0].hoverinfo == "skip"
assert_one_hover_trace(plain, no_fcst, "no forecast", float("inf"))
slog = app_mod.trend_chart(lines, {}, title="t", y_log=True)
assert_one_hover_trace(slog, lines, "y_log", split)
for tr in slog.data:
    if tr.hoverinfo != "skip":
        assert "%{customdata" in tr.hovertemplate and "%{y" not in tr.hovertemplate
        assert list(tr.customdata) == list(lines[tr.legendgroup].dropna()), "y_log: tooltip must show real values"
print("OK: one hover trace per series covering every year once (also without a forecast and with y_log)")

pop = app_mod.trend_chart({"Population": t["SP.POP.TOTL"]}, {}, title="t", hline_zero=True)
assert pop.layout.yaxis.rangemode == "tozero", "hline_zero must extend the y-axis to include 0"
print("OK: hline_zero extends the y-axis to 0 (total population)")

bars = app_mod.trend_stacked_bar({"Net migration": t["SM.POP.NETM"], "Natural": t["natural_increase"]}, {}, title="t")
assert_no_shading(bars, "trend_stacked_bar")
assert bars.layout.barmode == "relative" and len(bars.data) == 2
assert all(c.endswith(f",{app_mod.FORECAST_BAR_ALPHA})") == (x >= split) for tr in bars.data for x, c in zip(tr.x, tr.marker.color))
print("OK: trend_stacked_bar stacks relative to zero, forecast years at half strength")

dep = app_mod.trend_stacked_bar({"Youth": t["SP.POP.DPND.YG"], "Elderly": t["SP.POP.DPND.OL"]}, {}, title="t",
                                hover_only={"Total": t["SP.POP.DPND"]})
bar_traces = [tr for tr in dep.data if tr.type == "bar"]
hover_rows = [tr for tr in dep.data if tr.type == "scatter"]
assert len(bar_traces) == 2 and len(hover_rows) == 1 and hover_rows[0].line.width == 0
assert list(hover_rows[0].x) == list(bar_traces[0].x), "tooltip-only total must cover the same years as the bars"
print("OK: trend_stacked_bar hover_only adds an invisible tooltip row (dependency ratio total)")

du.clear_disk_cache()
print("\nALL FORECAST MARKER TESTS PASSED")
