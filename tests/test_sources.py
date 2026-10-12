"""
The data sources (sources.py) and their shared loader (data_utils.load_data):

1. Country dictionary: source codes and name variants map to one code; other sources' own
   groups ("North America" the continent, IMF groups) are dropped, never matched to WB aggregates.
2. A failing source doesn't take the app down: only its own charts go empty, with a visible
   warning, while the other sources (the population data among them) still load.
3. Each source has its own on-disk cache: a second process start reads it instead of the
   network, and a cached source missing a series (written by an older app version) is refetched.
4. Release dates ("Last updated" under the Trends charts): a date that can't be read leaves the
   source loaded and its footer without the date; a cache written before the dates were kept is
   refetched once.
5. A World Bank request that times out is tried again, so one slow series doesn't fail WDI.
"""
import _pathfix  # noqa: F401
import json
from unittest.mock import patch

import pandas as pd

import country_dict as cd
import data_utils as du
import sources as ds
from test_app2 import EXPECTED_RELEASES, fake_get

# --- 1. Country dictionary ---
cases = {("UVK", None): "XKX", ("KOS", None): "XKX", ("ROM", None): "ROU", ("WBG", None): "PSE",
         ("G001", None): "WLD", ("XD", "High income"): "HIC", (None, "Congo Democratic Republic"): "COD",
         (None, "Cote d'Ivoire"): "CIV", (None, "High-income countries"): "HIC", (None, "Kosovo"): "XKX",
         (None, "North America"): None, (None, "Africa (GCP)"): None, ("G110", None): None,
         ("ANT", "Netherlands Antilles (former)"): None, ("CHA", None): "CHI",
         (None, "Cambodia (Kampuchea)"): "KHM", (None, "World (excl. China)"): None,
         (None, "Côte d’Ivoire"): "CIV", (None, "Congo-Kinshasa"): "COD", (None, "Vatican City State"): "VAT"}
for (code, name), expected in cases.items():
    assert cd.to_iso3(code, name) == expected, (code, name, cd.to_iso3(code, name), expected)
raw = pd.DataFrame({"c": ["USA", "UVK", "G110", "USA"], "v": [1, 2, 3, 4]})
out = cd.unify_countries(raw, code_col="c")
assert list(out["country_code"]) == ["USA", "XKX", "USA"] and list(out["country_name"])[1] == "Kosovo"
assert all(du.REGION_CODES[c] == cd.COUNTRIES[c] for c in du.REGION_CODES)  # same names as the population data
print("OK: country dictionary")

# --- 2. One failing source ---
IMF_DOWN = "simulated: IMF blocks scripted downloads"


def imf_down_get(url, *args, **kwargs):
    if url.startswith(ds.IMF_SDMX_URL) or url.startswith(ds.IMF_DATAMAPPER_URL):  # both IMF routes
        raise ConnectionError(IMF_DOWN)
    return fake_get(url, *args, **kwargs)


du.clear_disk_cache()
du.load_data.clear()
with patch.object(du._SESSION, "get", side_effect=imf_down_get):
    data, errors = du.load_data()
    assert set(errors) == {"IMF"} and IMF_DOWN in errors["IMF"], errors
    assert not data["series_code"].str.startswith("IMF:").any()
    assert set(du.SERIES) - set(ds.series_of("IMF")) <= set(data["series_code"])
    assert not du._source_cache_file("IMF").exists()  # a failure isn't written to disk...
    assert du._source_cache_file("WDI").exists()  # ...successes are

    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file(_pathfix.APP_PATH, default_timeout=120)
    at.run()
    assert not at.exception, at.exception
    warnings = [w.value for w in at.warning]
    # Economics only (every IMF series is there now); no other source named.
    assert len(warnings) == 1 and "IMF" in warnings[0] and "ND-GAIN" not in warnings[0], warnings
    infos = [i.value for i in at.info]
    # World keeps WDI's eight Economics charts: the six IMF charts are left out, named in one note.
    economics_note = next(i for i in infos if "Real GDP growth" in i)
    assert economics_note.startswith("8 of 14 indicators have data for World."), economics_note
    assert not any("population" in i.lower() for i in infos), infos  # demographics unaffected
    # Low income has no WDI data in the fakes either: Economics is skipped entirely, but the
    # IMF failure still shows (at the top of the tab).
    at.selectbox(key="trends_entity").set_value("LIC").run()
    assert not at.exception, at.exception
    assert "Economics" not in [h.value for h in at.subheader]
    assert len(at.warning) == 1 and "IMF" in at.warning[0].value, [w.value for w in at.warning]
    at.selectbox(key="trends_entity").set_value("WLD").run()
    at.segmented_control(key="dist_section").set_value("Economics").run()
    at.selectbox(key="dist_indicator_Economics").set_value("Real GDP growth").run()  # an IMF indicator
    assert not at.exception, at.exception
    assert any("couldn't reach IMF" in i.value for i in at.info), [i.value for i in at.info]
print("OK: a failed source only empties its own charts, with a warning")

# --- 3. Per-source disk cache ---
calls = []


def counting_get(url, *args, **kwargs):
    calls.append(url)
    return fake_get(url, *args, **kwargs)


du.clear_disk_cache()
du.load_data.clear()
with patch.object(du._SESSION, "get", side_effect=counting_get):
    data1, errors1 = du.load_data()
    assert errors1 == {} and calls, errors1
    n_first = len(calls)

    du.load_data.clear()  # a process restart: memory cache gone, disk cache still there
    data2, _ = du.load_data()
    assert len(calls) == n_first, calls[n_first:]
    assert len(data2) == len(data1)

    # An older app version's ND-GAIN cache without vulnerability/readiness: refetched, not trusted.
    ndgain_file = du._source_cache_file("NDGAIN")
    stale = pd.read_parquet(ndgain_file)
    stale[stale["series_code"] == "NDGAIN:GAIN"].to_parquet(ndgain_file, index=False)
    du.load_data.clear()
    data3, _ = du.load_data()
    assert calls[n_first:] == [ds.NDGAIN_URL], calls[n_first:]  # only the stale source
    assert set(ds.series_of("NDGAIN")) <= set(data3["series_code"])
du.clear_disk_cache()
print("OK: per-source disk cache, with the completeness self-heal")

# --- 4. Release dates ---
import streamlit as st  # noqa: E402

GITHUB_DOWN = "simulated: GitHub API rate limit exceeded"


def swiid_date_down_get(url, *args, **kwargs):
    if url == ds.SWIID_COMMITS_URL:  # only SWIID's release date; its data still loads
        raise ConnectionError(GITHUB_DOWN)
    return fake_get(url, *args, **kwargs)


du.clear_disk_cache()
st.cache_data.clear()
with patch.object(du._SESSION, "get", side_effect=swiid_date_down_get):
    data, errors = du.load_data()
    assert errors == {} and "SWIID:GINI_DISP" in set(data["series_code"]), errors  # not a failed source
    updates = du.source_updates()
    assert updates["SWIID"] is None and updates == {**EXPECTED_RELEASES, "SWIID": None}, updates

    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file(_pathfix.APP_PATH, default_timeout=120)
    at.run()
    at.selectbox(key="trends_entity").set_value("USA").run()
    assert not at.exception, at.exception
    footers = [m.value for m in at.tabs[1].markdown if "Source:" in m.value]
    swiid = [f for f in footers if ds.SOURCES["SWIID"]["label"] in f]
    assert swiid and not any("Last updated" in f for f in swiid), swiid  # the chart, without a date
    assert any("World Development Indicators · Last updated" in f for f in footers)  # the others keep theirs
print("OK: a source without a release date loads, with no 'Last updated' in its footer")

calls = []
du.clear_disk_cache()
st.cache_data.clear()
with patch.object(du._SESSION, "get", side_effect=counting_get):
    du.load_data()
    assert du._UPDATES_CACHE_FILE.exists()
    # A cache written before the dates were kept: every data file is there and fresh, but no WHR date.
    on_disk = json.loads(du._UPDATES_CACHE_FILE.read_text(encoding="utf-8"))
    del on_disk["WHR"]
    du._UPDATES_CACHE_FILE.write_text(json.dumps(on_disk), encoding="utf-8")
    du.load_data.clear()
    n_before = len(calls)
    du.load_data()
    assert calls[n_before:] == [ds.WHR_URL], calls[n_before:]  # only that source is refetched
    du.source_updates.clear()
    assert du.source_updates()["WHR"] == ds.WHR_RELEASED
    assert "WHR" in json.loads(du._UPDATES_CACHE_FILE.read_text(encoding="utf-8"))  # healed on disk too
du.clear_disk_cache()
st.cache_data.clear()
print("OK: a cache without release dates self-heals on the next load")

# --- 5. A timed-out WDI request is retried ---
import requests  # noqa: E402

timed_out = []


def wdi_slow_once_get(url, params=None, timeout=None, **kwargs):
    """Every WDI series times out on its first request, then answers."""
    if "/indicator/" in url and url not in timed_out:
        timed_out.append(url)
        assert timeout == ds.WDI_TIMEOUT, timeout
        raise requests.exceptions.ReadTimeout("simulated: read timed out")
    return fake_get(url, params=params, timeout=timeout, **kwargs)


def wdi_always_slow_get(url, params=None, timeout=None, **kwargs):
    if "/indicator/" in url:
        timed_out.append(url)
        raise requests.exceptions.ReadTimeout("simulated: read timed out")
    return fake_get(url, params=params, timeout=timeout, **kwargs)


with patch.object(ds, "RETRY_WAIT", 0):
    table, _ = ds.fetch_wdi(type("S", (), {"get": staticmethod(wdi_slow_once_get)}))
    assert len(timed_out) == len(ds.WDI_SERIES), len(timed_out)  # each series failed once...
    assert set(table["series_code"]) == set(ds.series_of("WDI"))  # ...and still loaded
    timed_out.clear()
    try:
        ds.fetch_wdi(type("S", (), {"get": staticmethod(wdi_always_slow_get)}))
        raise AssertionError("fetch_wdi should fail when the API never answers")
    except requests.exceptions.ReadTimeout:
        pass
    # gives up after WDI_ATTEMPTS tries per series (other series may not have started)
    assert max(timed_out.count(u) for u in set(timed_out)) == ds.WDI_ATTEMPTS
print("OK: a timed-out World Bank request is retried, and gives up after WDI_ATTEMPTS")

print("\nALL SOURCE CHECKS PASSED")
