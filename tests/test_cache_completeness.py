"""
Regression test for the "working-age chart is empty" bug: a disk cache written
by an OLDER version of the app (before SP.POP.1564.TO.ZS was added to
INDICATORS) can survive a redeploy on hosts where the .wb_data_cache
directory isn't wiped between deploys. Before the fix, _read_disk_cache()
trusted any fresh-enough cache blindly, so that old, incomplete cache would
get served forever (until the 24h TTL expired) with the new indicators'
charts silently empty. This test writes exactly that kind of stale-but-fresh,
pre-upgrade cache directly to disk, then checks that load_data() notices it's
missing an indicator and refetches instead of trusting it.
"""
import _pathfix  # noqa: F401
from unittest.mock import patch

import data_utils as du
from test_app2 import fake_get

du.clear_disk_cache()

call_count = {"n": 0}


def counting_fake_get(*args, **kwargs):
    call_count["n"] += 1
    return fake_get(*args, **kwargs)


with patch.object(du._SESSION, "get", side_effect=counting_fake_get):
    du.load_data.clear()
    du.fetch_countries.clear()
    du.fetch_indicator.clear()

    df, countries = du.load_data()
    assert call_count["n"] == len(du.INDICATORS) + 1, "sanity check: first load should hit the network"
    assert set(du.INDICATORS) <= set(df["series_code"].unique())

    # Simulate a pre-upgrade cache: drop the working-age share rows, then write that
    # incomplete df straight to disk (bypassing load_data() so its mtime looks fresh,
    # exactly like a cache directory that survived a redeploy untouched).
    old_style_df = df[df["series_code"] != "SP.POP.1564.TO.ZS"].copy()
    assert set(old_style_df["series_code"].unique()) < set(du.INDICATORS), "the stale fixture must actually be incomplete"
    du._write_disk_cache(old_style_df, countries)

    # A fresh "process restart": in-memory caches cold, but the incomplete disk cache is
    # sitting there with a fresh mtime -- exactly the reported bug's starting condition.
    du.load_data.clear()
    du.fetch_countries.clear()
    du.fetch_indicator.clear()
    calls_before = call_count["n"]

    df2, countries2 = du.load_data()

    assert call_count["n"] > calls_before, (
        "load_data() trusted the incomplete on-disk cache instead of noticing it was missing "
        "an indicator and refetching -- this is the bug that left the working-age chart empty"
    )
    assert set(du.INDICATORS) <= set(df2["series_code"].unique()), (
        "the recovered dataset should include every current indicator, including working-age population"
    )
    print("OK: an incomplete (pre-upgrade) disk cache is detected and triggers a real refetch")
    print("OK: the recovered dataset covers every indicator, including the ones added most recently")

    # Same self-heal for a cache written before the release dates were kept: complete data, no date.
    import json
    on_disk = json.loads(du._UPDATES_CACHE_FILE.read_text(encoding="utf-8"))
    assert du.POPULATION_SOURCE in on_disk, on_disk
    del on_disk[du.POPULATION_SOURCE]
    du._UPDATES_CACHE_FILE.write_text(json.dumps(on_disk), encoding="utf-8")
    du.load_data.clear()
    du.fetch_countries.clear()
    du.fetch_indicator.clear()
    calls_before = call_count["n"]
    du.load_data()
    assert call_count["n"] > calls_before, "a cache without the population release date was trusted"
    assert du.POPULATION_SOURCE in json.loads(du._UPDATES_CACHE_FILE.read_text(encoding="utf-8"))
    calls_before = call_count["n"]
    du.load_data.clear()
    du.load_data()  # now complete, dates included: read from disk
    assert call_count["n"] == calls_before
    print("OK: a disk cache without the release date is refetched once")

du.clear_disk_cache()
print("\nALL CACHE COMPLETENESS TESTS PASSED")
