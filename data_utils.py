"""
Data access layer for the Global Shifts & Trends Tracker app.

Pulls the World Bank's "Population estimates and projections" database
(source id 40 on the World Bank API) which, unlike the standard WDI
indicator endpoints, includes forecasts out to 2050 alongside history
back to 1960.

Two layers of caching sit in front of the network:
  1. st.cache_data -- an in-memory cache for the lifetime of the running
     process. Free, but lost whenever the process restarts (a redeploy, or a
     free-tier host waking a sleeping app).
  2. A small on-disk parquet cache next to this file -- survives a process
     restart as long as the underlying filesystem does. When it's present and
     still fresh, a freshly-started process can skip the network fetch
     entirely instead of just fetching it quickly.
Both layers share the same TTL, and both are best-effort: if the filesystem
turns out to be read-only or ephemeral on a given host, the disk layer just
quietly never hits, and the app behaves exactly as it did before -- fetching
over the network (in parallel) every time the in-memory cache is cold.

A third, separate kind of caching applies to the pandas transform functions
below (trends_data, country_indicator_wide): st.tabs isn't lazy, so a full
run of the script builds both tabs (app.py makes each tab an st.fragment, so a
widget inside one reruns only that tab), which would otherwise redo every one
of these pivots/groupbys each time. They're
cached with @st.cache_data using a cheap custom fingerprint (see
_fast_df_fingerprint) instead of Streamlit's default full-content hash --
hashing our ~220k-row dataframe byte-for-byte costs more than most of these
functions' own computation, which would make caching a net loss rather than a
win. The fingerprint (shape + column names + a sum over numeric columns) is
good enough here: this data only ever changes via a real refetch (never a
subtle in-place edit), so the astronomically unlikely case of two different
fetches coincidentally sharing a fingerprint is not a real-world concern.
"""

from __future__ import annotations

import concurrent.futures
import datetime as dt
import json
import os
import shutil
import threading
import time
from pathlib import Path

import pandas as pd
import requests
import streamlit as st

import country_dict as cd
import extra_sources as xs

WB_API_BASE = "https://api.worldbank.org/v2"
SOURCE_ID = 40  # "Population estimates and projections" -- has data through 2050
REQUEST_TIMEOUT = 60
CACHE_TTL_SECONDS = 60 * 60 * 24  # 24h -- shared by st.cache_data and the on-disk cache

# A shared Session reuses TCP/TLS connections across every call to the World
# Bank API (they all hit the same host), instead of paying a fresh handshake
# for each of the ~10 requests load_data() makes.
_SESSION = requests.Session()

# On-disk cache: parquet files next to this module, plus their mtime as the
# freshness signal (no separate metadata file needed). WB_DATA_CACHE_DIR overrides
# the location -- the test suite sets it (in tests/_pathfix.py) so its fake data
# never lands in the cache the real app reads.
_CACHE_DIR = Path(os.environ.get("WB_DATA_CACHE_DIR") or Path(__file__).resolve().parent / ".wb_data_cache")
_DATA_CACHE_FILE = _CACHE_DIR / "population_data.parquet"
_COUNTRIES_CACHE_FILE = _CACHE_DIR / "countries.parquet"
_UPDATES_CACHE_FILE = _CACHE_DIR / "source_updates.json"  # release dates, see source_updates()

# Series (indicator) codes used throughout the app.
INDICATORS: dict[str, str] = {
    "SP.POP.TOTL": "Population, total",
    "SP.POP.GROW": "Population growth (annual %)",
    "SP.DYN.TFRT.IN": "Fertility rate, total (births per woman)",
    "SP.DYN.LE00.IN": "Life expectancy at birth, total (years)",
    "SP.POP.0014.TO.ZS": "Population ages 0-14 (% of total population)",
    "SP.POP.65UP.TO.ZS": "Population ages 65 and above (% of total population)",
    "SP.POP.1564.TO.ZS": "Population ages 15-64 (% of total population)",
    "SM.POP.NETM": "Net migration",
    "SP.DYN.CBRT.IN": "Birth rate, crude (per 1,000 people)",
    "SP.DYN.CDRT.IN": "Death rate, crude (per 1,000 people)",
    "SH.DYN.MORT": "Mortality rate, under-5 (per 1,000)",  # history only, no forecast
    "SP.POP.DPND": "Age dependency ratio (% of working-age population)",
    "SP.POP.DPND.OL": "Age dependency ratio, old",
    "SP.POP.DPND.YG": "Age dependency ratio, young",
    "SP.DYN.LE00.FE.IN": "Life expectancy at birth, female (years)",
    "SP.DYN.LE00.MA.IN": "Life expectancy at birth, male (years)",
}

WORLD_CODE = "WLD"

# Values must match the region names the World Bank API returns exactly: chart columns
# come straight from the data, and REGION_COLOR_MAP is keyed by these values, so a stale
# name silently renders that region grey. (The World Bank renamed MEA from "Middle East &
# North Africa" to its current name.) Display-only short names: app.REGION_SHORT_LABEL.
REGION_CODES: dict[str, str] = {
    "EAS": "East Asia & Pacific",
    "ECS": "Europe & Central Asia",
    "LCN": "Latin America & Caribbean",
    "MEA": "Middle East, North Africa, Afghanistan & Pakistan",
    "NAC": "North America",
    "SAS": "South Asia",
    "SSF": "Sub-Saharan Africa",
}

INCOME_CODES: dict[str, str] = {
    "HIC": "High income",
    "UMC": "Upper middle income",
    "LMC": "Lower middle income",
    "LIC": "Low income",
}

# Colors: the OHA palette (USAID Office of HIV/AIDS data visualization guide, built on the
# USAID colors), used the way the Urban Institute style guide uses its own colors (chart style
# follows Urban too, see app.style_fig): OHA Denim and Golden Sand take the roles of Urban's
# cyan and yellow, OHA grays those of Urban's grays.
DENIM, SCOOTER, OLD_ROSE, GOLDEN_SAND = "#2057a7", "#1e87a5", "#c43d4d", "#f2bc40"
MOODY_BLUE, GENOA, BURNT_SIENNA, TROLLEY_GREY = "#8980cb", "#287c6f", "#e07653", "#808080"
BLACK = "#000000"
# OHA grays, light to dark: "shaded area", "light grid", "caption", "subtitle/body", "title".
WHISPER, LIGHT_GREY, SUVA_GREY, MATTERHORN, NERO = "#ebebeb", "#d3d3d3", "#909090", "#505050", "#202020"
# Categorical series follow Urban's order (cyan, yellow, black, gray, magenta, green, space gray,
# orange) in OHA colors.
CATEGORICAL_COLORS = [DENIM, GOLDEN_SAND, NERO, LIGHT_GREY, OLD_ROSE, GENOA, MATTERHORN, BURNT_SIENNA]
# Maps: the OHA "Denims" sequential ramp (light to dark), and a diverging palette from the
# "Golden Sands" (negative, dark to light) through a neutral near-white at 0 into the Denims
# (positive, light to dark) -- Urban's yellow-to-blue diverging palette in OHA colors. The
# neutral midpoint keeps values near 0 from blending into a muddy gray.
SEQUENTIAL_RAMP = ["#bfddff", "#a7c4fd", "#8aadfe", "#7397ef", "#5784d4", "#456ebe", "#215dad", "#064896",
                   "#02397d", "#032461"]
DIVERGING = ["#735000", "#a27601", "#d29f1f", "#fbcf4f", "#ffeb6e", "#f5f5f5",
             "#bfddff", "#8aadfe", "#5784d4", "#215dad", "#02397d"]
GRID_COLOR = LIGHT_GREY  # horizontal gridlines only

# Distributions table region labels: four OHA colors other than the two primary ones (Denim,
# Golden Sand), then three OHA grays. Region order is the World Bank's (alphabetical), so each
# region keeps its color.
REGION_COLORS = [SCOOTER, MOODY_BLUE, GENOA, OLD_ROSE, LIGHT_GREY, SUVA_GREY, MATTERHORN]
REGION_COLOR_MAP: dict[str, str] = dict(zip(REGION_CODES.values(), REGION_COLORS))

DIST_COLORS = [DENIM, GOLDEN_SAND]  # two-year overlay bars
# Reference bands (education spending's 4-6% of GDP): a light neutral tint, translucent so the gridlines
# (drawn under every shape in Plotly's "below" layer) still show through.
REF_BAND_COLOR, REF_BAND_OPACITY = LIGHT_GREY, 0.45

ZERO_LINE_COLOR = BLACK  # y = 0 lines: solid black (app.style_fig + add_hline)
# Distributions table change arrows: direction only, in colors with no good/bad reading
# (a rising death rate isn't "green"): the diverging palette's blue up and gold down, gray for
# no change. Denim reads well as text on white; Golden Sand doesn't, so the down arrow takes a
# darker step of the Golden Sands ramp (WCAG AA contrast).
CHANGE_UP_COLOR, CHANGE_DOWN_COLOR, NO_CHANGE_COLOR = DENIM, "#8a5f00", TROLLEY_GREY
REPLACEMENT_LEVEL = 2.1  # births per woman
# Reference marks: drawn on the Trends chart and the
# Distributions histogram of their indicator.
U5_MORTALITY_TARGET = 25  # deaths per 1,000 live births: SDG target 3.2, by 2030
POVERTY_TARGET = 3  # % of the world's population below $3.00 a day: World Bank goal for 2030
EDUCATION_SPENDING_BENCHMARK = (4, 6)  # % of GDP: Education 2030 Framework for Action


def _compute_forecast_start(today: dt.date | None = None) -> float:
    """
    Fallback for forecast_start() when the WDI lookup fails: a date-based guess.

    The boundary is the midpoint
    between the last actual year and the first forecast year (e.g. 2025.5 sits between
    actual-2025 and forecast-2026). It shifts by a year each August, roughly when the
    World Bank publishes the prior year's actuals: from August 1st onward, last year is
    presumed final (boundary at (today's year - 1) + 0.5); before that, one year earlier.
    """
    today = today or dt.date.today()
    prev_year = today.year - 1
    if today.month >= 8:
        return prev_year + 0.5
    return prev_year + 0.5 - 1


# Source 40 carries estimates and projections with no per-value flag for which is which,
# but World Development Indicators (WDI) carries the same estimates only: the last year
# WDI reports for total population is the last estimated year.
ESTIMATES_SERIES = "SP.POP.TOTL"


def last_estimate_year(series_code: str = ESTIMATES_SERIES) -> int:
    """Latest year with a World value for series_code in WDI (mrnev=1: most recent non-empty value)."""
    url = f"{WB_API_BASE}/country/{WORLD_CODE}/indicator/{series_code}"
    try:
        resp = _SESSION.get(url, params={"format": "json", "mrnev": 1}, timeout=15)
        resp.raise_for_status()
        return int(resp.json()[1][0]["date"])
    except Exception as exc:  # noqa: BLE001
        raise DataFetchError(f"Could not read the last WDI estimate year for {series_code}: {exc}") from exc


@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
def forecast_start() -> float:
    """
    Where estimates end and projections begin: last WDI estimate year + 0.5 (the midpoint
    before the first projected year, e.g. 2025.5 -> projections from 2026). Falls back to
    the date-based _compute_forecast_start() if WDI can't be reached, so charts still split.
    """
    try:
        return last_estimate_year() + 0.5
    except DataFetchError:
        return _compute_forecast_start()


def _fast_df_fingerprint(d: pd.DataFrame):
    """Cheap stand-in for st.cache_data's default DataFrame hash (shape + column
    names + a sum over numeric columns) -- see the module docstring for why."""
    numeric = d.select_dtypes("number")
    numeric_sum = float(numeric.sum().sum()) if not numeric.empty else 0.0
    return (d.shape, tuple(d.columns), numeric_sum)


# Passed as hash_funcs to every @st.cache_data transform below that takes df/countries.
_DF_HASH_FUNCS = {pd.DataFrame: _fast_df_fingerprint}


class DataFetchError(RuntimeError):
    """Raised when the World Bank API cannot be reached or returns something unexpected."""


@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
def fetch_countries() -> pd.DataFrame:
    """Country/region/income-group metadata from the World Bank /country endpoint."""
    url = f"{WB_API_BASE}/country"
    params = {"format": "json", "per_page": 400}
    try:
        resp = _SESSION.get(url, params=params, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        payload = resp.json()
    except Exception as exc:  # noqa: BLE001
        raise DataFetchError(f"Could not fetch country metadata from the World Bank API: {exc}") from exc

    if not isinstance(payload, list) or len(payload) < 2:
        raise DataFetchError("Unexpected response shape from the World Bank /country endpoint.")

    rows = []
    for rec in payload[1]:
        region_id = rec.get("region", {}).get("id", "NA")
        income_id = rec.get("incomeLevel", {}).get("id", "NA")
        rows.append(
            {
                "country_code": rec["id"],
                "iso2_code": rec.get("iso2Code") or None,  # for flag images (flag CDNs key by ISO2)
                "country_name": rec["name"],
                # Aggregates (regions, income groups, "World") have region/incomeLevel id == "NA".
                "region": rec["region"]["value"] if region_id != "NA" else None,
                "income_group": rec["incomeLevel"]["value"] if income_id != "NA" else None,
                "is_aggregate": region_id == "NA",
            }
        )
    return _clean_countries(pd.DataFrame(rows))


def _clean_countries(countries: pd.DataFrame) -> pd.DataFrame:
    """The /country endpoint pads some region names with a trailing space ("Sub-Saharan
    Africa ", "Latin America & Caribbean "), unlike the region names in the indicator
    data. Strip them so region names match everywhere (color maps, short labels). The aggregates'
    own names are padded too ("Sub-Saharan Africa " as the name of SSF), so those as well."""
    return countries.assign(**{
        col: countries[col].str.strip() for col in ("region", "income_group", "country_name") if col in countries
    })


@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
def fetch_indicator(series_code: str) -> tuple[pd.DataFrame, dt.date | None]:
    """
    Fetch one indicator, all entities (countries + aggregates), all years (1960-2050),
    from the "Population estimates and projections" source. Handles pagination even
    though a single request with a large per_page normally returns everything at once.
    Also returns the source's release date: the "lastupdated" the API sends with the data
    (None if it's missing).
    """
    url = f"{WB_API_BASE}/sources/{SOURCE_ID}/country/all/series/{series_code}/time/all/data"
    rows: list[dict] = []
    page = 1
    pages = 1
    updated = None
    while page <= pages:
        params = {"format": "json", "per_page": 32000, "page": page}
        try:
            resp = _SESSION.get(url, params=params, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            payload = resp.json()
        except Exception as exc:  # noqa: BLE001
            raise DataFetchError(f"Could not fetch indicator {series_code} from the World Bank API: {exc}") from exc

        pages = payload.get("pages", 1) or 1
        updated = updated or xs.parse_date(payload.get("lastupdated"))
        data = payload.get("source", {}).get("data", [])
        for item in data:
            by_concept = {v["concept"]: v for v in item.get("variable", [])}
            country = by_concept.get("Country")
            time_ = by_concept.get("Time")
            if country is None or time_ is None:
                continue
            value = item.get("value")
            if value is None:
                continue
            try:
                year = int(time_["value"])
            except (TypeError, ValueError):
                continue
            rows.append(
                {
                    "country_code": country["id"],
                    "country_name": country["value"],
                    "year": year,
                    "value": float(value),
                }
            )
        page += 1

    df = pd.DataFrame(rows, columns=["country_code", "country_name", "year", "value"])
    df["series_code"] = series_code
    return df, updated


def _cache_age_seconds(*files: Path) -> float | None:
    """Age of the OLDEST of the given files in seconds, or None if any of them don't exist
    yet -- so a partially-written cache set never reads as fresher than it really is."""
    if not all(f.exists() for f in files):
        return None
    return time.time() - min(f.stat().st_mtime for f in files)


def _read_parquet_if_fresh(*files: Path) -> list[pd.DataFrame] | None:
    """Read all of `files` as parquet if they exist and are within the TTL, else None."""
    age = _cache_age_seconds(*files)
    if age is None or age > CACHE_TTL_SECONDS:
        return None
    try:
        return [pd.read_parquet(f) for f in files]
    except Exception:  # noqa: BLE001 -- a corrupt/unreadable cache just means "fetch over the network instead"
        return None


def _write_parquet_atomic(file_df_pairs: list[tuple[Path, pd.DataFrame]]) -> None:
    """Best-effort write-through to disk. Never raises -- a read-only filesystem just means
    no speedup next time. Writes to temp files then renames, so a process that crashes
    mid-write (or another session reading concurrently) never sees a half-written file."""
    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        tmp_pairs = [(f, f.with_suffix(".tmp"), df) for f, df in file_df_pairs]
        for _, tmp, df in tmp_pairs:
            df.to_parquet(tmp, index=False)
        for f, tmp, _ in tmp_pairs:
            tmp.replace(f)
    except Exception:  # noqa: BLE001
        pass


def _disk_cache_age_seconds() -> float | None:
    """Age of the core population/countries on-disk cache, or None if it doesn't fully exist."""
    return _cache_age_seconds(_DATA_CACHE_FILE, _COUNTRIES_CACHE_FILE)


def _read_disk_cache() -> tuple[pd.DataFrame, pd.DataFrame] | None:
    """Load (df, countries) from the on-disk parquet cache if present, still fresh, AND covers
    every indicator this version of the app expects -- else None. That last check matters
    when the app is redeployed with a new indicator added (as happened when working-age
    population was added here) but the .wb_data_cache directory survives the redeploy on the
    host's filesystem: without it, an old cache missing the new indicator would be trusted as
    complete, silently leaving that indicator's chart empty until the 24h TTL happened to
    expire or someone noticed and clicked "Refresh data". Now a cache like that is treated as
    a miss immediately, so a redeploy self-heals on its very next load."""
    result = _read_parquet_if_fresh(_DATA_CACHE_FILE, _COUNTRIES_CACHE_FILE)
    if result is None:
        return None
    df, countries = result
    if not set(INDICATORS) <= set(df["series_code"].unique()):
        return None
    if "iso2_code" not in countries.columns:  # written before iso2_code was added -- same self-heal
        return None
    if not _cached_update(POPULATION_SOURCE):  # written before release dates were added -- same self-heal
        return None
    return df, _clean_countries(countries)  # caches written before the strip was added


def _write_disk_cache(df: pd.DataFrame, countries: pd.DataFrame) -> None:
    _write_parquet_atomic([(_DATA_CACHE_FILE, df), (_COUNTRIES_CACHE_FILE, countries)])


def clear_disk_cache() -> None:
    """Delete the whole on-disk cache (population + countries + extra sources + release dates). Called
    by the app's "Refresh data" button so a forced refresh actually goes back to the network instead
    of instantly re-reading yesterday's files."""
    shutil.rmtree(_CACHE_DIR, ignore_errors=True)
    with _UPDATES_LOCK:
        _UPDATES.clear()


# --------------------------------------------------------------------------
# Release dates ("Last updated" under the Trends charts)
# --------------------------------------------------------------------------
# Each source's fetch returns its publisher's last release date alongside the data. They're kept
# out of the data tables: the loaders record them here, in memory (_UPDATES, for this process) and
# on disk (_UPDATES_CACHE_FILE, {source key: "YYYY-MM-DD" or null}, next to the data it belongs to).
# A source's disk cache only counts as a hit if its date is recorded (null included), so a cache
# written before the dates existed is refetched once, like the completeness checks above.

_UPDATES: dict[str, dt.date | None] = {}
_UPDATES_LOCK = threading.Lock()  # the extra sources are loaded on several threads


def _read_updates_file() -> dict[str, dt.date | None]:
    try:
        raw = json.loads(_UPDATES_CACHE_FILE.read_text(encoding="utf-8"))
        return {k: dt.date.fromisoformat(v) if v else None for k, v in raw.items()}
    except Exception:  # noqa: BLE001 -- missing or unreadable: no dates on disk
        return {}


def _cached_update(source: str) -> bool:
    """Whether `source`'s release date is on disk (it may be null) -- if not, its data cache is a
    miss. Puts the date in memory too, for source_updates()."""
    on_disk = _read_updates_file()
    if source not in on_disk:
        return False
    with _UPDATES_LOCK:
        _UPDATES[source] = on_disk[source]
    return True


def _record_update(source: str, updated: dt.date | None, *, to_disk: bool = True) -> None:
    """Keep a freshly fetched source's release date: in memory, and on disk (best effort) when its
    data is written there too."""
    with _UPDATES_LOCK:
        _UPDATES[source] = updated
        if not to_disk:
            return
        merged = {k: v.isoformat() if v else None for k, v in {**_read_updates_file(), source: updated}.items()}
        try:
            _CACHE_DIR.mkdir(parents=True, exist_ok=True)
            tmp = _UPDATES_CACHE_FILE.with_suffix(".tmp")
            tmp.write_text(json.dumps(merged, indent=1), encoding="utf-8")
            tmp.replace(_UPDATES_CACHE_FILE)
        except Exception:  # noqa: BLE001 -- a read-only filesystem: memory only
            pass


# Keys in load_population_data()'s errors, alongside the extra sources' keys (xs.SOURCES).
POPULATION_SOURCE = "POP"  # source 40's indicators
COUNTRIES_SOURCE = "COUNTRIES"  # the /country list (names, regions, income groups)
POPULATION_COLUMNS = ["country_code", "country_name", "year", "value", "series_code", "series_name"]
COUNTRIES_COLUMNS = ["country_code", "iso2_code", "country_name", "region", "income_group", "is_aggregate"]


def empty_population_table() -> pd.DataFrame:
    """load_data()'s table with no rows, for when source 40 can't be reached."""
    dtypes = {"year": "int64", "value": float}
    return pd.DataFrame({col: pd.Series(dtype=dtypes.get(col, object)) for col in POPULATION_COLUMNS})


def _stale_countries_cache() -> pd.DataFrame | None:
    """The on-disk countries file whatever its age (None if missing, unreadable or too old a layout)."""
    try:
        countries = pd.read_parquet(_COUNTRIES_CACHE_FILE)
    except Exception:  # noqa: BLE001 -- missing or corrupt: no fallback from here
        return None
    if countries.empty or not set(COUNTRIES_COLUMNS) <= set(countries.columns):
        return None
    return _clean_countries(countries)


def countries_from_dict() -> pd.DataFrame:
    """A minimal country list from country_dict.py (codes and names only: no regions, income groups
    or ISO2 codes), for when the /country endpoint and its disk cache are both unavailable."""
    return pd.DataFrame(
        [{"country_code": code, "iso2_code": None, "country_name": name, "region": None, "income_group": None,
          "is_aggregate": code in cd.AGGREGATES} for code, name in cd.COUNTRIES.items()],
        columns=COUNTRIES_COLUMNS,
    )


def fallback_countries() -> pd.DataFrame:
    """The country list when fetch_countries() fails: the disk cache even if stale, else country_dict's."""
    stale = _stale_countries_cache()
    return stale if stale is not None else countries_from_dict()


def has_country_groups(countries: pd.DataFrame) -> bool:
    """Whether the country list carries regions and income groups (countries_from_dict()'s doesn't)."""
    return bool(countries["region"].notna().any())


def _load_population() -> tuple[pd.DataFrame, pd.DataFrame, dict[str, str]]:
    """
    Every indicator + country metadata as (long_df, countries_df, errors); never raises.

    Checks the on-disk cache first (helps a freshly-started process -- e.g. a
    free-tier host waking a sleeping app -- skip the network entirely). On a
    miss, all len(INDICATORS) + 1 API calls (one per indicator, plus country
    metadata) are independent HTTP requests, so they're issued concurrently
    from a small thread pool instead of one after another: they're I/O-bound
    (waiting on the network), so threading helps here despite the GIL,
    cutting wall-clock time from roughly "the sum of every request" to
    roughly "the slowest single one". The freshly-fetched result is then
    written back to disk for next time.

    A failed indicator fails the whole population source (errors[POPULATION_SOURCE], with an
    empty table), as a failed extra source does. A failed country list
    (errors[COUNTRIES_SOURCE]) falls back to fallback_countries().
    """
    cached = _read_disk_cache()
    if cached is not None:
        return *cached, {}

    errors: dict[str, str] = {}
    updated = None
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(INDICATORS) + 1) as executor:
        countries_future = executor.submit(fetch_countries)
        indicator_futures = [executor.submit(fetch_indicator, code) for code in INDICATORS]
        # .result() re-raises whatever happened in that worker thread.
        try:
            results = [f.result() for f in indicator_futures]
            df = pd.concat([frame for frame, _ in results], ignore_index=True)
            df["series_name"] = df["series_code"].map(INDICATORS)
            updated = xs._latest(date for _, date in results)
        except Exception as exc:  # noqa: BLE001 -- reported in the app
            errors[POPULATION_SOURCE] = f"{type(exc).__name__}: {exc}"
            df = empty_population_table()
        try:
            countries = countries_future.result()
        except Exception as exc:  # noqa: BLE001 -- reported in the app
            errors[COUNTRIES_SOURCE] = f"{type(exc).__name__}: {exc}"
            countries = fallback_countries()

    if POPULATION_SOURCE not in errors:  # on disk only along with its data
        _record_update(POPULATION_SOURCE, updated, to_disk=not errors)
    if not errors:
        _write_disk_cache(df, countries)
    elif COUNTRIES_SOURCE not in errors:  # keep a fresh country list for the stale-cache fallback
        _write_parquet_atomic([(_COUNTRIES_CACHE_FILE, countries)])
    return df, countries, errors


@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
def load_population_data() -> tuple[pd.DataFrame, pd.DataFrame, dict[str, str]]:
    """
    (long_df, countries_df, errors) for the app (see _load_population). A failure is cached in
    memory like a success (24h, until "Refresh data"), so an unreachable API isn't retried on every
    widget interaction; the failed parts are never written to disk.
    """
    return _load_population()


@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
def load_data() -> tuple[pd.DataFrame, pd.DataFrame]:
    """(long_df, countries_df), raising DataFetchError if any part failed (load_population_data()
    is the app's never-raising version)."""
    df, countries, errors = _load_population()
    if errors:
        raise DataFetchError("; ".join(f"{k}: {v}" for k, v in errors.items()))
    return df, countries


# --------------------------------------------------------------------------
# Economic and other indicators (extra_sources.py): WDI, IMF, ND-GAIN,
# WHR, ECI, UNDP, ILO, SWIID, PIP
# --------------------------------------------------------------------------

EXTRA_SERIES: dict[str, str] = xs.SERIES  # series_code -> name, e.g. "IMF:NGDP_RPCH"
EXTRA_SOURCES: dict[str, str] = {name: src["label"] for name, src in xs.SOURCES.items()}


def _extra_cache_file(source: str) -> Path:
    return _CACHE_DIR / f"extra_{source.lower()}.parquet"


def _read_extra_cache(source: str) -> pd.DataFrame | None:
    """One source's on-disk cache if fresh and it holds every series this version expects for
    that source -- the same self-heal as _read_disk_cache when a series is added."""
    result = _read_parquet_if_fresh(_extra_cache_file(source))
    if result is None:
        return None
    (df,) = result
    if not set(xs.series_of(source)) <= set(df["series_code"].unique()):
        return None
    if not _cached_update(source):  # written before release dates were added: refetched
        return None
    return df


@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
def load_extra_data() -> tuple[pd.DataFrame, dict[str, str]]:
    """
    Every extra source as one long table (extra_sources.SCHEMA), plus {source: error message}
    for the sources that failed. As with load_population_data(), a failure doesn't stop the app:
    these sources are separate publishers (some block scripted downloads from time to time), so a
    failed one only leaves its own charts empty, with a warning. Each source is cached on disk
    separately, so only failed or stale sources are refetched, concurrently. A failure is
    cached in memory like a success (24h, until "Refresh data"), so a publisher that is down
    isn't retried on every widget interaction.
    """
    frames, errors, missing = [], {}, []
    for source in xs.SOURCES:
        cached = _read_extra_cache(source)
        if cached is None:
            missing.append(source)
        else:
            frames.append(cached)
    if missing:
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(missing)) as executor:
            futures = {s: executor.submit(xs.SOURCES[s]["fetch"], _SESSION) for s in missing}
            for source, future in futures.items():
                try:
                    df, updated = future.result()
                except Exception as exc:  # noqa: BLE001 -- reported in the app, per source
                    errors[source] = f"{type(exc).__name__}: {exc}"
                    continue
                frames.append(df)
                _write_parquet_atomic([(_extra_cache_file(source), df)])
                _record_update(source, updated)
    xdf = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=xs.SCHEMA)
    return xdf, errors


@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
def source_updates() -> dict[str, dt.date | None]:
    """
    {source key: release date or None} for the population data (POPULATION_SOURCE) and every extra
    source (xs.SOURCES keys): when the publisher last released it, not when the app fetched it.
    None for a source that failed or whose date couldn't be read. Loads the data first (both loads
    are cached, so normally free), which records the dates. Cached like the data (24h, until
    "Refresh data").
    """
    load_population_data()
    load_extra_data()
    on_disk = _read_updates_file()
    with _UPDATES_LOCK:
        return {key: _UPDATES.get(key, on_disk.get(key)) for key in (POPULATION_SOURCE, *xs.SOURCES)}


# --------------------------------------------------------------------------
# Generic helpers
# --------------------------------------------------------------------------

def real_country_codes(countries: pd.DataFrame) -> list[str]:
    """All actual countries (excludes World, regions, and income-group aggregates)."""
    return countries.loc[~countries["is_aggregate"], "country_code"].unique().tolist()


# --------------------------------------------------------------------------
# Tab transforms
# --------------------------------------------------------------------------

@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False, hash_funcs=_DF_HASH_FUNCS)
def trends_data(df: pd.DataFrame, entity_code: str) -> pd.DataFrame:
    """
    Everything the Trends tab charts for one entity (World, a region, an income group or a
    country), year-indexed. Raw indicators keep their series code as the column name; the
    derived columns are:
      births, deaths        crude rate (per 1,000) * population / 1,000  (people)
      natural_increase       births - deaths (people)
    """
    sub = df[df["country_code"] == entity_code]
    wide = sub.pivot_table(index="year", columns="series_code", values="value").sort_index()
    wide = wide.reindex(columns=list(INDICATORS))  # every column present, even with no data
    pop = wide["SP.POP.TOTL"]
    # Birth/death rates are forecast only every 5 years (2030, 2035, ...), so these three
    # columns are empty for the forecast years in between.
    wide["births"] = wide["SP.DYN.CBRT.IN"] * pop / 1000
    wide["deaths"] = wide["SP.DYN.CDRT.IN"] * pop / 1000
    wide["natural_increase"] = wide["births"] - wide["deaths"]
    return wide


@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False, hash_funcs=_DF_HASH_FUNCS)
def extra_trends_data(xdf: pd.DataFrame, entity_code: str) -> pd.DataFrame:
    """trends_data's counterpart for the extra sources: one entity, year-indexed, one column per
    EXTRA_SERIES code (all present, empty where a source has no data for this entity)."""
    sub = xdf[xdf["country_code"] == entity_code]
    if sub.empty:
        return pd.DataFrame(columns=list(EXTRA_SERIES), dtype=float)
    wide = sub.pivot_table(index="year", columns="series_code", values="value").sort_index()
    return wide.reindex(columns=list(EXTRA_SERIES))


@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False, hash_funcs=_DF_HASH_FUNCS)
def projection_starts(xdf: pd.DataFrame) -> dict[str, float]:
    """series_code -> split point before its first projected year (e.g. 2024.5), for the extra
    series that carry projections (IMF). Like forecast_start() for the population data."""
    projected = xdf[xdf["is_projection"].astype(bool)]
    return (projected.groupby("series_code")["year"].min() - 0.5).astype(float).to_dict()


# Indicators computed from the fetched series, usable wherever a series code is (see
# country_indicator_wide). Both per 1,000 population.
NATURAL_CHANGE_RATE = "natural_change_rate"  # crude birth rate - crude death rate
NET_MIGRATION_RATE = "net_migration_rate"  # net migration / total population * 1,000


@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False, hash_funcs=_DF_HASH_FUNCS)
def country_indicator_wide(df: pd.DataFrame, countries: pd.DataFrame, series_code: str) -> pd.DataFrame:
    """
    One indicator for every real country: rows = country_code, columns = years (only years
    with any data). df is load_data()'s table, or load_extra_data()'s for an EXTRA_SERIES code
    (only countries in the World Bank's country list are kept either way). series_code can also be one of the derived indicators above; they only
    cover years where every input has a value (e.g. birth/death rates are forecast only every
    5 years, so the natural change rate is too).
    """
    if series_code == NATURAL_CHANGE_RATE:
        wide = (country_indicator_wide(df, countries, "SP.DYN.CBRT.IN")
                - country_indicator_wide(df, countries, "SP.DYN.CDRT.IN"))
    elif series_code == NET_MIGRATION_RATE:
        wide = (country_indicator_wide(df, countries, "SM.POP.NETM")
                / country_indicator_wide(df, countries, "SP.POP.TOTL") * 1000)
    else:
        codes = real_country_codes(countries)
        sub = df[(df["series_code"] == series_code) & (df["country_code"].isin(codes))]
        wide = sub.pivot_table(index="country_code", columns="year", values="value")
    return wide.dropna(axis=1, how="all")
