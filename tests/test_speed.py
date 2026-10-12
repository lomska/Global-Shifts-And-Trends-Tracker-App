"""Measure the wall-clock speedup from fetching the population data's series in parallel
(sources.fetch_population: one request per series, plus the last-estimate lookup), using a
mock that sleeps like a real network round-trip would."""
import _pathfix  # noqa: F401
import time

import sources as ds
from test_app2 import fake_get

LATENCY_S = 0.3  # simulate a ~300ms round trip per request, typical for a public API


class SlowSession:
    def get(self, url, *args, **kwargs):
        time.sleep(LATENCY_S)
        return fake_get(url, *args, **kwargs)


start = time.time()
table, _ = ds.fetch_population(SlowSession())
elapsed = time.time() - start
assert set(table["series_code"]) == set(ds.series_of(ds.POPULATION))

n_calls = len(ds.POP_SERIES) + 1
sequential_estimate = n_calls * LATENCY_S
print(f"{n_calls} API calls at ~{LATENCY_S*1000:.0f}ms each")
print(f"Sequential would take ~{sequential_estimate:.2f}s")
print(f"Parallel (actual) took {elapsed:.2f}s")
print(f"Speedup: {sequential_estimate / elapsed:.1f}x")
assert elapsed < sequential_estimate * 0.6, "Expected a substantial speedup from parallelizing"
print("\nOK: parallel fetch is meaningfully faster than sequential would be")
