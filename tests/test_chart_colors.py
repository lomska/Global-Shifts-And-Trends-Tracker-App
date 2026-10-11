"""
Regression test: region names from country metadata must match REGION_COLOR_MAP's keys
(and app.REGION_SHORT_LABEL's), or the Distributions table's region pills silently lose
their color / short name. The real /country endpoint pads some region names with a
trailing space ("Sub-Saharan Africa "); du._clean_countries strips them, and the
test_app2 fixture keeps that trailing space on purpose so this test guards it.
"""
import _pathfix  # noqa: F401
from unittest.mock import patch

import data_utils as du
from test_app2 import fake_get

du.clear_disk_cache()

with patch.object(du._SESSION, "get", side_effect=fake_get):
    df, countries = du.load_data()

import app as app_mod

country_regions = set(countries["region"].dropna())
assert country_regions, "fixture should have countries with regions"
missing = country_regions - set(du.REGION_COLOR_MAP)
assert not missing, f"country-level region values not in REGION_COLOR_MAP: {missing}"
missing = country_regions - set(app_mod.REGION_SHORT_LABEL)
assert not missing, f"country-level region values not in REGION_SHORT_LABEL: {missing}"
print("OK: country-level region values all resolve to a real color and short label")

du.clear_disk_cache()
print("\nALL CHART COLOR TESTS PASSED")
