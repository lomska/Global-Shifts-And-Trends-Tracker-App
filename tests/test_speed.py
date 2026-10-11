"""Measure the wall-clock speedup from parallelizing the 10 API calls, using a
mock that sleeps like a real network round-trip would."""
import _pathfix  # noqa: F401
import time
from unittest.mock import patch

import data_utils as du
from test_app2 import fake_country_payload, fake_indicator_payload, FakeResponse

LATENCY_S = 0.3  # simulate a ~300ms round trip per request, typical for a public API


def slow_fake_get(url, params=None, timeout=None):
    time.sleep(LATENCY_S)
    params = params or {}
    if url.endswith("/v2/country"):
        return FakeResponse(fake_country_payload())
    series_code = url.split("/series/")[1].split("/time/")[0]
    page = int(params.get("page", 1))
    per_page = int(params.get("per_page", 32000))
    return FakeResponse(fake_indicator_payload(series_code, page, per_page))


with patch.object(du._SESSION, "get", side_effect=slow_fake_get):
    du.load_data.clear()  # bypass Streamlit's in-memory cache...
    du.clear_disk_cache()  # ...and the on-disk cache, so we measure the actual network-fetch path
    start = time.time()
    df, countries = du.load_data()
    elapsed = time.time() - start

n_calls = len(du.INDICATORS) + 1
sequential_estimate = n_calls * LATENCY_S
print(f"{n_calls} API calls at ~{LATENCY_S*1000:.0f}ms each")
print(f"Sequential would take ~{sequential_estimate:.2f}s")
print(f"Parallel (actual) took {elapsed:.2f}s")
print(f"Speedup: {sequential_estimate / elapsed:.1f}x")
assert elapsed < sequential_estimate * 0.6, "Expected a substantial speedup from parallelizing"
print("\nOK: parallel fetch is meaningfully faster than sequential would be")
