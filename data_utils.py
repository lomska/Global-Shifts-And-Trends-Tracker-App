"""
Data access layer for the Global Shifts Tracker app: loading, caching and the pandas
transforms behind the charts. What each source is and how it's downloaded lives in sources.py; every
source comes back as one long table (sources.SCHEMA), so the app works with one table, `data`, 
from load_data(). The country list (names, regions, income groups) is reference data rather 
than a source of series: load_countries().

Two layers of caching sit in front of the network:
  1. st.cache_data -- an in-memory cache for the lifetime of the running
     process. Free, but lost whenever the process restarts (a redeploy, or a
     free-tier host waking a sleeping app).
  2. Small on-disk parquet files next to this file, one per source plus the country list --
     they survive a process restart as long as the underlying filesystem does. When a source's
     file is present, still fresh and complete, a freshly-started process skips that source's
     network fetch entirely.
Both layers share the same TTL, and both are best-effort: if the filesystem
turns out to be read-only or ephemeral on a given host, the disk layer just
quietly never hits, and the app fetches over the network (in parallel) every
time the in-memory cache is cold.

A third, separate kind of caching applies to the pandas transform functions
below (trends_data, country_indicator_wide, projection_starts): st.tabs isn't lazy, so a full
run of the script builds both tabs (app.py makes each tab an st.fragment, so a
widget inside one reruns only that tab), which would otherwise redo every one
of these pivots/groupbys each time. They're
cached with @st.cache_data using a cheap custom fingerprint (see
_fast_df_fingerprint) instead of Streamlit's default full-content hash --
hashing the several-hundred-thousand-row table byte-for-byte costs more than most of these
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
import math
import os
import shutil
import threading
import time
from pathlib import Path

import pandas as pd
import requests
import streamlit as st

import country_dict as cd
import sources as ds

REQUEST_TIMEOUT = 60
CACHE_TTL_SECONDS = 60 * 60 * 24  # 24h -- shared by st.cache_data and the on-disk cache

# A shared Session reuses TCP/TLS connections across the requests to each host. Every source's
# fetch gets it (load_data), and the tests patch its get().
_SESSION = requests.Session()

# On-disk cache: parquet files next to this module, plus their mtime as the
# freshness signal (no separate metadata file needed). WB_DATA_CACHE_DIR overrides
# the location -- the test suite sets it (in tests/_pathfix.py) so its fake data
# never lands in the cache the real app reads.
_CACHE_DIR = Path(os.environ.get("WB_DATA_CACHE_DIR") or Path(__file__).resolve().parent / ".wb_data_cache")
_COUNTRIES_CACHE_FILE = _CACHE_DIR / "countries.parquet"
_UPDATES_CACHE_FILE = _CACHE_DIR / "source_updates.json"  # release dates, see source_updates()

# Every series the app can chart (code -> name) and every source (key -> label), from sources.py.
SERIES: dict[str, str] = ds.SERIES
SOURCE_LABELS: dict[str, str] = {key: source["label"] for key, source in ds.SOURCES.items()}
POPULATION_SOURCE = ds.POPULATION  # "POP": the population data's key, as in load_data()'s errors
COUNTRIES_SOURCE = "COUNTRIES"  # the /country list's key in load_countries()'s errors

# Population series the transforms below compute with.
POP_TOTAL, NET_MIGRATION = "POP:SP.POP.TOTL", "POP:SM.POP.NETM"
BIRTH_RATE, DEATH_RATE = "POP:SP.DYN.CBRT.IN", "POP:SP.DYN.CDRT.IN"

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

# Colors: #2057a7 (blue) and #f2bc40 (yellow) are the two primary colors (first and second series), with a set
# of grays for gridlines, captions and text; chart style: app.style_fig.
DENIM, SCOOTER, OLD_ROSE, GOLDEN_SAND = "#2057a7", "#1e87a5", "#c43d4d", "#f2bc40"
MOODY_BLUE, GENOA, BURNT_SIENNA, TROLLEY_GREY = "#8980cb", "#287c6f", "#e07653", "#808080"
BLACK = "#000000"
# Grays, light to dark: "shaded area", "light grid", "caption", "subtitle/body", "title".
WHISPER, LIGHT_GREY, SUVA_GREY, MATTERHORN, NERO = "#ebebeb", "#d3d3d3", "#909090", "#505050", "#202020"
# Categorical series, in order: blue, yellow, black, gray, red, green, dark gray, orange.
CATEGORICAL_COLORS = [DENIM, GOLDEN_SAND, NERO, LIGHT_GREY, OLD_ROSE, GENOA, MATTERHORN, BURNT_SIENNA]
# Maps: a blue sequential ramp (#bfddff to #032461, light to dark), and a yellow-to-blue diverging
# palette from the yellows (negative, #735000 to #ffeb6e, dark to light) through a neutral near-white
# (#f5f5f5) at 0 into the blues (positive, light to dark). The neutral midpoint keeps values near 0 from blending into a muddy gray.
SEQUENTIAL_RAMP = ["#bfddff", "#a7c4fd", "#8aadfe", "#7397ef", "#5784d4", "#456ebe", "#215dad", "#064896",
                   "#02397d", "#032461"]
DIVERGING = ["#735000", "#a27601", "#d29f1f", "#fbcf4f", "#ffeb6e", "#f5f5f5",
             "#bfddff", "#8aadfe", "#5784d4", "#215dad", "#02397d"]
GRID_COLOR = LIGHT_GREY  # horizontal gridlines only

# Distributions table region labels: four palette colors other than the two primary ones (#2057a7,
# #f2bc40), then three grays. Region order is the World Bank's (alphabetical), so each
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
# no change. #2057a7 reads well as text on white; #f2bc40 doesn't, so the down arrow takes a
# darker step of the yellow ramp, #8a5f00 (WCAG AA contrast).
CHANGE_UP_COLOR, CHANGE_DOWN_COLOR, NO_CHANGE_COLOR = DENIM, "#8a5f00", TROLLEY_GREY
REPLACEMENT_LEVEL = 2.1  # births per woman
# Reference marks: drawn on the Trends chart and the
# Distributions histogram of their indicator.
U5_MORTALITY_TARGET = 25  # deaths per 1,000 live births: SDG target 3.2, by 2030
POVERTY_TARGET = 3  # % of the world's population below $3.00 a day: World Bank goal for 2030
EDUCATION_SPENDING_BENCHMARK = (4, 6)  # % of GDP: Education 2030 Framework for Action


# --------------------------------------------------------------------------
# Derived series: computed from the fetched ones, usable wherever a series code is
# --------------------------------------------------------------------------
# POP-prefixed, so sources.source_of() names the population data as their source. trends_data()
# adds the first three as columns; country_indicator_wide() computes the two rates.
BIRTHS = "POP:births"  # crude birth rate (per 1,000) * population / 1,000 (people)
DEATHS = "POP:deaths"  # crude death rate (per 1,000) * population / 1,000 (people)
NATURAL_INCREASE = "POP:natural_increase"  # births - deaths (people)
NATURAL_CHANGE_RATE = "POP:natural_change_rate"  # crude birth rate - crude death rate (per 1,000)
NET_MIGRATION_RATE = "POP:net_migration_rate"  # net migration / total population * 1,000
# Each derived series' projections start where the series it's computed from start (series_split).
DERIVED_FROM: dict[str, str] = {BIRTHS: BIRTH_RATE, DEATHS: DEATH_RATE, NATURAL_INCREASE: BIRTH_RATE,
                                NATURAL_CHANGE_RATE: BIRTH_RATE, NET_MIGRATION_RATE: NET_MIGRATION}


def _fast_df_fingerprint(d: pd.DataFrame):
    """Cheap stand-in for st.cache_data's default DataFrame hash (shape + column
    names + a sum over numeric columns) -- see the module docstring for why."""
    numeric = d.select_dtypes("number")
    numeric_sum = float(numeric.sum().sum()) if not numeric.empty else 0.0
    return (d.shape, tuple(d.columns), numeric_sum)


# Passed as hash_funcs to every @st.cache_data transform below that takes a table.
_DF_HASH_FUNCS = {pd.DataFrame: _fast_df_fingerprint}


class DataFetchError(RuntimeError):
    """Raised when the World Bank API cannot be reached or returns something unexpected."""


# --------------------------------------------------------------------------
# On-disk cache helpers
# --------------------------------------------------------------------------

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


def clear_disk_cache() -> None:
    """Delete the whole on-disk cache (every source, the country list and the release dates). Called
    by the app's "Refresh data" button so a forced refresh actually goes back to the network instead
    of instantly re-reading yesterday's files."""
    shutil.rmtree(_CACHE_DIR, ignore_errors=True)
    with _UPDATES_LOCK:
        _UPDATES.clear()


# --------------------------------------------------------------------------
# Release dates ("Last updated" under the Trends charts)
# --------------------------------------------------------------------------
# Each source's fetch returns its publisher's last release date alongside the data. They're kept
# out of the data table: load_data() records them here, in memory (_UPDATES, for this process) and
# on disk (_UPDATES_CACHE_FILE, {source key: "YYYY-MM-DD" or null}, next to the data it belongs to).
# A source's disk cache only counts as a hit if its date is recorded (null included), so a cache
# written before the dates existed is refetched once, like the completeness check below.

_UPDATES: dict[str, dt.date | None] = {}
_UPDATES_LOCK = threading.Lock()  # the sources are loaded on several threads


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


def _record_update(source: str, updated: dt.date | None) -> None:
    """Keep a freshly fetched source's release date: in memory, and on disk (best effort) next to its data."""
    with _UPDATES_LOCK:
        _UPDATES[source] = updated
        merged = {k: v.isoformat() if v else None for k, v in {**_read_updates_file(), source: updated}.items()}
        try:
            _CACHE_DIR.mkdir(parents=True, exist_ok=True)
            tmp = _UPDATES_CACHE_FILE.with_suffix(".tmp")
            tmp.write_text(json.dumps(merged, indent=1), encoding="utf-8")
            tmp.replace(_UPDATES_CACHE_FILE)
        except Exception:  # noqa: BLE001 -- a read-only filesystem: memory only
            pass


# --------------------------------------------------------------------------
# Country list (names, regions, income groups, ISO2 codes for the flags)
# --------------------------------------------------------------------------

COUNTRIES_COLUMNS = ["country_code", "iso2_code", "country_name", "region", "income_group", "is_aggregate"]


def fetch_countries() -> pd.DataFrame:
    """Country/region/income-group metadata from the World Bank /country endpoint."""
    url = f"{ds.WB_API_BASE}/country"
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
                "iso2_code": rec.get("iso2Code") or None,  # for flag images (flag files are keyed by ISO2)
                "country_name": rec["name"],
                # Aggregates (regions, income groups, "World") have region/incomeLevel id == "NA".
                "region": rec["region"]["value"] if region_id != "NA" else None,
                "income_group": rec["incomeLevel"]["value"] if income_id != "NA" else None,
                "is_aggregate": region_id == "NA",
            }
        )
    return _clean_countries(pd.DataFrame(rows, columns=COUNTRIES_COLUMNS))


def _clean_countries(countries: pd.DataFrame) -> pd.DataFrame:
    """The /country endpoint pads some region names with a trailing space ("Sub-Saharan
    Africa ", "Latin America & Caribbean "), unlike the region names in the indicator
    data. Strip them so region names match everywhere (color maps, short labels). The aggregates'
    own names are padded too ("Sub-Saharan Africa " as the name of SSF), so those as well."""
    return countries.assign(**{
        col: countries[col].str.strip() for col in ("region", "income_group", "country_name") if col in countries
    })


def _read_countries_cache(fresh_only: bool = True) -> pd.DataFrame | None:
    """The on-disk country list: only if still fresh (fresh_only), or whatever its age (the fallback when
    the endpoint is down). None if missing, unreadable, or written before a column was added (iso2_code,
    for the flags): such a file is a miss, so it self-heals on the next load."""
    try:
        if fresh_only:
            result = _read_parquet_if_fresh(_COUNTRIES_CACHE_FILE)
            if result is None:
                return None
            (countries,) = result
        else:
            countries = pd.read_parquet(_COUNTRIES_CACHE_FILE)
    except Exception:  # noqa: BLE001 -- missing or corrupt
        return None
    if countries.empty or not set(COUNTRIES_COLUMNS) <= set(countries.columns):
        return None
    return _clean_countries(countries)  # files written before the strip was added


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
    stale = _read_countries_cache(fresh_only=False)
    return stale if stale is not None else countries_from_dict()


def has_country_groups(countries: pd.DataFrame) -> bool:
    """Whether the country list carries regions and income groups (countries_from_dict()'s doesn't)."""
    return bool(countries["region"].notna().any())


@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
def load_countries() -> tuple[pd.DataFrame, dict[str, str]]:
    """
    (countries, errors); never raises. The on-disk copy if fresh, else the /country endpoint (written to
    disk). If the endpoint fails: errors[COUNTRIES_SOURCE] and fallback_countries(). A failure is cached in
    memory like a success (24h, until "Refresh data"), so an unreachable API isn't retried on every
    widget interaction.
    """
    cached = _read_countries_cache()
    if cached is not None:
        return cached, {}
    try:
        countries = fetch_countries()
    except Exception as exc:  # noqa: BLE001 -- reported in the app
        return fallback_countries(), {COUNTRIES_SOURCE: f"{type(exc).__name__}: {exc}"}
    _write_parquet_atomic([(_COUNTRIES_CACHE_FILE, countries)])
    return countries, {}


# --------------------------------------------------------------------------
# The data: every source in sources.SOURCES, as one long table
# --------------------------------------------------------------------------

def _source_cache_file(source: str) -> Path:
    return _CACHE_DIR / f"source_{source.lower()}.parquet"


def _read_source_cache(source: str) -> pd.DataFrame | None:
    """One source's on-disk cache if fresh AND it holds every series this version of the app expects
    from that source -- else None. The completeness check matters when the app is redeployed with a
    new series added (as happened when working-age population was added) but the .wb_data_cache
    directory survives the redeploy on the host's filesystem: without it, an old cache missing the new
    series would be trusted as complete, silently leaving that chart empty until the 24h TTL happened to
    expire or someone clicked "Refresh data". Now a cache like that is a miss, so a redeploy self-heals
    on its very next load."""
    result = _read_parquet_if_fresh(_source_cache_file(source))
    if result is None:
        return None
    (table,) = result
    if not set(ds.series_of(source)) <= set(table["series_code"].unique()):
        return None
    if not _cached_update(source):  # written before release dates were added: refetched
        return None
    return table


def empty_data() -> pd.DataFrame:
    """load_data()'s table with no rows."""
    return pd.DataFrame(columns=ds.SCHEMA)


@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
def load_data() -> tuple[pd.DataFrame, dict[str, str]]:
    """
    Every source as one long table (sources.SCHEMA), plus {source key: error message} for the sources
    that failed; never raises. A failure doesn't stop the app: the sources are separate publishers (some
    block scripted downloads from time to time), so a failed one only leaves its own charts empty, with a
    warning. Each source is cached on disk separately, so only failed or stale sources are refetched,
    concurrently (I/O-bound requests, so threads help despite the GIL). A failure is cached in memory like
    a success (24h, until "Refresh data"), so a publisher that is down isn't retried on every widget
    interaction; it is never written to disk.
    """
    frames, errors, missing = [], {}, []
    for source in ds.SOURCES:
        cached = _read_source_cache(source)
        if cached is None:
            missing.append(source)
        else:
            frames.append(cached)
    if missing:
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(missing)) as executor:
            futures = {s: executor.submit(ds.SOURCES[s]["fetch"], _SESSION) for s in missing}
            for source, future in futures.items():
                try:
                    table, updated = future.result()
                except Exception as exc:  # noqa: BLE001 -- reported in the app, per source
                    errors[source] = f"{type(exc).__name__}: {exc}"
                    continue
                frames.append(table)
                _write_parquet_atomic([(_source_cache_file(source), table)])
                _record_update(source, updated)
    data = pd.concat(frames, ignore_index=True) if frames else empty_data()
    return data, errors


@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
def source_updates() -> dict[str, dt.date | None]:
    """
    {source key: release date or None} for every source in sources.SOURCES: when the publisher last
    released it, not when the app fetched it. None for a source that failed or whose date couldn't be
    read. Loads the data first (cached, so normally free), which records the dates. Cached like the data
    (24h, until "Refresh data").
    """
    load_data()
    on_disk = _read_updates_file()
    with _UPDATES_LOCK:
        return {key: _UPDATES.get(key, on_disk.get(key)) for key in ds.SOURCES}


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
def trends_data(data: pd.DataFrame, entity_code: str) -> pd.DataFrame:
    """
    Everything the Trends tab charts for one entity (World, a region, an income group or a country),
    year-indexed: one column per SERIES code (all present, empty where a source has no data for this
    entity), plus the derived BIRTHS, DEATHS and NATURAL_INCREASE columns.
    """
    sub = data[data["country_code"] == entity_code]
    if sub.empty:
        wide = pd.DataFrame(columns=list(SERIES), dtype=float)
    else:
        wide = sub.pivot_table(index="year", columns="series_code", values="value").sort_index()
        wide = wide.reindex(columns=list(SERIES))
    pop = wide[POP_TOTAL]
    # Birth/death rates are projected only every 5 years (2030, 2035, ...), so these three
    # columns are empty for the projection years in between.
    wide[BIRTHS] = wide[BIRTH_RATE] * pop / 1000
    wide[DEATHS] = wide[DEATH_RATE] * pop / 1000
    wide[NATURAL_INCREASE] = wide[BIRTHS] - wide[DEATHS]
    return wide


@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False, hash_funcs=_DF_HASH_FUNCS)
def projection_starts(data: pd.DataFrame) -> dict[str, float]:
    """
    series_code -> where its projections start, for every series with projected rows (is_projection):
    the midpoint after its last observed year before the first projected one (e.g. 2024.5 for
    projections from 2025). For a series whose projections skip years (birth rates: 2024, then 2030),
    that is still right after the last observed year, so every projection shows as one.
    """
    flags = data["is_projection"].astype(bool)
    first_projected = data[flags].groupby("series_code")["year"].min()
    observed = data.loc[~flags, ["series_code", "year"]]
    observed = observed[observed["year"] < observed["series_code"].map(first_projected)]
    last_observed = observed.groupby("series_code")["year"].max()
    return {code: float(last_observed[code] + 0.5) if code in last_observed.index else float(first - 0.5)
            for code, first in first_projected.items()}


@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False, hash_funcs=_DF_HASH_FUNCS)
def series_ranges(data: pd.DataFrame) -> pd.DataFrame:
    """Each series' (min, max) over every country and year: index series_code, columns min / max."""
    return data.groupby("series_code")["value"].agg(["min", "max"])


# The last table series_split() saw and its projection_starts(): a run asks once per chart, and even a
# cache hit fingerprints the whole table, so the lookup is kept for as long as the same table object is
# passed (one run: st.cache_data hands each run its own copy). One entry, replaced atomically.
_LAST_SPLITS: tuple[pd.DataFrame | None, dict[str, float]] = (None, {})


def series_split(series_code: str, data: pd.DataFrame) -> float:
    """Where a series' projections start (projection_starts; a derived series follows the series it's
    computed from), or math.inf for a series without projections."""
    global _LAST_SPLITS
    table, splits = _LAST_SPLITS
    if table is not data:
        splits = projection_starts(data)
        _LAST_SPLITS = (data, splits)
    return splits.get(DERIVED_FROM.get(series_code, series_code), math.inf)


@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False, hash_funcs=_DF_HASH_FUNCS)
def country_indicator_wide(data: pd.DataFrame, countries: pd.DataFrame, series_code: str) -> pd.DataFrame:
    """
    One indicator for every real country: rows = country_code, columns = years (only years
    with any data). Only countries in the World Bank's country list are kept. series_code can also
    be NATURAL_CHANGE_RATE or NET_MIGRATION_RATE; they only cover years where every input has a value
    (e.g. birth/death rates are projected only every 5 years, so the natural change rate is too).
    """
    if series_code == NATURAL_CHANGE_RATE:
        wide = (country_indicator_wide(data, countries, BIRTH_RATE)
                - country_indicator_wide(data, countries, DEATH_RATE))
    elif series_code == NET_MIGRATION_RATE:
        wide = (country_indicator_wide(data, countries, NET_MIGRATION)
                / country_indicator_wide(data, countries, POP_TOTAL) * 1000)
    else:
        codes = real_country_codes(countries)
        sub = data[(data["series_code"] == series_code) & (data["country_code"].isin(codes))]
        wide = sub.pivot_table(index="country_code", columns="year", values="value")
    return wide.dropna(axis=1, how="all")
