"""
Smoke test for the population Streamlit app (Trends + Distributions tabs), run with a mocked World Bank API
(the endpoint shapes here were verified separately against the live API).

Run directly: `python tests/test_app2.py` from the project root, or `python
test_app2.py` from inside tests/ -- either works. Several other tests in this folder
import fixtures from this file (fake_get, etc.), so this one
has no dependency on the others.
"""
from __future__ import annotations

import _pathfix  # noqa: F401  -- sets up sys.path so `import data_utils`/`import app` work
import random
from unittest.mock import patch

import data_utils as du

random.seed(0)

COUNTRIES = [
    {"id": "USA", "name": "United States", "region": {"id": "NAC", "value": "North America"},
     "incomeLevel": {"id": "HIC", "value": "High income"}},
    {"id": "CHN", "name": "China", "region": {"id": "EAS", "value": "East Asia & Pacific"},
     "incomeLevel": {"id": "UMC", "value": "Upper middle income"}},
    # Trailing space on purpose: the real /country endpoint returns it (see du._clean_countries).
    {"id": "NGA", "name": "Nigeria", "region": {"id": "SSF", "value": "Sub-Saharan Africa "},
     "incomeLevel": {"id": "LMC", "value": "Lower middle income"}},
    {"id": "IND", "name": "India", "region": {"id": "SAS", "value": "South Asia"},
     "incomeLevel": {"id": "LMC", "value": "Lower middle income"}},
    {"id": "UKR", "name": "Ukraine", "region": {"id": "ECS", "value": "Europe & Central Asia"},
     "incomeLevel": {"id": "UMC", "value": "Upper middle income"}},
]
AGGREGATES = [
    {"id": "WLD", "name": "World"},
    {"id": "EAS", "name": "East Asia & Pacific"},
    {"id": "ECS", "name": "Europe & Central Asia"},
    {"id": "LCN", "name": "Latin America & Caribbean"},
    {"id": "MEA", "name": "Middle East, North Africa, Afghanistan & Pakistan"},  # current World Bank name
    {"id": "NAC", "name": "North America"},
    {"id": "SAS", "name": "South Asia"},
    {"id": "SSF", "name": "Sub-Saharan Africa"},
    {"id": "HIC", "name": "High income"},
    {"id": "UMC", "name": "Upper middle income"},
    {"id": "LMC", "name": "Lower middle income"},
    {"id": "LIC", "name": "Low income"},
]

YEARS = list(range(1960, 2051))


def fake_country_payload():
    records = []
    for c in COUNTRIES:
        records.append({
            "id": c["id"], "iso2Code": c["id"][:2], "name": c["name"],
            "region": {"id": c["region"]["id"], "value": c["region"]["value"]},
            "incomeLevel": {"id": c["incomeLevel"]["id"], "value": c["incomeLevel"]["value"]},
        })
    for a in AGGREGATES:
        records.append({
            "id": a["id"], "iso2Code": a["id"][:2], "name": a["name"],
            "region": {"id": "NA", "value": "Aggregates"},
            "incomeLevel": {"id": "NA", "value": "Aggregates"},
        })
    return [{"page": 1, "pages": 1, "per_page": 400, "total": len(records)}, records]


def base_value(series_code, entity_id, year):
    t = (year - 1960) / 90
    if series_code == "SP.POP.TOTL":
        scale = {"WLD": 3e9, "USA": 1.8e8, "CHN": 6.6e8, "NGA": 4.5e7, "IND": 4.5e8, "UKR": 4e7,
                 "EAS": 1e9, "ECS": 6e8, "LCN": 2e8, "MEA": 1e8, "NAC": 2e8, "SAS": 5e8, "SSF": 2e8,
                 "HIC": 1e9, "UMC": 1e9, "LMC": 1e9, "LIC": 2e8}.get(entity_id, 1e7)
        if entity_id in ("UKR", "ECS") and year >= 2000:
            decline_t = (year - 2000) / 50
            return scale * (1 + 0.4 * t) * (1 - 0.5 * decline_t)
        return scale * (1 + 1.4 * t)
    if series_code == "SP.POP.GROW":
        return max(-1.0, 3.0 - 3.2 * t + random.uniform(-0.1, 0.1))
    if series_code == "SP.DYN.TFRT.IN":
        return max(1.0, 6.0 - 4.2 * t)
    if series_code == "SP.DYN.LE00.IN":
        return 50 + 28 * t
    if series_code == "SP.POP.0014.TO.ZS":
        return 38 - 21 * t
    if series_code == "SP.POP.65UP.TO.ZS":
        return 4 + 26 * t
    if series_code == "SP.POP.1564.TO.ZS":
        return 62 - 5 * t
    if series_code == "SP.DYN.CBRT.IN":
        return 35 - 20 * t
    if series_code == "SP.DYN.CDRT.IN":
        return 15 - 7 * t
    if series_code == "SH.DYN.MORT":
        return None if year > 2024 else 200 - 160 * t  # history only, like the real series
    if series_code == "SP.POP.DPND":
        return 75 - 20 * t
    if series_code == "SP.POP.DPND.YG":
        return 68 - 38 * t
    if series_code == "SP.POP.DPND.OL":
        return 7 + 18 * t
    if series_code in ("SP.DYN.LE00.FE.IN", "SP.DYN.LE00.MA.IN"):
        return 50 + 28 * t + (2.5 if series_code.endswith("FE.IN") else -2.5)
    if series_code == "SM.POP.NETM":
        return random.uniform(-200000, 200000)
    return random.uniform(0, 100)


def fake_indicator_payload(series_code, page, per_page):
    entities = [(c["id"], c["name"]) for c in COUNTRIES] + [(a["id"], a["name"]) for a in AGGREGATES]
    all_rows = []
    for eid, ename in entities:
        for y in YEARS:
            value = base_value(series_code, eid, y)
            all_rows.append({
                "variable": [
                    {"concept": "Country", "id": eid, "value": ename},
                    {"concept": "Series", "id": series_code, "value": ds.POP_SERIES.get(series_code, series_code)},
                    {"concept": "Time", "id": f"YR{y}", "value": str(y)},
                ],
                "value": None if value is None else round(value, 4),  # the real API sends null for no data
            })
    total = len(all_rows)
    start = (page - 1) * per_page
    chunk = all_rows[start:start + per_page]
    pages = max(1, -(-total // per_page))
    return {"page": page, "pages": pages, "per_page": per_page, "total": total, "lastupdated": FAKE_POP_RELEASE,
            "source": {"id": "40", "name": "Population estimates and projections", "data": chunk}}


class FakeResponse:
    def __init__(self, payload=None, content: bytes | None = None):
        self._payload = payload
        self.content = content if content is not None else b""
        self.text = self.content.decode("utf-8", errors="replace")

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def fake_get(url, params=None, timeout=None, **kwargs):
    params = params or {}
    if url.endswith("/v2/country"):
        return FakeResponse(fake_country_payload())
    if "/sources/40/country/all/series/" in url:
        series_code = url.split("/series/")[1].split("/time/")[0]
        page = int(params.get("page", 1))
        per_page = int(params.get("per_page", 32000))
        return FakeResponse(fake_indicator_payload(series_code, page, per_page))
    if url == ds.LAST_ESTIMATE_URL:  # ds.last_estimate_year's WDI lookup
        return FakeResponse(fake_wdi_last_year_payload(FAKE_LAST_ESTIMATE_YEAR))
    other = fake_source_get(url, params)
    if other is not None:
        return other
    raise AssertionError(f"Unexpected URL in test: {url}")


# --------------------------------------------------------------------------
# Fakes for the other sources (sources.py), in each source's real layout (checked
# against the live sources): WDI JSON, IMF SDMX CSV, ND-GAIN zip, WHR Excel, Harvard Dataverse (ECI), UNDP Latin-1 CSV, ILOSTAT CSV, SWIID CSV, PIP JSON.
# --------------------------------------------------------------------------

import datetime as dt  # noqa: E402
import functools  # noqa: E402
import io  # noqa: E402
import math  # noqa: E402
import zipfile  # noqa: E402

import pandas as pd  # noqa: E402

import sources as ds  # noqa: E402

COUNTRY_ISO3 = [c["id"] for c in COUNTRIES]  # USA, CHN, NGA, IND, UKR

# Release dates, in each publisher's own format (see the fakes below); a different month for each.
FAKE_POP_RELEASE = "2026-07-01"  # the API's "lastupdated"
FAKE_WDI_RELEASE = "2026-09-15"
FAKE_IMF_PUBLICATION = "2025-10-14T13:00:00Z"
FAKE_ECI_RELEASE = "2026-02-08T19:59:09Z"
FAKE_ILO_TOC = {"LAP_2GDP_NOC_RT_A": "20/03/2026 12:54:04", "EIP_2EET_SEX_RT_A": "02/12/2025 10:34:13",
                "SDG_0111_SEX_AGE_RT_A": "05/10/2026 08:00:00"}  # day first; the last one isn't fetched
FAKE_SWIID_COMMIT = "2026-01-08T15:45:34Z"
FAKE_PIP_VERSIONS = ["20261001_2017_01_02_PROD",  # a newer release in 2017 PPP: not the data's
                     "20260922_2021_01_02_PROD", "20260324_2021_01_02_PROD"]
# What du.source_updates() should return for these fakes (ND-GAIN, WHR, UNDP: stored constants).
EXPECTED_RELEASES = {du.POPULATION_SOURCE: dt.date(2026, 7, 1), "WDI": dt.date(2026, 9, 15),
                     "IMF": dt.date(2025, 10, 14), "NDGAIN": ds.NDGAIN_RELEASED, "WHR": ds.WHR_RELEASED,
                     "ECI": dt.date(2026, 2, 8), "UNDP": ds.UNDP_RELEASED, "ILO": dt.date(2026, 3, 20),
                     "SWIID": dt.date(2026, 1, 8), "PIP": dt.date(2026, 9, 22)}
COUNTRY_NAMES = {c["id"]: c["name"] for c in COUNTRIES}
# COUNTRY_UPDATE_DATE lags the edition, as in the live data: projections start in the publication
# year (FAKE_IMF_PUBLICATION, 2025), not 2024 (see ds._imf_projection_start).
IMF_UPDATE_DATE = "9/19/2024"


def _xvalue(i, year, lo=0.0, hi=100.0):
    return round(lo + (hi - lo) * (((i * 37 + year * 13) % 100) / 100), 4)


def fake_wdi_payload(code):
    # Countries by ISO3, World + a region by ISO3, an income group with an empty ISO3 (as the real API),
    # an aggregate the dictionary drops (Arab World), and a null value (the API sends every year).
    entities = [(iso, iso[:2], COUNTRY_NAMES[iso]) for iso in COUNTRY_ISO3]
    entities += [("WLD", "1W", "World"), ("SSF", "ZG", "Sub-Saharan Africa"), ("", "XD", "High income"),
                 ("ARB", "1A", "Arab World")]
    recs = []
    for i, (iso3, cid, name) in enumerate(entities):
        for y in range(1990, 2025):
            recs.append({"indicator": {"id": code, "value": code}, "country": {"id": cid, "value": name},
                         "countryiso3code": iso3, "date": str(y),
                         "value": None if y == 1990 else _xvalue(i, y, 0.5, 30)})
    return [{"page": 1, "pages": 1, "per_page": 20000, "total": len(recs), "sourceid": "2",
             "lastupdated": FAKE_WDI_RELEASE}, recs]


@functools.lru_cache(maxsize=None)
def fake_imf_csv() -> bytes:
    rows = []
    for i, c in enumerate(COUNTRY_ISO3 + ["G001", "G110"]):  # G001 = World, G110 = an IMF group (dropped)
        for ind in ds.IMF_SERIES:
            for y in range(1980, 2031):
                rows.append({"STRUCTURE[;]": "dataflow", "COUNTRY": c, "INDICATOR": ind, "FREQUENCY": "A",
                             "TIME_PERIOD": y, "OBS_VALUE": _xvalue(i, y, -5, 10), "UNIT": "PT",
                             "COUNTRY_UPDATE_DATE": IMF_UPDATE_DATE})
    return pd.DataFrame(rows).to_csv(index=False).encode()


def fake_imf_attributes_csv() -> bytes:
    """ds._imf_publication_date's request: one series with every attribute, PUBLICATION_DATE among them."""
    return pd.DataFrame([{"COUNTRY": "G001", "INDICATOR": "NGDP_RPCH", "TIME_PERIOD": y, "OBS_VALUE": 3.0,
                          "COUNTRY_UPDATE_DATE": IMF_UPDATE_DATE, "PUBLICATION_DATE": FAKE_IMF_PUBLICATION}
                         for y in (2025, 2026)]).to_csv(index=False).encode()


def _excel(sheets: dict[str, pd.DataFrame]) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        for name, frame in sheets.items():
            frame.to_excel(writer, sheet_name=name, index=False)
    return buf.getvalue()


@functools.lru_cache(maxsize=None)
def fake_ndgain_zip() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for member in ds.NDGAIN_SERIES:
            wide = pd.DataFrame([{"ISO3": c, "Name": COUNTRY_NAMES[c],
                                  **{str(y): _xvalue(i, y, 0.2, 0.8) for y in range(1995, 2025)}}
                                 for i, c in enumerate(COUNTRY_ISO3)])
            zf.writestr(f"resources 2/{member}", wide.to_csv(index=False))
            # trends/<name>.csv: same file name, different layout -- must not be picked
            name = member.split("/")[1]
            zf.writestr(f"resources 2/trends/{name}", "ISO3,Name,Value,sign\nUSA,United States,0.1,1\n")
    return buf.getvalue()


# Names as the name-matched sources spell them (checked against the live files).
SWIID_NAMES = {**COUNTRY_NAMES, "USA": "United States"}


@functools.lru_cache(maxsize=None)
def fake_whr_xlsx() -> bytes:
    rows = [{"Year": y, "Rank": 1, "Country name": COUNTRY_NAMES.get(c, "Somaliland Region"),
             "Life evaluation (3-year average)": _xvalue(i, y, 3, 8), "Lower whisker": 1.0, "Upper whisker": 9.0}
            for i, c in enumerate(COUNTRY_ISO3 + ["SOM_R"]) for y in range(2011, 2026)]
    return _excel({"Sheet1": pd.DataFrame(rows)})


FAKE_ECI_FILE_ID = 13439575


def fake_eci_meta() -> dict:
    files = [{"dataFile": {"id": 13439574, "filename": "rankings_data_dictionary.tab",
                           "originalFileName": "rankings_data_dictionary.csv"}},
             {"dataFile": {"id": FAKE_ECI_FILE_ID, "filename": "growth_proj_eci_rankings.tab",
                           "originalFileName": "growth_proj_eci_rankings.csv"}}]
    return {"status": "OK", "data": {"latestVersion": {"files": files, "releaseTime": FAKE_ECI_RELEASE}}}


@functools.lru_cache(maxsize=None)
def fake_eci_csv() -> bytes:
    rows = [{"country_id": i, "country_iso3_code": c, "year": y, "growth_proj": 3.0, "in_rankings": True,
             "eci_sitc": _xvalue(i, y, -2, 2), "eci_rank_sitc": i + 1, "eci_hs92": 0.5, "eci_rank_hs92": i + 1}
            for i, c in enumerate(COUNTRY_ISO3) for y in range(1995, 2025)]
    return pd.DataFrame(rows).to_csv(index=False).encode()


@functools.lru_cache(maxsize=None)
def fake_undp_csv() -> bytes:
    entities = [(c, COUNTRY_NAMES[c]) for c in COUNTRY_ISO3] + [("CIV", "Côte d'Ivoire"),
                                                           ("ZZA.VHHD", "Very high human development")]
    rows = [{"iso3": c, "country": name, "hdicode": "High", "hdi_2023": 0.7,
             **{f"mys_{y}": _xvalue(i, y, 1, 14) for y in range(1990, 2024)}, "mys_f_2023": 1.0,
             **{f"eys_{y}": _xvalue(i, y, 5, 18) for y in range(1990, 2024)}, "eys_f_2023": 1.0}
            for i, (c, name) in enumerate(entities)]
    return pd.DataFrame(rows).to_csv(index=False).encode("latin-1")  # like the real file: not UTF-8


@functools.lru_cache(maxsize=None)
def fake_ilo_csv(ind_id: str) -> bytes:
    rows = []
    for i, c in enumerate(COUNTRY_ISO3 + ["X01"]):  # X01: an ILO regional group, dropped
        for y in range(2004, 2028):
            base = {"ref_area": c, "source": "XA:2198", "indicator": ind_id[:-2], "time": y, "obs_status": ""}
            if ind_id.startswith("EIP"):  # by sex: only the total is kept
                rows += [{**base, "sex": s, "obs_value": _xvalue(i, y, 5, 40) + k}
                         for k, s in enumerate(["SEX_T", "SEX_M", "SEX_F"])]
            else:
                rows.append({**base, "obs_value": _xvalue(i, y, 30, 70)})
    return pd.DataFrame(rows).to_csv(index=False).encode()


@functools.lru_cache(maxsize=None)
def fake_swiid_csv() -> bytes:
    rows = [{"country": SWIID_NAMES.get(c, "Soviet Union"), "year": y, "gini_disp": _xvalue(i, y, 20, 60),
             "gini_disp_se": 1.0, "gini_mkt": 45.0}
            for i, c in enumerate(COUNTRY_ISO3 + ["SUN"]) for y in range(1960, 2025)]
    return pd.DataFrame(rows).to_csv(index=False).encode()


PIP_NOWCAST_FROM = 2024


def fake_pip_payload() -> list[dict]:
    rows = []
    for i, c in enumerate(COUNTRY_ISO3):
        for y in range(1981, 2027):
            row = {"country_code": c, "country_name": COUNTRY_NAMES[c], "reporting_year": y,
                   "reporting_level": "national", "welfare_type": "consumption",
                   "headcount": _xvalue(i, y, 0, 0.6), "median": _xvalue(i, y, 1, 60),
                   "estimation_type": "survey" if y % 3 == 0 else "interpolation",
                   # Nowcasts from 2024: a year before the population data's and IMF's projections
                   # (both from 2025 here), so a year can be observed on one and projected on the other.
                   "estimate_type": "nowcast" if y >= PIP_NOWCAST_FROM else "actual"}
            rows.append(row)
            if c == "CHN":  # urban/rural rows: left out
                rows.append({**row, "reporting_level": "urban", "headcount": 0.99})
            if c == "IND" and y == 2011:  # a second welfare type the same year: one is kept
                rows.append({**row, "welfare_type": "income"})
    rows.append({"country_code": "SAU", "country_name": "Saudi Arabia", "reporting_year": 2020,  # regional fill-in
                 "reporting_level": "national", "welfare_type": "consumption", "headcount": 0.1,
                 "estimation_type": "CMD estimation", "estimate_type": "projection"})
    return rows


def fake_source_get(url, params=None):
    """FakeResponse for a URL of one of the sources other than the population data, or None."""
    params = params or {}
    if url.startswith("https://api.worldbank.org/v2/country/all/indicator/"):
        return FakeResponse(fake_wdi_payload(url.rsplit("/", 1)[1]))
    if url.startswith(ds.IMF_SDMX_URL):
        if params.get("attributes") == "all":  # the publication date request
            return FakeResponse(content=fake_imf_attributes_csv())
        return FakeResponse(content=fake_imf_csv())
    if url == ds.NDGAIN_URL:
        return FakeResponse(content=fake_ndgain_zip())
    if url == ds.WHR_URL:
        return FakeResponse(content=fake_whr_xlsx())
    if url == f"{ds.DATAVERSE_URL}/datasets/:persistentId/" and params.get("persistentId") == ds.ECI_DOI:
        return FakeResponse(fake_eci_meta())
    if url == f"{ds.DATAVERSE_URL}/access/datafile/{FAKE_ECI_FILE_ID}":
        return FakeResponse(content=fake_eci_csv())
    if url == ds.UNDP_URL:
        return FakeResponse(content=fake_undp_csv())
    if url == ds.ILO_URL and params.get("id") in ds.ILO_SERIES:
        return FakeResponse(content=fake_ilo_csv(params["id"]))
    if url == ds.ILO_TOC_URL:
        toc = pd.DataFrame([{"id": i, "indicator": i[:-2], "last.update": d} for i, d in FAKE_ILO_TOC.items()])
        return FakeResponse(content=toc.to_csv(index=False).encode())
    if url == ds.SWIID_URL:
        return FakeResponse(content=fake_swiid_csv())
    if url == ds.SWIID_COMMITS_URL and params.get("path") == ds.SWIID_PATH:
        return FakeResponse([{"sha": "d644379", "commit": {"committer": {"date": FAKE_SWIID_COMMIT},
                                                          "message": "update for 9.92"}}])
    if url == ds.PIP_URL:
        return FakeResponse(fake_pip_payload())
    if url == ds.PIP_INFO_URL:
        return FakeResponse({"available_data_versions": FAKE_PIP_VERSIONS})
    return None


FAKE_LAST_ESTIMATE_YEAR = 2024  # differs from the date-based fallback, so tests can tell which one ran
UNDP_LABEL = "Mean years of schooling"  # a Distributions indicator with a short history (1990-2023 in the fakes)


def fake_wdi_last_year_payload(year):
    """WDI's /country/WLD/indicator/{code}?mrnev=1 response: metadata, then one value."""
    return [{"page": 1, "pages": 1, "per_page": 50, "total": 1},
            [{"indicator": {"id": ds.ESTIMATES_SERIES, "value": "Population, total"},
              "country": {"id": "1W", "value": "World"}, "countryiso3code": "WLD",
              "date": str(year), "value": 8e9, "obs_status": "", "decimal": 0}]]


def check(at, label):
    if at.exception:
        print(f"!!! EXCEPTION: {label}")
        for e in at.exception:
            print(e)
        raise SystemExit(1)
    print(f"OK: {label}")


def run():
    # Start from an empty disk cache: otherwise load_data() can pick up a still-fresh
    # parquet cache another test left behind (e.g. test_transform_cache_speed's 260
    # synthetic countries) instead of this file's fake_get data. Done here rather than
    # at import time because other tests import this module for its fixtures.
    du.clear_disk_cache()
    with patch.object(du._SESSION, "get", side_effect=fake_get):
        countries, country_errors = du.load_countries()
        data, errors = du.load_data()
        print("Loaded data:", data.shape, "countries:", countries.shape)
        assert errors == {} and country_errors == {}, (errors, country_errors)
        assert set(du.SERIES) <= set(data["series_code"].unique()), set(du.SERIES) - set(data["series_code"])
        assert not countries.empty

        tn = du.trends_data(data, "NGA")
        y = 2020
        assert abs(tn.loc[y, du.BIRTHS] - tn.loc[y, du.BIRTH_RATE] * tn.loc[y, du.POP_TOTAL] / 1000) < 1e-6
        assert abs(tn.loc[y, du.NATURAL_INCREASE] - (tn.loc[y, du.BIRTHS] - tn.loc[y, du.DEATHS])) < 1e-6
        assert tn["POP:SH.DYN.MORT"].dropna().index.max() == 2024  # history only
        print("OK: trends_data derived columns")

        pop = du.country_indicator_wide(data, countries, du.POP_TOTAL)
        assert pop.loc["NGA", 2020] == tn.loc[2020, du.POP_TOTAL]
        assert "WLD" not in pop.index  # real countries only
        import app as app_mod
        import numpy as np
        import pandas as pd
        vals = pd.DataFrame({2000: [2.1, 2.15, 1.0, np.nan], 2020: [2.0, 5.95, 1.05, 1.1]})
        d = app_mod.distribution_counts(vals, ("width", 0.1))
        assert d[2000].sum() == 3 and d[2020].sum() == 4, d
        assert d.loc[2.15, 2000] == 2 and d.loc[2.15, "label"] == "2.1 to 2.2", d.loc[2.15]  # 2.1 in [2.1, 2.2)
        assert list(d.index) == sorted(d.index) and len(d) == 50  # no missing bins from 1.0 to 5.9
        grow = pd.DataFrame({2000: [-20.0] + [1.0] * 98 + [15.0], 2020: [2.0] * 100})
        dg = app_mod.distribution_counts(grow, ("width", 0.5, "clip_tails"))
        assert dg[2000].sum() == 100 and len(dg) <= 5, dg  # outliers folded, not 70 empty bins
        assert dg["label"].iloc[0].startswith("< ") and dg["label"].iloc[-1].endswith("+"), dg["label"].tolist()
        mig = pd.DataFrame({2000: [-2e6, -5, 0, 3e4], 2020: [5e5, 2e6, np.nan, -1e3]})
        # Fixed edges spanning zero (no live indicator has these now; population's start at 0).
        mig_edges = [-np.inf, -1e6, -1e5, -1e4, -1e3, 0, 1e3, 1e4, 1e5, 1e6, np.inf]
        spec = {"bins": ("edges", mig_edges, app_mod._edge_labels(mig_edges, app_mod._short_count))}
        dm = app_mod.distribution_counts(mig, spec["bins"]).set_index("label")
        assert dm.loc["< -1M", 2000] == 1 and dm.loc["-1k to 0", 2000] == 1 and dm.loc["0 to 1k", 2000] == 1
        assert dm.loc["1M+", 2020] == 1 and dm.loc["-1k to 0", 2020] == 1, dm
        # Change column: arrow + size of the change (no sign) in the indicator's format; "pp" for percentages.
        assert app_mod._change_text(0.004, ",.2f", "") == "▬ 0.00"  # rounds to zero at 2 decimals
        assert app_mod._change_text(-0.004, ",.2f", "") == "▬ 0.00"
        assert app_mod._change_text(1.2345, ",.2f", " pp") == "▲ 1.23 pp"
        assert app_mod._change_text(-1234567.0, ",.0f", "") == "▼ 1,234,567"
        assert app_mod._change_text(np.nan, ",.2f", "") == "–"
        # Tooltip headers: bins as left-closed, right-open intervals; folded tails run to infinity.
        assert app_mod.bin_intervals(d, ("width", 0.1))[:2] == ["[1, 1.1)", "[1.1, 1.2)"]
        grow_iv = app_mod.bin_intervals(dg, ("width", 0.5, "clip_tails"), "%")
        assert grow_iv[0].startswith("(-∞, ") and grow_iv[-1].endswith(", +∞)"), grow_iv
        assert app_mod.bin_intervals(dm.reset_index(), spec["bins"])[0] == "(-∞, -1M)"
        # Zero line: inside the range only -- not where the axis starts at 0.
        spans_zero = pd.DataFrame({2000: [-1.2, -0.3, 0.4, 2.2], 2020: [-0.6, 0.1, 1.0, 3.1]})
        assert app_mod.zero_line_x(app_mod.distribution_counts(spans_zero, ("width", 0.5)), ("width", 0.5)) == 0.0
        assert app_mod.zero_line_x(dg, ("width", 0.5, "clip_tails")) is None  # the -20% outlier sits in the "< x" bin
        assert app_mod.zero_line_x(d, ("width", 0.1)) is None  # 1.0 .. 5.9, all positive
        assert app_mod.zero_line_x(app_mod.distribution_counts(mig, spec["bins"]), spec["bins"]) == 4.5  # after "-1k to 0"
        pop_spec = app_mod.DISTRIBUTION_INDICATORS["Total population"]
        pop_dist = app_mod.distribution_counts(pd.DataFrame({2000: [5e4, 2e6], 2020: [8e4, 3e7]}), pop_spec["bins"])
        assert app_mod.zero_line_x(pop_dist, pop_spec["bins"]) is None  # bins start at 0: no line
        # Year slider snapping: 5-yearly forecast years after yearly history (e.g. birth rates).
        data_years = [2022, 2023, 2024, 2030, 2035]
        assert [app_mod.nearest_year(y, data_years) for y in (2024, 2027, 2028, 2032, 2033, 2050)] == \
            [2024, 2024, 2030, 2030, 2035, 2035]
        # Remembered slider years: a handle is kept (snapped) inside the indicator's year range, and
        # falls back to its own default outside it.
        assert app_mod.remembered_years((1960, 2020), list(range(1990, 2025)), (1990, 2024)) == (1990, 2020)
        assert app_mod.remembered_years((1960, 1985), list(range(1990, 2025)), (1990, 2024)) == (1990, 2024)
        assert app_mod.remembered_years((2000, 2032), data_years, (2022, 2024)) == (2022, 2030)  # start: default
        assert app_mod.remembered_years((2023, 2032), data_years, (2022, 2024)) == (2023, 2030)  # gap year snaps
        assert app_mod.remembered_years((2033, 2050), data_years, (2022, 2024)) == (2024, 2035)  # sorted
        assert app_mod.remembered_years_caption((1990, 2020), list(range(1960, 2051))) is None
        assert app_mod.remembered_years_caption((2020, 2020), list(range(1960, 2051))) is None
        assert app_mod.remembered_years_caption((1960, 2020), list(range(1990, 2025))) == (
            "This indicator has data for 1990–2024 only, so the default is shown instead of 1960.")
        # A year picked as observed that is a projection on this indicator falls back to the default
        # (the last observed year for the end); a year picked as a projection is kept (snapped).
        pip_years = list(range(1981, 2027))
        assert app_mod.remembered_years((2000, 2025), pip_years, (1981, 2024), 2024.5, (False, False)) == (2000, 2024)
        assert app_mod.remembered_years_caption((2000, 2025), pip_years, 2024.5, (False, False), (1981, 2024)) == (
            "2025 is a projection for this indicator, so the last observed year, 2024, is shown instead.")
        assert app_mod.remembered_years((2000, 2025), pip_years, (1981, 2024), 2024.5, (False, True)) == (2000, 2025)
        assert app_mod.remembered_years_caption((2000, 2025), pip_years, 2024.5, (False, True), (1981, 2024)) is None
        assert app_mod.remembered_years((2023, 2032), data_years, (2022, 2024), 2024.5, (False, True)) == (2023, 2030)
        # Observed on the indicator picked on, but no projection here: unchanged.
        assert app_mod.remembered_years((2000, 2025), pip_years, (1981, 2024), math.inf, (False, False)) == (2000, 2025)
        # Both handles at once: both observed years are projections here -> both defaults.
        assert app_mod.remembered_years((2025, 2026), pip_years, (1981, 2024), 2024.5, (False, False)) == (1981, 2024)
        assert app_mod.remembered_years_caption((2025, 2026), pip_years, 2024.5, (False, False), (1981, 2024)) == (
            "2025 and 2026 are projections for this indicator, so the default years, 1981 and 2024, are shown instead.")
        # One handle outside the data, the other a projection here: both explained.
        assert app_mod.remembered_years((1970, 2025), pip_years, (1981, 2024), 2024.5, (False, False)) == (1981, 2024)
        assert app_mod.remembered_years_caption((1970, 2025), pip_years, 2024.5, (False, False), (1981, 2024)) == (
            "This indicator has data for 1981–2026 only, so the default is shown instead of 1970. "
            "2025 is a projection for this indicator, so the last observed year, 2024, is shown instead.")
        # Default years: the first / last observed year with values for at least 30 countries.
        assert app_mod.MIN_DEFAULT_COUNTRIES == 30

        def counts_from_wide(per_year: dict[int, int]) -> pd.Series:  # a wide table with n countries per year
            wide = pd.DataFrame({y: [1.0] * n + [float("nan")] * (60 - n) for y, n in per_year.items()})
            return app_mod.countries_per_year(wide)

        sparse_start = counts_from_wide({1990: 12, 1991: 12, 1992: 30, 1993: 45, 2000: 50, 2001: 40})
        assert list(sparse_start) == [12, 12, 30, 45, 50, 40]
        assert app_mod.default_years(sparse_start, math.inf) == (1992, 2001)
        # A sparse last observed year: the end is the last observed year with 30 countries.
        sparse_end = counts_from_wide({1990: 40, 2000: 50, 2023: 31, 2024: 8})
        assert app_mod.default_years(sparse_end, math.inf) == (1990, 2023)
        # Never 30 countries: the old defaults, first year with data -> last observed year.
        thin = counts_from_wide({1990: 5, 2000: 12, 2024: 29, 2030: 20})
        assert app_mod.default_years(thin, 2024.5) == (1990, 2024)
        # A projection year with full coverage never becomes the default end year...
        projected = counts_from_wide({2000: 40, 2023: 35, 2024: 12, 2025: 60, 2030: 60})
        assert app_mod.default_years(projected, 2024.5) == (2000, 2023)
        # ...and with no observed year reaching 30, the end is the old default (last observed year).
        only_projected = counts_from_wide({2020: 10, 2024: 12, 2025: 60, 2030: 60})
        assert app_mod.default_years(only_projected, 2024.5) == (2020, 2024)
        print("OK: distributions binning / arrows")

        # Distributions' initial view: the first DEFAULT_DIST_VIEWS entry with data, else entry 1.
        views = app_mod.DEFAULT_DIST_VIEWS
        assert views[0] == ("Economics", "Real GDP growth") and len(set(views)) == len(views) == 8
        for section, label in views:
            assert label in app_mod.DISTRIBUTION_SECTIONS.get(section, {}), (section, label)
        view_source = {v: ds.source_of(app_mod.DISTRIBUTION_SECTIONS[v[0]][v[1]]["series"]) for v in views}
        assert list(view_source.values()) == ["IMF", du.POPULATION_SOURCE, "ILO", "SWIID", "NDGAIN",
                                              "UNDP", "ECI", "WHR"], view_source
        for available, expected in [({"ILO", "UNDP"}, ("Labour market", "Youth NEET rate")),
                                    (set(), views[0]),
                                    ({"WHR"}, ("Living standards", "Happiness: life evaluation")),
                                    ({"WHR", du.POPULATION_SOURCE}, ("Demographics", "Birth rate")),
                                    (set(view_source.values()), views[0])]:
            got = app_mod.first_available_view(lambda s, l: view_source[(s, l)] in available)
            assert got == expected, (available, got)
        print("OK: distributions initial view")

        # Every source loads (above), every series is there, aggregates only where published.
        # Release dates: one per source, from each publisher's metadata (or the stored constants).
        assert du.source_updates() == EXPECTED_RELEASES, du.source_updates()
        assert app_mod.month_year(dt.date(2026, 7, 31)) == "Jul-2026"
        assert app_mod.source_text("WDI", dt.date(2026, 9, 1)) == "WDI · Last updated Sep-2026"
        assert app_mod.source_text("WDI", None) == "WDI"  # no date: no "Last updated", no error
        assert (app_mod.source_text(["WDI", "IMF"], [None, dt.date(2026, 4, 14)])
                == "WDI; IMF · Last updated Apr-2026")
        # A chart whose lines come from two sources names each, with its own projections and date.
        two = app_mod.series_spec(app_mod.trend_chart, {"Growth": "IMF:NGDP_RPCH", "Unemployment": "WB:SL.UEM.TOTL.ZS"},
                                  du.trends_data(data, "USA"), data, {}, "Two sources", "%")
        assert two["sources"] == [("IMF, World Economic Outlook", "IMF"),
                                  ("World Bank, World Development Indicators", "WDI")], two["sources"]
        print("OK: source release dates")
        assert not data["value"].isna().any() and not data.duplicated(["series_code", "country_code", "year"]).any()
        aggs = {src: set(data.loc[data["series_code"].str.startswith(src + ":"), "country_code"]) - set(COUNTRY_ISO3)
                for src in ("WB", "IMF", "NDGAIN")}
        assert aggs == {"WB": {"WLD", "SSF", "HIC"}, "IMF": {"WLD"}, "NDGAIN": set()}, aggs
        xt = du.trends_data(data, "USA")
        trend_columns = [*du.SERIES, du.BIRTHS, du.DEATHS, du.NATURAL_INCREASE]
        assert list(xt.columns) == trend_columns and xt.index.min() >= 1960
        # Projections start after the last WDI estimate year for every population series but under-5
        # mortality (history only): 2024.5 also for birth rates, whose projections jump to 2030.
        expected_starts = {code: FAKE_LAST_ESTIMATE_YEAR + 0.5 for code in ds.series_of(ds.POPULATION)
                           if code != "POP:SH.DYN.MORT"}
        expected_starts.update({code: 2024.5 for code in du.SERIES if code.startswith("IMF:")})
        expected_starts.update({code: PIP_NOWCAST_FROM - 0.5 for code in ds.series_of("PIP")})
        expected_starts.update({code: ds._ilo_projection_start() - 0.5 for code in ds.series_of("ILO")})
        assert du.projection_starts(data) == expected_starts, du.projection_starts(data)
        assert du.series_split(du.NET_MIGRATION_RATE, data) == FAKE_LAST_ESTIMATE_YEAR + 0.5  # derived
        assert du.series_split("POP:SH.DYN.MORT", data) == math.inf
        # IMF's split: the publication year; without it, the latest COUNTRY_UPDATE_DATE.
        assert ds._imf_projection_start(dt.date(2026, 4, 14), pd.Series(["9/26/2025"])) == 2026
        assert ds._imf_projection_start(None, pd.Series(["9/12/2025", "9/26/2025"])) == 2025
        # PIP: national rows only, % not a share, no regional fill-ins (CMD), one row per country-year.
        pip = data[data["series_code"] == "PIP:POV_3_00"]
        assert pip["value"].max() <= 60 and "SAU" not in set(pip["country_code"]), pip["value"].max()
        # ILO: both sexes only; groups dropped. UNDP: read despite the Latin-1 encoding.
        assert set(data.loc[data["series_code"] == "ILO:NEET", "country_code"]) == set(COUNTRY_ISO3)
        assert "CIV" in set(data.loc[data["series_code"] == "UNDP:MYS", "country_code"])
        empty = du.trends_data(data, "XKX")  # no source publishes Kosovo here: every column, no rows
        assert empty.empty and list(empty.columns) == trend_columns
        lic = du.trends_data(data, "LIC")  # Low income: only the population data publishes it here
        assert {ds.source_of(c) for c in lic.columns if lic[c].notna().any()} == {ds.POPULATION}
        # GDP and GNI per capita share one y-axis range, from 0 to above both series' maximum.
        specs = app_mod.living_standards_charts(xt, data)[:2]
        ranges = [tuple(s["chart_fn"](s["lines"], s["colors"], title="x", **s["kw"]).layout.yaxis.range)
                  for s in specs]
        top = xt[["WB:NY.GDP.PCAP.PP.KD", "WB:NY.GNP.PCAP.PP.KD"]].max().max()
        assert ranges[0] == ranges[1] and ranges[0][0] == 0 and ranges[0][1] > top, (ranges, top)
        # The Economic Complexity Index's y-axis is symmetric around 0 (the world average) on one fixed
        # scale (+-2.5, plus the usual 10% headroom) for every country; bounded scores stay within their scale.
        eci = next(s for s in app_mod.industry_charts(xt, data) if s["title"] == "Economic Complexity Index")
        lo, hi = eci["chart_fn"](eci["lines"], eci["colors"], title="x", **eci["kw"]).layout.yaxis.range
        assert xt["ECI:ECI"].abs().max() < app_mod.ECI_SCALE and (lo, hi) == (-2.75, 2.75), (lo, hi)
        assert app_mod.symmetric_axis(-2.9, -1.7, 0)["range"][0] < -2.9
        assert app_mod.symmetric_axis(5, 99, 50)["range"] == [0, 100]
        print("OK: every source")

        # Reference marks: each on its Trends chart (if it has one) and its Distributions histogram,
        # labelled; education's is a band from 4 to 6. Out-of-pocket spending and elderly share have none.
        def marks(fig):
            """(lines, bands, annotation texts) of a figure's reference shapes."""
            lines = [s for s in fig.layout.shapes if s.type == "line" and s.line.dash in ("dash", "dot")]
            bands = [s for s in fig.layout.shapes if s.type == "rect"]
            return lines, bands, [a.text for a in fig.layout.annotations]

        def trend_fig(specs, title):
            spec = next(s for s in specs if s["title"] == title)
            return spec, spec["chart_fn"](spec["lines"], spec["colors"], title="x", **spec["kw"])

        tn_specs = app_mod.demographics_charts(tn, data)
        x_specs = (app_mod.living_standards_charts(xt, data) + app_mod.education_charts(xt, data)
                   + app_mod.healthcare_charts(xt, data))
        expected_lines = {  # Trends title -> (value, label)
            "Total fertility rate": (2.1, "Replacement level (2.1)"),
            "Under-5 mortality rate": (25, "SDG target for 2030 (25)"),
            "Poverty at $3.00 a day": (3, "Global target for 2030 (3%)"),
        }
        for title, (value, label) in expected_lines.items():
            _, fig = trend_fig(tn_specs + x_specs, title)
            lines, bands, texts = marks(fig)
            assert [(s.y0, s.y1) for s in lines] == [(value, value)] and not bands, (title, lines, bands)
            assert texts == [label], (title, texts)
            assert fig.layout.yaxis.range[1] >= value, (title, fig.layout.yaxis.range)  # axis reaches the line
        u5 = tn["POP:SH.DYN.MORT"].dropna()
        assert u5.max() > 25, "the fake under-5 rates should cross the line"
        _, low_u5 = trend_fig(app_mod.demographics_charts(tn.assign(**{"POP:SH.DYN.MORT": u5 / 30}), data),
                              "Under-5 mortality rate")
        assert low_u5.layout.yaxis.range[1] > 25, low_u5.layout.yaxis.range  # far below it: axis still reaches 25
        spec, fig = trend_fig(x_specs, "Government expenditure on education")
        lines, bands, texts = marks(fig)
        assert not lines and [(b.y0, b.y1) for b in bands] == [(4, 6)], (lines, bands)
        assert bands[0].layer == "below" and bands[0].line.width == 0 and bands[0].fillcolor == du.REF_BAND_COLOR
        assert texts == ["Education 2030 benchmark (4–6% of GDP)"], texts
        spec, _ = trend_fig(x_specs, "Poverty at $3.00 a day")
        assert app_mod.POVERTY_TARGET_NOTE in spec["note"], spec["note"]
        assert app_mod.POVERTY_TARGET_NOTE == "The 3% target is for the world as a whole by 2030, not for each country."
        for specs, title in [(tn_specs, "Age group shares"), (x_specs, "Out-of-pocket health spending")]:
            _, fig = trend_fig(specs, title)
            assert marks(fig)[:2] == ([], []), (title, marks(fig))

        expected_hist = {  # Distributions label -> (vlines values, band edges, labels)
            "Fertility rate": ([2.1], None, ["Replacement level (2.1)"]),
            "Under-5 mortality rate": ([25], None, ["SDG target for 2030 (25)"]),
            "Poverty at $3.00 a day": ([3], None, ["Global target for 2030 (3%)"]),
            "Government expenditure on education": ([], (4, 6), ["Education 2030 benchmark (4–6% of GDP)"]),
        }
        for label, spec in app_mod.DISTRIBUTION_INDICATORS.items():
            values, band, texts = expected_hist.get(label, ([], None, []))
            if "vlines" not in spec and "band" not in spec:
                assert not values and band is None, f"{label}: reference mark missing"
                continue
            width = spec["bins"][1]
            vals = pd.DataFrame({2000: np.linspace(0, 40, 81), 2020: np.linspace(0.5, 30, 81)})
            dist = app_mod.distribution_counts(vals, spec["bins"])
            fig = app_mod.distribution_bars(dist, spec["bins"], label, 2000, 2020, x_title="x",
                                            vlines=spec.get("vlines"), band=spec.get("band"))
            left = float(dist.index[0]) - width / 2

            def value_at(x):  # category position -> value (bin k spans k - 0.5 .. k + 0.5)
                return round((x + 0.5) * width + left, 6)

            lines, bands, got_texts = marks(fig)
            assert [value_at(s.x0) for s in lines] == values, (label, [value_at(s.x0) for s in lines])
            assert all(s.line.dash == "dot" and s.line.color == du.BLACK for s in lines), label
            assert [(value_at(b.x0), value_at(b.x1)) for b in bands] == ([band] if band else []), label
            assert all(b.line.width == 0 and b.layer == "below" for b in bands), label
            edges = values + list(band or [])
            assert all(abs(v / width - round(v / width)) < 1e-9 for v in edges), f"{label}: mark not on a bin edge"
            assert list(got_texts) == texts, (label, got_texts)
        assert app_mod.DISTRIBUTION_INDICATORS["Poverty at $3.00 a day"]["note"] == app_mod.POVERTY_TARGET_NOTE
        assert not hasattr(du, "AGING_THRESHOLDS")
        print("OK: reference lines and band on Trends and Distributions")

        print("ALL DATA_UTILS TRANSFORMS OK\n")

    with patch.object(du._SESSION, "get", side_effect=fake_get):
        from streamlit.testing.v1 import AppTest
        at = AppTest.from_file(_pathfix.APP_PATH, default_timeout=60)
        at.run()
        check(at, "initial load (both tabs render)")
        assert len(at.tabs) == 2, f"expected Trends + Distributions tabs, got {len(at.tabs)}"
        tab_labels = [t.label for t in at.tabs]
        # Distributions is the landing tab: first in st.tabs, so the app opens on it.
        assert tab_labels == ["Period & Country Comparisons", "Country Profiles"], f"tab labels: {tab_labels}"
        assert at.tabs[0].segmented_control(key="dist_section").label == "Indicator Group"
        assert at.tabs[1].selectbox(key="trends_entity") is not None  # Trends in the second tab
        intro = at.caption[0].value
        assert intro.startswith("This app gathers a curated set of publicly available indicators"), intro
        about = [c.value for c in at.sidebar.caption]
        assert len(about) == 3 and about[1].startswith("**Country Profiles** follows a single country"), about
        # The three section breaks on the Distributions tab, in order, light (not <h3>) headings.
        breaks = [m.value for m in at.tabs[0].markdown if 'role="heading"' in m.value]
        names = ["Global Distribution Comparison Between Years", "Country-Level Insights",
                 "Global Distribution Shift By Year"]
        assert len(breaks) == 3 and all(n in b for n, b in zip(names, breaks)), breaks
        assert not any("<h3" in b for b in breaks), breaks

        assert [t.value for t in at.title] == [app_mod.APP_NAME], [t.value for t in at.title]
        # Distributions opens on Economics / Real GDP growth (the first DEFAULT_DIST_VIEWS entry).
        assert at.segmented_control(key="dist_section").value == "Economics"
        assert at.selectbox(key="dist_indicator_Economics").value == "Real GDP growth"
        assert app_mod.APP_NAME == "Global Shifts & Trends Tracker", app_mod.APP_NAME

        # The sidebar's "Data sources and licences" dialog shows DATA_SOURCES.md, its link to LICENSE
        # pointed at the licence's page (a relative link goes nowhere in the app).
        next(b for b in at.sidebar.button if b.label == "Data sources and licences").click().run()
        check(at, "data sources dialog")
        sources_md = [m.value for m in at.markdown if "## Non-commercial use" in m.value]
        assert len(sources_md) == 1, "DATA_SOURCES.md not shown in the dialog"
        assert app_mod.LICENSE_URL in sources_md[0] and "](LICENSE)" not in sources_md[0]
        assert not sources_md[0].startswith("# Data sources")  # the dialog's title replaces the heading

        # --- Trends tab: entity dropdown ---
        trends_sel = at.selectbox(key="trends_entity")
        assert app_mod.DEFAULT_ENTITY == "DEU", app_mod.DEFAULT_ENTITY
        assert app_mod.DEFAULT_ENTITY not in countries["country_code"].values  # no Germany in the fakes...
        assert trends_sel.value == "WLD", trends_sel.value  # ...so the default falls back to World
        opts = trends_sel.options
        assert opts[:12] == ["World", *du.REGION_CODES.values(), *du.INCOME_CODES.values()], opts[:12]
        assert len(opts) == 12 + len(du.real_country_codes(countries))
        for code in ("NGA", "SSF", "LIC"):
            at.selectbox(key="trends_entity").set_value(code).run()
            check(at, f"trends: entity {code}")
        n_trend_charts = sum(1 for c in at.get("plotly_chart"))
        print("plotly charts on page after trends switch:", n_trend_charts)
        # Low income: only the population data covers it here, so every other section is skipped
        # entirely -- no header, no "no data" notes.
        assert [h.value for h in at.subheader] == ["Demographics"], [h.value for h in at.subheader]
        assert not at.info, [i.value for i in at.info]
        assert not at.warning, [w.value for w in at.warning]  # every source loaded
        at.selectbox(key="trends_entity").set_value("USA").run()
        check(at, "trends: entity USA")
        trend_sections = [h.value for h in at.subheader]
        assert trend_sections == ["Economics", "Labour market", "Industry & innovation", "Living standards",
                                  "Demographics", "Climate",
                                  "Infrastructure & basic services", "Education",
                                  "Healthcare"], trend_sections
        assert not at.info, [i.value for i in at.info]  # every chart in every section has data
        assert [c.value for c in at.caption].count("Read with the unemployment rate in Economics.") == 1
        footers = [m.value for m in at.markdown if "Source:" in m.value]
        assert sum(app_mod.POVERTY_TARGET_NOTE in f for f in footers) == 1, "poverty chart's footer note"
        # "Last updated" on every Trends footer: population charts and every other source's.
        trend_footers = [m.value for m in at.tabs[1].markdown if "Source:" in m.value]
        assert all("· Last updated " in f for f in trend_footers), [f for f in trend_footers if "Last updated" not in f]
        # The Observed/Forecast legend explains the dotted lines: no footer repeats it.
        assert not any("dotted" in f for f in trend_footers), [f for f in trend_footers if "dotted" in f]
        for expected in ["Source: World Bank, Population estimates and projections · Last updated Jul-2026",
                         "Source: World Bank, World Development Indicators · Last updated Sep-2026",
                         "Source: IMF, World Economic Outlook · Last updated Oct-2025",
                         "Source: University of Notre Dame, ND-GAIN Country Index · Last updated "
                         + app_mod.month_year(ds.NDGAIN_RELEASED)]:
            assert any(expected in f for f in trend_footers), expected
        # Distributions footers stay as they were.
        assert not any("Last updated" in m.value for m in at.tabs[0].markdown), "Distributions footer"
        at.selectbox(key="trends_entity").set_value("WLD").run()
        # World: only WDI and IMF publish a World aggregate in the fakes (SWIID, PIP, ND-GAIN, UNDP, ILO,
        # ECI and WHR don't), so five sections each get a note naming their charts without data.
        infos = [i.value for i in at.info]
        assert len(infos) == 5, infos
        # (Economics has every chart for World: no note.)
        assert infos[0].startswith("1 of 3 indicators have data for World.") and "Youth not in employment" in infos[0]
        assert "Labour income share" in infos[0], infos[0]
        assert infos[1].startswith("4 of 5 indicators have data for World.") and "Economic Complexity" in infos[1]
        assert infos[2].startswith("2 of 6 indicators have data for World."), infos[2]
        assert "Happiness: life evaluation" in infos[2] and "Median income" in infos[2], infos[2]
        assert infos[3].startswith("5 of 7 indicators have data for World.") and "ND-GAIN country index" in infos[3]
        assert infos[4].startswith("2 of 3 indicators have data for World.") and "years of schooling" in infos[4]
        # Economics in its five fixed rows; row 4 has two charts.
        specs = app_mod.economics_charts(du.trends_data(data, "WLD"), data)
        rows = [[s["title"] for s in specs if s["row"] == n] for n in range(max(s["row"] for s in specs) + 1)]
        assert rows == [["Real GDP growth", "Consumer prices", "Unemployment rate"],
                        ["Government revenue and expenditure", "Government budget balance",
                         "General government gross debt"],
                        ["Current account balance", "Foreign direct investment, net inflows",
                         "Domestic credit to private sector"],
                        ["Price level relative to the US", "Net energy imports"],
                        ["GDP, PPP", "Output by sector", "Employment by sector"]], rows
        titles = [s["title"] for s in app_mod.labour_charts(du.trends_data(data, "WLD"), data)]
        assert titles == ["Labour force participation rate", "Youth not in employment, education or training",
                          "Labour income share"], titles
        titles = [s["title"] for s in app_mod.industry_charts(du.trends_data(data, "WLD"), data)]
        assert titles == ["Manufacturing contribution to GDP", "Medium and high-tech manufacturing",
                          "Manufactured exports", "Economic Complexity Index",
                          "Research and development expenditure"], titles

        # --- Distributions tab: every indicator of every section renders (distribution, map, table) ---
        import app as app_mod
        assert list(app_mod.DISTRIBUTION_SECTIONS) == trend_sections  # same sections, same order as Trends
        labels = [(sec, label) for sec, specs in app_mod.DISTRIBUTION_SECTIONS.items() for label in specs]
        assert len(labels) == len(app_mod.DISTRIBUTION_INDICATORS), "a label is in two sections (one is lost)"
        dist_series = {spec["series"] for spec in app_mod.DISTRIBUTION_INDICATORS.values()}
        assert dist_series >= set(du.SERIES) - app_mod.TRENDS_ONLY_SERIES, set(du.SERIES) - dist_series
        assert not dist_series & app_mod.TRENDS_ONLY_SERIES  # e.g. the services shares: Trends only
        for section, label in labels:
            at.segmented_control(key="dist_section").set_value(section).run()
            at.selectbox(key=f"dist_indicator_{section}").set_value(label).run()
            check(at, f"distributions: {label}")
            if label == "Poverty at $3.00 a day":  # the world-target note in the histogram's footer
                assert any(app_mod.POVERTY_TARGET_NOTE in m.value for m in at.markdown if "Source:" in m.value)
            mode = next(r for r in at.segmented_control if r.label == "Select map mode")
            assert len(mode.options) == 3 and mode.options[-1].startswith("Change, "), mode.options
            mode.set_value("change").run()
            check(at, f"distributions: {label}, change map")
            table = next(d for d in at.dataframe if "Change" in d.value.columns).value
            year_cols = [c for c in table.columns if str(c).strip().isdigit()]
            assert pd.api.types.is_numeric_dtype(table["Change"]), table["Change"].dtype  # sorts by size
            if len(year_cols) == 2:
                expected = table[year_cols[1]] - table[year_cols[0]]
                assert ((table["Change"] - expected).abs().fillna(0) < 1e-9).all()
        at.segmented_control(key="dist_section").set_value("Demographics").run()
        at.selectbox(key="dist_indicator_Demographics").set_value("Fertility rate").run()

        # --- Distributions: the year slider keeps the user's choice across indicators ---
        def dist_slider(label):
            return at.slider(key=f"dist_year_range_{label}")

        def selection_captions():
            return [c.value for c in at.caption
                    if c.value.startswith("This indicator has data for") or "for this indicator, so" in c.value]

        assert app_mod.DIST_USER_YEARS not in at.session_state  # nothing moved yet: defaults everywhere...
        # The fakes have 5 countries, never MIN_DEFAULT_COUNTRIES: default_years takes its fallback.
        assert dist_slider("Fertility rate").value == (1960, FAKE_LAST_ESTIMATE_YEAR)
        assert not selection_captions()  # ...and no caption
        dist_slider("Fertility rate").set_value((1965, 2040)).run()
        check(at, "distributions: year slider moved")
        assert at.session_state[app_mod.DIST_USER_YEARS] == (1965, 2040)
        assert at.session_state[app_mod.DIST_USER_PROJECTED] == (False, True)  # 2040: a fertility projection
        assert not selection_captions(), selection_captions()  # both years in the data: no caption
        assert not [c.value for c in at.caption if c.value.startswith("You've selected")]
        # Under-5 mortality has no forecast: 1965 is kept, 2040 falls back to the default end year.
        at.selectbox(key="dist_indicator_Demographics").set_value("Under-5 mortality rate").run()
        check(at, "distributions: remembered years, one outside the data")
        assert dist_slider("Under-5 mortality rate").value == (1965, 2024)
        assert selection_captions() == ["This indicator has data for 1960–2024 only, so the default is shown "
                                        "instead of 2040."], selection_captions()
        # Neither year in the data (UNDP: 1990-2023): the indicator's full default range.
        at.segmented_control(key="dist_section").set_value("Education").run()
        at.selectbox(key="dist_indicator_Education").set_value(UNDP_LABEL).run()
        check(at, "distributions: remembered years, both outside the data")
        assert dist_slider(UNDP_LABEL).value == (1990, 2023), dist_slider(UNDP_LABEL).value
        assert selection_captions()[0].endswith("instead of 1965 and 2040."), selection_captions()
        # A fallback doesn't overwrite the choice: back on a long series it is restored in full.
        at.segmented_control(key="dist_section").set_value("Demographics").run()
        at.selectbox(key="dist_indicator_Demographics").set_value("Birth rate").run()
        assert dist_slider("Birth rate").value == (1965, 2040), dist_slider("Birth rate").value
        assert at.session_state[app_mod.DIST_USER_YEARS] == (1965, 2040)
        # --- Distributions: start / end year fields, in step with the slider both ways ---
        def year_fields(label):
            return (at.number_input(key=f"dist_year_start_{label}").value,
                    at.number_input(key=f"dist_year_end_{label}").value)

        assert year_fields("Birth rate") == (1965, 2040)  # the fields follow the slider...
        at.number_input(key="dist_year_start_Birth rate").set_value(1980).run()
        check(at, "distributions: start year typed")
        assert dist_slider("Birth rate").value == (1980, 2040)  # ...and the slider follows a field
        assert at.session_state[app_mod.DIST_USER_YEARS] == (1980, 2040)
        assert not selection_captions(), selection_captions()
        table = next(d for d in at.dataframe if "Change" in d.value.columns).value
        assert [c for c in table.columns if str(c).strip().isdigit()] == ["1980", "2040"], list(table.columns)
        at.number_input(key="dist_year_end_Birth rate").set_value(1970).run()  # end before start: swapped
        assert dist_slider("Birth rate").value == (1970, 1980) and year_fields("Birth rate") == (1970, 1980)
        dist_slider("Birth rate").set_value((2000, 2010)).run()
        assert year_fields("Birth rate") == (2000, 2010)
        # Typed years carry over to other indicators like slider moves do.
        at.selectbox(key="dist_indicator_Demographics").set_value("Fertility rate").run()
        assert dist_slider("Fertility rate").value == (2000, 2010) and year_fields("Fertility rate") == (2000, 2010)
        # Reset: the choice is forgotten, every indicator is back on its own default, no caption.
        reset = at.button(key="dist_years_reset_Fertility rate")
        assert not reset.disabled
        reset.click().run()
        check(at, "distributions: years reset")
        assert app_mod.DIST_USER_YEARS not in at.session_state and not selection_captions()
        assert dist_slider("Fertility rate").value == (1960, FAKE_LAST_ESTIMATE_YEAR)
        assert year_fields("Fertility rate") == (1960, FAKE_LAST_ESTIMATE_YEAR)
        assert at.button(key="dist_years_reset_Fertility rate").disabled  # nothing to reset
        at.selectbox(key="dist_indicator_Demographics").set_value("Under-5 mortality rate").run()
        assert dist_slider("Under-5 mortality rate").value == (1960, 2024)
        at.selectbox(key="dist_indicator_Demographics").set_value("Fertility rate").run()

        # --- Distributions: an observed year never lands on another indicator's projection ---
        # 2024 is observed for fertility (projections from FAKE_LAST_ESTIMATE_YEAR + 1) but a PIP
        # nowcast (from PIP_NOWCAST_FROM): on poverty the end handle shows its last observed year.
        assert FAKE_LAST_ESTIMATE_YEAR == PIP_NOWCAST_FROM == 2024
        dist_slider("Fertility rate").set_value((1990, 2024)).run()
        assert at.session_state[app_mod.DIST_USER_PROJECTED] == (False, False)
        pov_section = next(sec for sec, specs in app_mod.DISTRIBUTION_SECTIONS.items()
                           if "Poverty at $3.00 a day" in specs)
        at.segmented_control(key="dist_section").set_value(pov_section).run()
        at.selectbox(key=f"dist_indicator_{pov_section}").set_value("Poverty at $3.00 a day").run()
        check(at, "distributions: remembered observed year is a projection here")
        assert dist_slider("Poverty at $3.00 a day").value == (1990, 2023), dist_slider("Poverty at $3.00 a day").value
        assert selection_captions() == ["2024 is a projection for this indicator, so the last observed year, "
                                        "2023, is shown instead."], selection_captions()
        assert not [c.value for c in at.caption if "on are projections" in c.value]  # no projection shown
        assert at.session_state[app_mod.DIST_USER_YEARS] == (1990, 2024)  # the choice itself is kept
        # A year picked as a projection is carried: 2025 on poverty (a nowcast) shows 2025 on fertility.
        dist_slider("Poverty at $3.00 a day").set_value((1990, 2025)).run()
        assert at.session_state[app_mod.DIST_USER_PROJECTED] == (False, True)
        at.segmented_control(key="dist_section").set_value("Demographics").run()
        at.selectbox(key="dist_indicator_Demographics").set_value("Fertility rate").run()
        assert dist_slider("Fertility rate").value[1] == 2025 and not selection_captions(), selection_captions()
        at.button(key="dist_years_reset_Fertility rate").click().run()
        assert app_mod.DIST_USER_PROJECTED not in at.session_state

        selectboxes = at.selectbox
        for sb in selectboxes:
            if sb.key == "trends_entity":  # code-valued (format_func shows names); tested above
                continue
            sb.set_value(sb.options[0]).run()
            check(at, f"selectbox '{sb.label}' changed")

        # --- Refresh data button ---
        buttons = at.sidebar.button
        if buttons:
            buttons[0].click().run()
            check(at, "refresh data button")

    # --- Distributions without IMF data: the tab opens on the next view, Demographics / Birth rate ---
    def imf_down_get(url, *args, **kwargs):
        if url.startswith(ds.IMF_SDMX_URL) or url.startswith(ds.IMF_DATAMAPPER_URL):  # both IMF routes
            raise ConnectionError("simulated: IMF unreachable")
        return fake_get(url, *args, **kwargs)

    import streamlit as st
    du.clear_disk_cache()
    st.cache_data.clear()
    with patch.object(du._SESSION, "get", side_effect=imf_down_get):
        at = AppTest.from_file(_pathfix.APP_PATH, default_timeout=60)
        at.run()
        check(at, "initial load without IMF data")
        assert at.segmented_control(key="dist_section").value == "Demographics"
        assert at.selectbox(key="dist_indicator_Demographics").value == "Birth rate"
        # The chain only picks the initial view: Economics, chosen by the user, stands without data.
        at.segmented_control(key="dist_section").set_value("Economics").run()
        check(at, "Economics without IMF data")
        assert at.selectbox(key="dist_indicator_Economics").value == "Real GDP growth"  # its first indicator
        assert any("No country data loaded" in i.value for i in at.info), [i.value for i in at.info]
        at.segmented_control(key="dist_section").set_value("Demographics").run()
        assert at.selectbox(key="dist_indicator_Demographics").value == "Birth rate"
    st.cache_data.clear()

    du.clear_disk_cache()
    print("\nALL APP INTERACTIONS PASSED")


if __name__ == "__main__":
    run()
