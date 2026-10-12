"""
What the app does when data sources can't be reached:

1. Everything unreachable: a visible on-page error instead of an uncaught exception or a blank page.
2. Only the World Bank population data (source 40) unreachable: like any failed source, the app keeps
   running on the others, with a warning naming it where its charts would be; Trends has no
   Demographics section, and Distributions opens on Economics / Real GDP growth (DEFAULT_DIST_VIEWS).
3. The country list unreachable (on its own: it is loaded separately from the data): a stale on-disk
   countries file is used if there is one, otherwise the minimal country_dict list (no regions or
   income groups), with a warning at the top of the page and without an exception.
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
import sources as ds
from test_app2 import fake_get

POP_LABEL = du.SOURCE_LABELS[ds.POPULATION]


def raise_conn_error(*args, **kwargs):
    raise requests.exceptions.ConnectionError("simulated: host unreachable (blocked egress)")


def is_population_url(url: str) -> bool:
    """Source 40's series and the population source's last-estimate lookup (not the WDI source's series)."""
    return "/sources/40/" in url or url == ds.LAST_ESTIMATE_URL


def is_countries_url(url: str) -> bool:
    return url.endswith("/v2/country")


def population_down_get(url, *args, **kwargs):
    if is_population_url(url):
        raise_conn_error()
    return fake_get(url, *args, **kwargs)


def countries_down_get(url, *args, **kwargs):
    if is_countries_url(url):
        raise_conn_error()
    return fake_get(url, *args, **kwargs)


def population_and_countries_down_get(url, *args, **kwargs):
    if is_population_url(url) or is_countries_url(url):
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
    # Named like any other failed source, at the top of the Trends tab (Demographics is skipped).
    assert any("Couldn't load data from" in w and POP_LABEL in w for w in warnings), warnings
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
    assert any("No country data loaded" in i and POP_LABEL in i for i in infos), infos
    # A country on the Trends tab (listed from the other sources' data).
    at.selectbox(key="trends_entity").set_value("NGA").run()
    assert not at.exception, at.exception


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

# --- 2. Population data unreachable, everything else fine ---
fresh_start()
with patch.object(du._SESSION, "get", side_effect=population_down_get):
    data, errors = du.load_data()
    assert set(errors) == {ds.POPULATION}, errors
    assert not data["series_code"].str.startswith("POP:").any()
    assert not du._source_cache_file(ds.POPULATION).exists()  # a failure isn't written...
    assert du._source_cache_file("WDI").exists()  # ...the sources that loaded are
    countries, country_errors = du.load_countries()
    assert country_errors == {} and du.has_country_groups(countries)  # the country list is separate
    assert du.series_split("IMF:NGDP_RPCH", data) == 2024.5  # other sources still split at their own year

    at = AppTest.from_file(_pathfix.APP_PATH, default_timeout=120)
    at.run()
    check_runs_without_population(at, regions_missing=False)
print("OK: population data unreachable -> the app runs on the other sources, with a warning")

# --- 3. The country list unreachable ---
# 3a. A stale (older than 24h) on-disk countries file is used.
fresh_start()
with patch.object(du._SESSION, "get", side_effect=fake_get):
    good_countries, _ = du.load_countries()
stale_time = time.time() - 3 * du.CACHE_TTL_SECONDS
os.utime(du._COUNTRIES_CACHE_FILE, (stale_time, stale_time))
st.cache_data.clear()
with patch.object(du._SESSION, "get", side_effect=countries_down_get):
    countries, errors = du.load_countries()
    assert set(errors) == {du.COUNTRIES_SOURCE}, errors
    pd.testing.assert_frame_equal(countries.reset_index(drop=True), good_countries.reset_index(drop=True))
    assert du.has_country_groups(countries)
    assert du.load_data()[1] == {}  # the data doesn't depend on the country list
print("OK: country list unreachable -> the stale disk cache is used")

# 3b. No cache at all, and the population data down too: the country_dict list, and the app still runs.
fresh_start()
with patch.object(du._SESSION, "get", side_effect=population_and_countries_down_get):
    countries, errors = du.load_countries()
    assert set(errors) == {du.COUNTRIES_SOURCE}, errors
    assert list(countries.columns) == du.COUNTRIES_COLUMNS and not du.has_country_groups(countries)
    assert {"USA", "NGA", "DEU"} <= set(du.real_country_codes(countries))
    assert "WLD" not in du.real_country_codes(countries)

    at = AppTest.from_file(_pathfix.APP_PATH, default_timeout=120)
    at.run()
    check_runs_without_population(at, regions_missing=True)
print("OK: no country list or cache -> country_dict's list, regions and income groups missing")


# --- 4. Population data and IMF both unreachable: Distributions opens on the next view ---
def population_and_imf_down_get(url, *args, **kwargs):
    if url.startswith(ds.IMF_SDMX_URL) or url.startswith(ds.IMF_DATAMAPPER_URL):
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
