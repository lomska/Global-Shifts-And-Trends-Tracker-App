"""
Verify the @st.cache_data layer on the pandas transform functions (trends_data,
country_indicator_wide, etc.) actually pays off end-to-end, at a
dataset size close to the real thing.

test_app2.py's fake API data only has 5 real countries + 12 aggregates (~14k rows
total) -- too small to show the effect, since everything is fast at that scale. The
real World Bank response has ~270 countries/aggregates (~220k rows), which is where
the default full-content DataFrame hash would have cost about as much as the
computation it was trying to save (see the benchmarking that motivated this change).
This test fakes a ~270-entity response and drives the actual Streamlit app through
two full reruns via AppTest -- the second rerun simulates the person moving a widget
in ONE tab, which (because st.tabs isn't lazy) re-executes both tabs' bodies again.
"""
import _pathfix  # noqa: F401
import random
import time
from unittest.mock import patch

import data_utils as du
import sources as ds
from test_app2 import fake_get as small_fake_get, fake_source_get

random.seed(0)

REGIONS = list(du.REGION_CODES.items())
INCOMES = list(du.INCOME_CODES.items())
N_COUNTRIES = 260
YEARS = list(range(1960, 2051))

country_records = []
for i in range(N_COUNTRIES):
    region_id, region_name = REGIONS[i % len(REGIONS)]
    income_id, income_name = INCOMES[i % len(INCOMES)]
    country_records.append({
        "id": f"C{i:03d}", "name": f"Country {i:03d}",
        "region": {"id": region_id, "value": region_name},
        "incomeLevel": {"id": income_id, "value": income_name},
    })
AGGREGATE_NAMES = {"WLD": "World", **dict(REGIONS), **dict(INCOMES)}
AGGREGATE_IDS = list(AGGREGATE_NAMES)
aggregate_records = [{"id": a, "name": AGGREGATE_NAMES[a]} for a in AGGREGATE_IDS]


def fake_country_payload():
    records = []
    for c in country_records:
        records.append({"id": c["id"], "iso2Code": c["id"][:2], "name": c["name"],
                         "region": c["region"], "incomeLevel": c["incomeLevel"]})
    for a in aggregate_records:
        records.append({"id": a["id"], "iso2Code": a["id"][:2], "name": a["name"],
                         "region": {"id": "NA", "value": "Aggregates"},
                         "incomeLevel": {"id": "NA", "value": "Aggregates"}})
    return [{"page": 1, "pages": 1, "per_page": 400, "total": len(records)}, records]


def base_value(series_code, year):
    t = (year - 1960) / 90
    if series_code == "SP.POP.TOTL":
        return 1e7 * (1 + 1.4 * t)
    if series_code == "SP.POP.GROW":
        return max(-1.0, 3.0 - 3.2 * t)
    if series_code == "SP.DYN.TFRT.IN":
        return max(1.0, 6.0 - 4.2 * t)
    if series_code == "SP.DYN.LE00.IN":
        return 50 + 28 * t
    if series_code == "SP.POP.65UP.TO.ZS":
        return 4 + 26 * t
    if series_code == "SM.POP.NETM":
        return random.uniform(-200000, 200000)
    return 0.0


def fake_indicator_payload(series_code, page, per_page):
    entity_ids = [c["id"] for c in country_records] + AGGREGATE_IDS
    entity_names = {c["id"]: c["name"] for c in country_records}
    entity_names.update(AGGREGATE_NAMES)
    data = []
    for eid in entity_ids:
        for y in YEARS:
            data.append({
                "variable": [
                    {"concept": "Country", "id": eid, "value": entity_names[eid]},
                    {"concept": "Time", "id": f"YR{y}", "value": str(y)},
                ],
                "value": base_value(series_code, y),
            })
    return {"pages": 1, "source": {"data": data}}


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def fake_get(url, params=None, timeout=None, **kwargs):
    params = params or {}
    if url.endswith("/v2/country"):
        return FakeResponse(fake_country_payload())
    if url == ds.LAST_ESTIMATE_URL:  # the population data's last estimate year
        return small_fake_get(url, params)
    other = fake_source_get(url, params)  # every other source: test_app2's small fakes
    if other is not None:
        return other
    series_code = url.split("/series/")[1].split("/time/")[0]
    page = int(params.get("page", 1))
    per_page = int(params.get("per_page", 32000))
    return FakeResponse(fake_indicator_payload(series_code, page, per_page))


with patch.object(du._SESSION, "get", side_effect=fake_get):
    du.clear_disk_cache()
    du.load_data.clear()
    du.load_countries.clear()

    start = time.time()
    data, errors = du.load_data()
    countries, _ = du.load_countries()
    assert errors == {}, errors
    print(f"Fetched fake dataset: {data.shape[0]:,} rows in {time.time()-start:.2f}s")

    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file(_pathfix.APP_PATH, default_timeout=120)

    start = time.time()
    at.run()
    cold_time = time.time() - start
    assert not at.exception, f"first run raised: {at.exception}"
    print(f"Cold run (all transform caches empty): {cold_time:.2f}s")

    # Simulate the person picking another entity in the Trends tab -- with st.tabs
    # not being lazy, this reruns the Distributions tab's body too, which is
    # exactly the case the transform caching targets.
    at.selectbox(key="trends_entity").set_value("C001")

    start = time.time()
    at.run()
    warm_time = time.time() - start
    assert not at.exception, f"second run raised: {at.exception}"
    print(f"Warm run (widget changed in Trends tab only, Distributions transforms cached): {warm_time:.2f}s")

    speedup = cold_time / warm_time
    print(f"Speedup from transform-level caching on the untouched tabs: {speedup:.2f}x")
    assert warm_time < cold_time, "the warm rerun (cache hits for untouched tabs) should be faster than the cold one"

print("\nOK: transform-level caching measurably speeds up reruns triggered by widgets in other tabs")
