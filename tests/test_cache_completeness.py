"""
Regression test for the "working-age chart is empty" bug: a disk cache written
by an OLDER version of the app (before POP:SP.POP.1564.TO.ZS was added to the
population series) can survive a redeploy on hosts where the .wb_data_cache
directory isn't wiped between deploys. Before the fix, the cache was trusted
blindly while fresh, so that old, incomplete cache would get served until the
24h TTL expired, with the new series' charts silently empty. This test writes
exactly that kind of stale-but-fresh, pre-upgrade cache directly to disk, then
checks that load_data() notices it's missing a series and refetches that source
(and only that source) instead of trusting it. The same check applies to every
source, since each has its own cache file (test_sources.py covers ND-GAIN's).
"""
import _pathfix  # noqa: F401
import json
from unittest.mock import patch

import data_utils as du
import sources as ds
from test_app2 import fake_get

du.clear_disk_cache()

calls = []


def counting_fake_get(url, *args, **kwargs):
    calls.append(url)
    return fake_get(url, *args, **kwargs)


def is_population_call(url):
    """Source 40's series and the last-estimate lookup: the population source's requests."""
    return "/sources/40/" in url or url == ds.LAST_ESTIMATE_URL


POP_CALLS = len(ds.POP_SERIES) + 1  # one request per series, plus the last-estimate lookup

with patch.object(du._SESSION, "get", side_effect=counting_fake_get):
    du.load_data.clear()
    data, errors = du.load_data()
    assert errors == {}, errors
    assert sum(map(is_population_call, calls)) == POP_CALLS, "sanity check: first load should hit the network"
    assert set(ds.series_of(ds.POPULATION)) <= set(data["series_code"].unique())

    # Simulate a pre-upgrade cache: drop the working-age share rows, then write that incomplete
    # table straight to disk (bypassing load_data() so its mtime looks fresh, exactly like a
    # cache directory that survived a redeploy untouched).
    pop = data[data["series_code"].str.startswith("POP:")]
    old_style = pop[pop["series_code"] != "POP:SP.POP.1564.TO.ZS"]
    assert set(old_style["series_code"]) < set(ds.series_of(ds.POPULATION)), "the fixture must be incomplete"
    du._write_parquet_atomic([(du._source_cache_file(ds.POPULATION), old_style)])

    # A fresh "process restart": in-memory caches cold, but the incomplete disk cache is
    # sitting there with a fresh mtime -- exactly the reported bug's starting condition.
    du.load_data.clear()
    n_before = len(calls)
    data2, _ = du.load_data()

    refetched = calls[n_before:]
    assert refetched and all(map(is_population_call, refetched)), (
        "load_data() should refetch the incomplete population cache, and only that source: " + str(refetched[:5])
    )
    assert len(refetched) == POP_CALLS, refetched
    assert set(du.SERIES) <= set(data2["series_code"].unique()), (
        "the recovered data should include every series, including working-age population"
    )
    print("OK: an incomplete (pre-upgrade) disk cache is detected and triggers a refetch of that source only")
    print("OK: the recovered data covers every series, including the ones added most recently")

    # Same self-heal for a cache written before the release dates were kept: complete data, no date.
    on_disk = json.loads(du._UPDATES_CACHE_FILE.read_text(encoding="utf-8"))
    assert ds.POPULATION in on_disk, on_disk
    del on_disk[ds.POPULATION]
    du._UPDATES_CACHE_FILE.write_text(json.dumps(on_disk), encoding="utf-8")
    du.load_data.clear()
    n_before = len(calls)
    du.load_data()
    assert calls[n_before:] and all(map(is_population_call, calls[n_before:])), "a cache without its release date was trusted"
    assert ds.POPULATION in json.loads(du._UPDATES_CACHE_FILE.read_text(encoding="utf-8"))
    n_before = len(calls)
    du.load_data.clear()
    du.load_data()  # now complete, dates included: read from disk
    assert len(calls) == n_before, calls[n_before:]
    print("OK: a disk cache without the release date is refetched once")

    # The country list's own self-heal: a file written before iso2_code (the flags) was added.
    countries, _ = du.load_countries()
    du._write_parquet_atomic([(du._COUNTRIES_CACHE_FILE, countries.drop(columns="iso2_code"))])
    du.load_countries.clear()
    n_before = len(calls)
    countries2, errors = du.load_countries()
    assert errors == {} and "iso2_code" in countries2 and calls[n_before:] == [f"{ds.WB_API_BASE}/country"]
    print("OK: a country list without a newer column is refetched")

du.clear_disk_cache()
print("\nALL CACHE COMPLETENESS TESTS PASSED")
