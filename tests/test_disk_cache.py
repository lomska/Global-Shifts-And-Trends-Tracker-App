"""Verify the on-disk cache (one file per source, plus the country list) actually persists
across a fresh process (simulated here by clearing Streamlit's in-memory cache, which is
what happens for real when the app process restarts), that an expired source file is
refetched on its own, and that clear_disk_cache() invalidates everything."""
import _pathfix  # noqa: F401
import os
import time
from unittest.mock import patch

import data_utils as du
import sources as ds
from test_app2 import fake_get

du.clear_disk_cache()
assert not du._CACHE_DIR.exists(), "cache dir should be gone after clear_disk_cache()"

calls = []


def counting_fake_get(url, *args, **kwargs):
    calls.append(url)
    return fake_get(url, *args, **kwargs)


def clear_all_memory_caches():
    """A real process restart wipes every st.cache_data-backed function at once."""
    du.load_data.clear()
    du.load_countries.clear()


def load_all():
    data, errors = du.load_data()
    countries, country_errors = du.load_countries()
    assert errors == {} and country_errors == {}, (errors, country_errors)
    return data, countries


with patch.object(du._SESSION, "get", side_effect=counting_fake_get):
    # 1) Cold: no in-memory cache, no disk cache -> must hit the (fake) network.
    clear_all_memory_caches()
    data1, countries1 = load_all()
    n_first = len(calls)
    files = [du._source_cache_file(s) for s in ds.SOURCES] + [du._COUNTRIES_CACHE_FILE]
    assert all(f.exists() for f in files), [f.name for f in files if not f.exists()]
    print(f"OK: first load hit the network ({n_first} calls) and wrote one cache file per source + countries")

    # 2) Simulate a process restart: clear ONLY the in-memory caches (disk cache untouched).
    clear_all_memory_caches()
    data2, countries2 = load_all()
    assert len(calls) == n_first, f"second load should read the disk cache, not the network: {calls[n_first:]}"
    assert data1.shape == data2.shape and countries1.shape == countries2.shape
    print("OK: simulated process restart read from the on-disk cache, made zero network calls")

    # 3) An expired file (older than the TTL) is ignored and refetched -- only that source.
    old_time = time.time() - du.CACHE_TTL_SECONDS - 3600
    os.utime(du._source_cache_file(ds.POPULATION), (old_time, old_time))
    clear_all_memory_caches()
    load_all()
    refetched = calls[n_first:]
    assert refetched and all("/sources/40/" in u or u == ds.LAST_ESTIMATE_URL for u in refetched), refetched[:5]
    print(f"OK: an expired (>24h old) population cache was refetched ({len(refetched)} calls), the rest read from disk")

    # 4) clear_disk_cache() (what the Refresh-data button calls) forces everything back to the network.
    n_before = len(calls)
    clear_all_memory_caches()
    du.clear_disk_cache()
    load_all()
    assert len(calls) - n_before == n_first, "clear_disk_cache() should force a full refetch"
    print("OK: clear_disk_cache() (what the Refresh-data button calls) forces a real refetch")

du.clear_disk_cache()
print("\nALL DISK CACHE TESTS PASSED")
