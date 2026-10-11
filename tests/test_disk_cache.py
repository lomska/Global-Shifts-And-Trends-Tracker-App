"""Verify the on-disk cache actually persists across a fresh process (simulated
here by clearing Streamlit's in-memory cache, which is what happens for real
when the app process restarts) and that clear_disk_cache() invalidates it."""
import _pathfix  # noqa: F401
import os
import time
from unittest.mock import patch

import data_utils as du
from test_app2 import fake_get

du.clear_disk_cache()
assert du._disk_cache_age_seconds() is None, "cache dir should be gone after clear_disk_cache()"

call_count = {"n": 0}


def counting_fake_get(*args, **kwargs):
    call_count["n"] += 1
    return fake_get(*args, **kwargs)


def clear_all_memory_caches():
    """A real process restart wipes every st.cache_data-backed function at once
    (load_data's own cache AND fetch_countries'/fetch_indicator's, which are
    separately decorated). Clearing only load_data would let those inner
    caches keep serving stale results and mask what the disk layer is doing."""
    du.load_data.clear()
    du.fetch_countries.clear()
    du.fetch_indicator.clear()


with patch.object(du._SESSION, "get", side_effect=counting_fake_get):
    # 1) Cold: no in-memory cache, no disk cache -> must hit the (fake) network.
    clear_all_memory_caches()
    df1, countries1 = du.load_data()
    calls_after_first = call_count["n"]
    assert calls_after_first == len(du.INDICATORS) + 1, f"expected {len(du.INDICATORS)+1} calls, got {calls_after_first}"
    assert du._DATA_CACHE_FILE.exists() and du._COUNTRIES_CACHE_FILE.exists(), "disk cache files should now exist"
    print(f"OK: first load hit the network ({calls_after_first} calls) and wrote the disk cache")

    # 2) Simulate a process restart: clear ONLY the in-memory caches (disk cache untouched).
    #    A real restart doesn't call this -- the in-memory cache just doesn't exist yet in a
    #    fresh process -- but clearing it here reproduces the same "no in-memory cache" state.
    clear_all_memory_caches()
    df2, countries2 = du.load_data()
    assert call_count["n"] == calls_after_first, "second load should NOT have hit the network -- should have read the disk cache"
    assert df1.shape == df2.shape and countries1.shape == countries2.shape
    print("OK: simulated process restart read from the on-disk cache, made zero network calls")

    # 3) A stale cache (older than the TTL) should be ignored and refetched.
    old_time = time.time() - du.CACHE_TTL_SECONDS - 3600
    os.utime(du._DATA_CACHE_FILE, (old_time, old_time))
    os.utime(du._COUNTRIES_CACHE_FILE, (old_time, old_time))
    clear_all_memory_caches()
    df3, countries3 = du.load_data()
    assert call_count["n"] == calls_after_first * 2, "an expired disk cache should trigger a fresh network fetch"
    print("OK: an expired (>24h old) disk cache was correctly ignored and refetched")

    # 4) clear_disk_cache() should force the next load back to the network even if it'd
    #    otherwise still be fresh.
    clear_all_memory_caches()
    du.clear_disk_cache()
    df4, countries4 = du.load_data()
    assert call_count["n"] == calls_after_first * 3, "clear_disk_cache() should force a network refetch"
    print("OK: clear_disk_cache() (what the Refresh-data button calls) forces a real refetch")

du.clear_disk_cache()
print("\nALL DISK CACHE TESTS PASSED")
