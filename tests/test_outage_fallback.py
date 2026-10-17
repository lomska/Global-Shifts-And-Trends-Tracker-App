"""What happens when a source is down (2026-10-17): it is shown from its last saved copy, whatever its age,
instead of leaving its charts empty (du.stale_sources() lists it and the app says so at the top); "Refresh
data" (du.expire_disk_cache) expires the saved copies without deleting them, so an outage during a refresh
keeps them; and a source that is down fails fast: its first failed request stops the others (ds._fetch_all)
instead of every series running its own timeouts and retries."""
import _pathfix  # noqa: F401
import os
import threading
import time
from unittest.mock import patch

import requests
import streamlit as st
from streamlit.testing.v1 import AppTest

import data_utils as du
import sources as ds
from test_app2 import fake_get


def wdi_down_get(url, *args, **kwargs):
    if url.startswith(ds.WDI_URL.split("{")[0]):
        raise requests.exceptions.ConnectionError("simulated: WDI unreachable")
    return fake_get(url, *args, **kwargs)


def fresh_load():
    st.cache_data.clear()
    return du.load_data()


# --- 1. A source that is down is shown from its expired disk cache ---
du.clear_disk_cache()
with patch.object(du._SESSION, "get", side_effect=fake_get):
    data_ok, errors = fresh_load()
assert errors == {}, errors
wdi_rows = data_ok["series_code"].str.startswith("WB:").sum()
old_time = time.time() - du.CACHE_TTL_SECONDS - 3600  # well past the TTL
os.utime(du._source_cache_file("WDI"), (old_time, old_time))

with patch.object(du._SESSION, "get", side_effect=wdi_down_get):
    data, errors = fresh_load()
    assert errors == {}, errors  # not an error: shown from the saved copy
    assert data["series_code"].str.startswith("WB:").sum() == wdi_rows
    stale = du.stale_sources()
    assert set(stale) == {"WDI"}, stale
    saved, message = stale["WDI"]
    assert abs(saved.timestamp() - old_time) < 5 and "WDI unreachable" in message, stale
    assert du.source_updates()["WDI"] is not None  # its release date comes from disk too

    at = AppTest.from_file(_pathfix.APP_PATH, default_timeout=120)
    at.run()
    assert not at.exception, at.exception
    notes = [i.value for i in at.info if "copy saved earlier" in i.value]
    assert len(notes) == 1 and du.SOURCE_LABELS["WDI"] in notes[0], [i.value for i in at.info]
    assert not any("Couldn't load data from" in w.value for w in at.warning), [w.value for w in at.warning]
print("OK: a source that is down is shown from its saved copy, with a note naming it")

# --- 2. No saved copy: still an error, as before ---
du.clear_disk_cache()
with patch.object(du._SESSION, "get", side_effect=wdi_down_get):
    data, errors = fresh_load()
    assert set(errors) == {"WDI"} and du.stale_sources() == {}, errors
    assert not data["series_code"].str.startswith("WB:").any()
print("OK: a source that is down with nothing saved is an error, its charts empty")

# --- 3. "Refresh data" expires the cache but keeps it as the fallback ---
du.clear_disk_cache()
calls = []


def counting_get(url, *args, **kwargs):
    calls.append(url)
    return fake_get(url, *args, **kwargs)


with patch.object(du._SESSION, "get", side_effect=counting_get):
    fresh_load()
    n_first = len(calls)
    fresh_load()
    assert len(calls) == n_first  # fresh files: read from disk
    du.expire_disk_cache()
    assert du._source_cache_file("WDI").exists()  # kept...
    fresh_load()
    assert len(calls) == 2 * n_first, (n_first, len(calls))  # ...but every source refetched
    du.load_countries.clear()
    du.load_countries()
    assert any(u.endswith("/country") for u in calls[n_first:]), "the country list is refetched too"
du.expire_disk_cache()
with patch.object(du._SESSION, "get", side_effect=wdi_down_get):
    data, errors = fresh_load()
    assert errors == {} and set(du.stale_sources()) == {"WDI"}, errors
    assert data["series_code"].str.startswith("WB:").sum() == wdi_rows
print("OK: Refresh data refetches everything, and a source down during it keeps its saved copy")

# --- 4. A source that is down fails fast ---
requests_made, lock = [], threading.Lock()


def hanging_get(url, params=None, timeout=None, **kwargs):
    """Every WDI request 'times out' after a short delay (standing in for WDI_TIMEOUT)."""
    with lock:
        requests_made.append(url)
    time.sleep(0.2)
    raise requests.exceptions.ReadTimeout("simulated: read timed out")


session = type("S", (), {"get": staticmethod(hanging_get)})
with patch.object(ds, "RETRY_WAIT", 0.5):
    start = time.time()
    try:
        ds.fetch_wdi(session)
        raise AssertionError("fetch_wdi should fail when every request times out")
    except requests.exceptions.ReadTimeout:
        pass
    elapsed = time.time() - start
# One series' worst case is 3 tries (0.6 s) + waits of 0.5 and 1 s = 2.1 s; every series' worst case,
# 8 at a time, would be about four times that. Only the requests already in flight run.
n_series = len(ds.WDI_SERIES)
assert len(requests_made) < n_series * ds.WDI_ATTEMPTS / 2, (len(requests_made), n_series)
assert elapsed < 4, elapsed
print(f"OK: WDI down -> fails after {elapsed:.1f}s and {len(requests_made)} requests "
      f"(not {n_series * ds.WDI_ATTEMPTS})")

# A host that refuses connections isn't retried at all: the other series stop right after it.
requests_made.clear()


def refused_get(url, params=None, timeout=None, **kwargs):
    assert timeout[0] <= ds.CONNECT_TIMEOUT, timeout
    with lock:
        requests_made.append(url)
    time.sleep(0.05)
    raise requests.exceptions.ConnectionError("simulated: connection refused")


try:
    ds.fetch_population(type("S", (), {"get": staticmethod(refused_get)}))
    raise AssertionError("fetch_population should fail when the host refuses connections")
except requests.exceptions.ConnectionError:
    pass
assert len(requests_made) <= len(ds.POP_SERIES) + 1, len(requests_made)  # one per series at most (+ the lookup)
print("OK: population data down -> one request per series at most, no retries")

du.clear_disk_cache()
st.cache_data.clear()
print("\nALL OUTAGE FALLBACK TESTS PASSED")
