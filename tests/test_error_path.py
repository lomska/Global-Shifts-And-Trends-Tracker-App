"""
What the app does when data sources can't be reached:

1. Everything unreachable: a visible on-page error instead of an uncaught exception or a blank page.
2. Only the World Bank population data (source 40) unreachable: the app keeps running on the other
   sources, with a warning naming the population data; Trends has no Demographics section, and
   Distributions opens on Economics / Real GDP growth (DEFAULT_DIST_VIEWS). The forecast split falls
   back to the date rule when its WDI lookup fails too.
3. The country list unreachable as well: a stale on-disk countries cache is used if there is one,
   otherwise the minimal country_dict list (no regions or income groups), without an exception.
4. The population data and IMF unreachable: Distributions opens on the next view with data,
   Labour market / Youth NEET rate.
"""
import _pathfix  # noqa: F401
import os
import time
from unittest.mock import patch

import pandas as pd
import requests
import streamlit as st
from streamlit.testing.v1 import AppTest

import data_utils as du
import extra_sources as xs
from test_app2 import fake_get


def raise_conn_error(*args, **kwargs):
    raise requests.exceptions.ConnectionError("simulated: host unreachable (blocked egress)")


def is_population_url(url: str) -> bool:
    """Source 40's indicators and the forecast split's WDI lookup (not the WDI extra-source series)."""
    return "/sources/40/" in url or url.endswith(f"/country/WLD/indicator/{du.ESTIMATES_SERIES}")


def population_down_get(url, *args, **kwargs):
    if is_population_url(url):
        raise_conn_error()
    return fake_get(url, *args, **kwargs)


def population_and_countries_down_get(url, *args, **kwargs):
    if is_population_url(url) or url.endswith("/v2/country"):
        raise_conn_error()
    return fake_get(url, *args, **kwargs)


def fresh_start():
    """A process start with no cache: memory and disk."""
    du.clear_disk_cache()
    st.cache_data.clear()


def check_runs_without_population(at: AppTest, regions_missing: bool):
    assert not at.exception, at.exception
    assert not at.error, [e.value for e in at.error]
    warnings = [w.value for w in at.warning]
    assert any("Couldn't load the population data" in w for w in warnings), warnings
    assert any("region and income-group information is missing" in w for w in warnings) == regions_missing, warnings
    headers = [h.value for h in at.subheader]
    assert "Demographics" not in headers and "Economics" in headers, headers  # Trends rendered, minus Demographics
    assert at.segmented_control(key="dist_section").value == "Economics"  # Distributions rendered
    assert at.selectbox(key="dist_indicator_Economics").value == "Real GDP growth"
    assert len(at.dataframe) == 1  # the Country Details table, with whatever region data there is
    # A Demographics indicator: the usual "no data" message, naming the population source.
    at.segmented_control(key="dist_section").set_value("Demographics").run()
    assert not at.exception, at.exception
    infos = [i.value for i in at.info]
    assert any("No country data loaded" in i and du_pop_name() in i for i in infos), infos
    # A country on the Trends tab (listed from the extra sources' data).
    at.selectbox(key="trends_entity").set_value("NGA").run()
    assert not at.exception, at.exception


def du_pop_name():
    import app
    return app.POP_SOURCE


# --- 1. Everything unreachable ---
fresh_start()
with patch.object(du._SESSION, "get", side_effect=raise_conn_error):
    at = AppTest.from_file(_pathfix.APP_PATH, default_timeout=60)
    at.run()
    print("exception:", at.exception)
    print("errors on page:", [e.value for e in at.error])
    assert not at.exception, "App should NOT raise an uncaught exception on network failure"
    assert len(at.error) > 0, "App should show a visible st.error on network failure"
    print("OK: network failure shows a visible error instead of crashing/blank")

# --- 2. Population data unreachable, the extra sources fine ---
fresh_start()
with patch.object(du._SESSION, "get", side_effect=population_down_get):
    df, countries, errors = du.load_population_data()
    assert set(errors) == {du.POPULATION_SOURCE}, errors
    assert df.empty and list(df.columns) == du.POPULATION_COLUMNS
    assert du.has_country_groups(countries)  # the country list itself loaded
    assert du._COUNTRIES_CACHE_FILE.exists() and not du._DATA_CACHE_FILE.exists()  # a failure isn't written
    assert du.forecast_start() == du._compute_forecast_start()  # WDI unreachable: the date rule
    try:
        du.load_data()
        raise AssertionError("load_data() should raise when the population data fails")
    except du.DataFetchError:
        pass

    at = AppTest.from_file(_pathfix.APP_PATH, default_timeout=120)
    at.run()
    check_runs_without_population(at, regions_missing=False)
print("OK: population data unreachable -> the app runs on the other sources, with a warning")

# --- 3. The country list unreachable too ---
# 3a. A stale (older than 24h) on-disk countries cache is used.
fresh_start()
with patch.object(du._SESSION, "get", side_effect=fake_get):
    _, good_countries, _ = du.load_population_data()
stale_time = time.time() - 3 * du.CACHE_TTL_SECONDS
for f in (du._DATA_CACHE_FILE, du._COUNTRIES_CACHE_FILE):
    os.utime(f, (stale_time, stale_time))
st.cache_data.clear()
with patch.object(du._SESSION, "get", side_effect=population_and_countries_down_get):
    df, countries, errors = du.load_population_data()
    assert set(errors) == {du.POPULATION_SOURCE, du.COUNTRIES_SOURCE}, errors
    pd.testing.assert_frame_equal(countries.reset_index(drop=True), good_countries.reset_index(drop=True))
    assert du.has_country_groups(countries)
print("OK: country list unreachable -> the stale disk cache is used")

# 3b. No cache at all: the country_dict list, and the app still runs.
fresh_start()
with patch.object(du._SESSION, "get", side_effect=population_and_countries_down_get):
    df, countries, errors = du.load_population_data()
    assert set(errors) == {du.POPULATION_SOURCE, du.COUNTRIES_SOURCE}, errors
    assert list(countries.columns) == du.COUNTRIES_COLUMNS and not du.has_country_groups(countries)
    assert {"USA", "NGA", "DEU"} <= set(du.real_country_codes(countries))
    assert "WLD" not in du.real_country_codes(countries)

    at = AppTest.from_file(_pathfix.APP_PATH, default_timeout=120)
    at.run()
    check_runs_without_population(at, regions_missing=True)
print("OK: no country list or cache -> country_dict's list, regions and income groups missing")

# --- 4. Population data and IMF both unreachable: Distributions opens on the next view ---
def population_and_imf_down_get(url, *args, **kwargs):
    if url.startswith(xs.IMF_SDMX_URL) or url.startswith(xs.IMF_DATAMAPPER_URL):
        raise_conn_error()
    return population_down_get(url, *args, **kwargs)


fresh_start()
with patch.object(du._SESSION, "get", side_effect=population_and_imf_down_get):
    at = AppTest.from_file(_pathfix.APP_PATH, default_timeout=120)
    at.run()
    assert not at.exception, at.exception
    assert not at.error, [e.value for e in at.error]
    assert at.segmented_control(key="dist_section").value == "Labour market"
    assert at.selectbox(key="dist_indicator_Labour market").value == "Youth NEET rate"
print("OK: population data and IMF unreachable -> Distributions opens on Labour market / Youth NEET rate")

du.clear_disk_cache()
print("\nALL ERROR PATH CHECKS PASSED")
