"""
Economic and other country indicators from sources other than the World Bank's population
database: download + reshape, one function per source. The file layouts were checked against the
live sources on 27 September 2026 (IMF SDMX CSV columns, ND-GAIN zip paths) and, for the sources
added on 28 September 2026 (World Happiness Report, Harvard ECI, UNDP, ILOSTAT, SWIID, World Bank
PIP), on that day.

Every fetch_* function takes the requests session to use (data_utils passes its shared _SESSION,
which the tests patch) and returns (table, release date). The release date (datetime.date, or None
when the publisher's metadata can't be read) is when the publisher last released the source, shown
as "Last updated" under the Trends charts; where each one comes from is listed in CLAUDE.md. A
missing or failed date never fails the fetch (_release_date). The table is one long table:

  series_code    source prefix + code, e.g. "WB:SL.UEM.TOTL.ZS", "IMF:NGDP_RPCH", "NDGAIN:GAIN"
  series_name    SERIES[series_code]
  year           int
  country_code   unified code from country_dict (country ISO3 or one of the 12 WB aggregates)
  country_name   unified name from country_dict
  value          float, never NaN
  is_projection  True for projections (IMF WEO, ILO modelled estimates) and nowcasts (PIP), else False

Aggregates are never computed: World, regions and income groups appear only where a source
publishes them (WDI: all 12; IMF: World).
Series made of modelled or imputed values rather than observations are listed in
ESTIMATE_NOTES, whose note the app shows under their charts.
Caching and error handling live in data_utils.load_extra_data().
"""

from __future__ import annotations

import concurrent.futures
import datetime as dt
import io
import logging
import re
import time
import zipfile

import pandas as pd
import requests

import country_dict as cd

log = logging.getLogger(__name__)

SCHEMA = ["series_code", "series_name", "year", "country_code", "country_name", "value", "is_projection"]
FIRST_YEAR = 1960  # same start as the population data
TIMEOUT = 180

# Browser-like headers: some publisher sites refuse requests that don't look like a browser.
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"),
    "Accept-Language": "en-US,en;q=0.9",
}

# --------------------------------------------------------------------------
# Series catalog: code -> name. The app's charts and Distributions list refer to these codes.
# --------------------------------------------------------------------------

WDI_SERIES = {
    "SL.UEM.TOTL.ZS": "Unemployment, total (% of labor force, modelled ILO estimate)",
    # Read with unemployment: people who give up looking leave the labour force
    "SL.TLF.CACT.ZS": "Labor force participation rate, total (% of population ages 15+, modelled ILO estimate)",
    # How expensive a country is compared with the US (US = 100): unlike the exchange rate, comparable
    # across countries. Replaced the archived ratio PA.NUS.PPPC.RF
    # (same measure, US = 1), which the API no longer serves. Revised with each ICP round (base 2021).
    "PA.NUS.GDP.PLI": "Price level index (GDP), US = 100",
    # Economic structure by sector (added 29 Sep 2026). Industry includes mining, utilities and
    # construction; GDP shares don't sum to 100% (net product taxes), employment shares do.
    "NV.AGR.TOTL.ZS": "Agriculture, forestry, and fishing, value added (% of GDP)",
    "NV.IND.TOTL.ZS": "Industry (including construction), value added (% of GDP)",
    "NV.SRV.TOTL.ZS": "Services, value added (% of GDP)",
    "SL.AGR.EMPL.ZS": "Employment in agriculture (% of total employment, modelled ILO estimate)",
    "SL.IND.EMPL.ZS": "Employment in industry (% of total employment, modelled ILO estimate)",
    "SL.SRV.EMPL.ZS": "Employment in services (% of total employment, modelled ILO estimate)",
    "NV.IND.MANF.ZS": "Manufacturing, value added (% of GDP)",  # SDG indicator 9.2.1
    # UNIDO, SDG 9.b.1: domestic production, so unlike high-tech exports (dropped) not inflated by
    # assembly of imported components
    "NV.MNF.TECH.ZS.UN": "Medium and high-tech manufacturing value added (% manufacturing value added)",
    # UN Comtrade (SITC 5-8): the export-side counterpart of manufacturing's share of GDP
    "TX.VAL.MANF.ZS.UN": "Manufactures exports (% of merchandise exports)",
    "SE.TER.ENRR": "School enrollment, tertiary (% gross)",
    "GB.XPD.RSDV.GD.ZS": "Research and development expenditure (% of GDP)",
    "IT.NET.USER.ZS": "Individuals using the Internet (% of population)",
    # added 28 Sep 2026
    "NY.GDP.PCAP.PP.KD": "GDP per capita, PPP (constant 2021 international $)",
    "NY.GDP.MKTP.PP.KD": "GDP, PPP (constant 2021 international $)",
    # Real and PPP-adjusted, like GDP per capita: not Atlas (current US$),
    # which mixes real change with US inflation and exchange-rate swings.
    "NY.GNP.PCAP.PP.KD": "GNI per capita, PPP (constant 2021 international $)",
    "SH.XPD.CHEX.GD.ZS": "Current health expenditure (% of GDP)",  # WHO Global Health Expenditure Database
    "SH.XPD.OOPC.CH.ZS": "Out-of-pocket expenditure (% of current health expenditure)",
    "SH.H2O.BASW.ZS": "People using at least basic drinking water services (% of population)",
    "SH.STA.BASS.ZS": "People using at least basic sanitation services (% of population)",
    "SH.STA.HYGN.ZS": "People with basic handwashing facilities including soap and water (% of population)",
    "EG.ELC.ACCS.ZS": "Access to electricity (% of population)",
    "EG.CFT.ACCS.ZS": "Access to clean fuels and technologies for cooking (% of population)",
    "EG.IMP.CONS.ZS": "Energy imports, net (% of energy use)",
    # EDGAR (European Commission JRC): six Kyoto gases incl. agriculture, excl. land use and forestry.
    # Not Our World in Data's GHG columns: one leaves agriculture out
    # (a near-duplicate of CO2), the other includes volatile deforestation.
    "EN.GHG.ALL.PC.CE.AR5": "Total greenhouse gas emissions excl. LULUCF per capita (t CO2e/capita)",
    # Added 2026-09-30 (user's decision): total emissions (who drives the
    # global total; size-driven, so log-scaled maps), the renewable share (SDG 7.2.1: how clean the
    # energy is) and forest cover (SDG 15.1.1: the land side, which the GHG series leave out).
    "EN.GHG.ALL.MT.CE.AR5": "Total greenhouse gas emissions excl. LULUCF (Mt CO2e)",
    "EG.FEC.RNEW.ZS": "Renewable energy consumption (% of total final energy consumption)",
    "AG.LND.FRST.ZS": "Forest area (% of land area)",
    # SDG 7.3.1 (Tracking SDG7), MJ per constant-PPP $ of GDP; lower is better. Replaced GDP per unit of
    # energy use (the inverse in kg of oil equivalent).
    "EG.EGY.PRIM.PP.KD": "Energy intensity level of primary energy (MJ/$2021 PPP GDP)",
    "FS.AST.PRVT.GD.ZS": "Domestic credit to private sector (% of GDP)",
    "BX.KLT.DINV.WD.GD.ZS": "Foreign direct investment, net inflows (% of GDP)",
    "SE.XPD.TOTL.GD.ZS": "Government expenditure on education, total (% of GDP)",
}
IMF_SERIES = {
    "NGDP_RPCH": "Real GDP growth (annual % change)",
    "PCPIPCH": "Inflation, average consumer prices (annual % change)",
    "GGR_NGDP": "General government revenue (% of GDP)",
    "GGX_NGDP": "General government total expenditure (% of GDP)",
    "BCA_NGDPD": "Current account balance (% of GDP)",
    "GGXCNL_NGDP": "General government net lending/borrowing (% of GDP)",
    "GGXWDG_NGDP": "General government gross debt (% of GDP)",
}
NDGAIN_SERIES = {  # zip member "<folder>/<file>" -> (code, name)
    "gain/gain.csv": ("NDGAIN:GAIN", "ND-GAIN Index (0-100)"),
    "vulnerability/vulnerability.csv": ("NDGAIN:VULNERABILITY", "ND-GAIN Vulnerability score (0-1)"),
    "readiness/readiness.csv": ("NDGAIN:READINESS", "ND-GAIN Readiness score (0-1)"),
}
ILO_SERIES = {  # ILOSTAT indicator id -> (code, name)
    "LAP_2GDP_NOC_RT_A": ("ILO:LABOUR_SHARE", "Labour income share (% of GDP, ILO modelled estimate)"),
    "EIP_2EET_SEX_RT_A": ("ILO:NEET", "Youth not in employment, education or training "
                                      "(% of youth aged 15-24, ILO modelled estimate)"),
}
SINGLE_SERIES = {  # sources with one series each
    "WHR:LADDER": "Happiness: life evaluation, Cantril ladder 0-10 (3-year average)",
    "ECI:ECI": "Economic Complexity Index (Harvard Growth Lab)",
    "UNDP:MYS": "Mean years of schooling (adults 25+)",
    # A child entering school now, if current enrollment rates persist (UNDP caps it at 18 in the HDI)
    "UNDP:EYS": "Expected years of schooling (children entering school)",
    "SWIID:GINI_DISP": "Income inequality: Gini index of disposable income (0-100, SWIID)",
    "PIP:POV_3_00": "Poverty headcount ratio at $3.00 a day (2021 PPP, % of population)",
    "PIP:MEDIAN": "Median income or consumption per day (2021 PPP $)",
}

SERIES: dict[str, str] = {
    **{f"WB:{k}": v for k, v in WDI_SERIES.items()},
    **{f"IMF:{k}": v for k, v in IMF_SERIES.items()},
    **dict(NDGAIN_SERIES.values()),
    **dict(ILO_SERIES.values()),
    **SINGLE_SERIES,
}

# Series made of modelled, imputed or gap-filled values rather than observations,
# or whose licence asks for a credit: the app shows
# the note under their charts.
_ILO_MODELLED = "ILO modelled estimates, which fill in years and countries without national data."
# Shown under the output-by-sector chart; not rescaled (no computing).
_SECTOR_GDP = ("Industry includes mining, utilities and construction. Shares don't add up to 100%: GDP at "
               "market prices also includes taxes on products, net of subsidies.")
_JMP_MODELLED = "WHO/UNICEF Joint Monitoring Programme estimates, modelled from household surveys."
ESTIMATE_NOTES: dict[str, str] = {
    "WB:SL.UEM.TOTL.ZS": _ILO_MODELLED,
    "WB:SL.TLF.CACT.ZS": _ILO_MODELLED,
    "WB:NV.AGR.TOTL.ZS": _SECTOR_GDP,
    "WB:NV.IND.TOTL.ZS": _SECTOR_GDP,
    "WB:NV.SRV.TOTL.ZS": _SECTOR_GDP,
    "WB:SL.AGR.EMPL.ZS": _ILO_MODELLED,
    "WB:SL.IND.EMPL.ZS": _ILO_MODELLED,
    "WB:SL.SRV.EMPL.ZS": _ILO_MODELLED,
    "WB:TX.VAL.MANF.ZS.UN": "Data: UN Comtrade. Re-exports and assembly of imported parts raise the share; "
                            "so do falls in oil and metal prices.",
    "WB:EG.EGY.PRIM.PP.KD": "SDG indicator 7.3.1 (Tracking SDG7: IEA, IRENA, UN, World Bank, WHO). Lower = less "
                            "energy used per unit of GDP.",
    "WB:NV.MNF.TECH.ZS.UN": "Data: UNIDO (SDG indicator 9.b.1). Medium and high-tech industries: chemicals, "
                            "machinery, vehicles, electronics, pharmaceuticals.",
    # Access to basic services: each agency models its own series from household surveys.
    "WB:SH.H2O.BASW.ZS": _JMP_MODELLED,
    "WB:SH.STA.BASS.ZS": _JMP_MODELLED,
    "WB:SH.STA.HYGN.ZS": _JMP_MODELLED + " Hygiene is not surveyed in most high-income countries, where access "
                                         "is near-universal: no data there, not 0%.",
    "WB:EG.ELC.ACCS.ZS": "Electricity: World Bank estimates, modelled from household surveys.",
    "WB:EG.CFT.ACCS.ZS": "Clean cooking: WHO estimates, modelled from household surveys.",
    # EDGAR's licence asks for this credit (its fossil CO2 part is IEA data, CC BY-NC-ND 4.0).
    "WB:EN.GHG.ALL.PC.CE.AR5": "Data: EDGAR (European Commission JRC) and IEA. Estimates from emission "
                               "inventories; excludes land use and forestry.",
    "WB:EN.GHG.ALL.MT.CE.AR5": "Data: EDGAR (European Commission JRC) and IEA. Estimates from emission "
                               "inventories; excludes land use and forestry.",
    "WB:EG.FEC.RNEW.ZS": "SDG indicator 7.2.1 (Tracking SDG7). Includes traditional biomass (wood, charcoal), "
                         "so many low-income countries show high shares without modern renewables.",
    "WB:AG.LND.FRST.ZS": "FAO Forest Resources Assessment (SDG indicator 15.1.1): reported about every five "
                         "years; the years in between are interpolated.",
    "ILO:LABOUR_SHARE": _ILO_MODELLED,
    "ILO:NEET": _ILO_MODELLED,
    "SWIID:GINI_DISP": "Imputed by a statistical model for years without comparable surveys.",
    "PIP:POV_3_00": "Only survey years are observed; other years are interpolated or extrapolated "
                    "from national accounts growth.",
    "PIP:MEDIAN": "Only survey years are observed; other years are interpolated or extrapolated from national "
                  "accounts growth. Some countries survey income, others consumption (income medians run higher).",
}


def source_of(series_code: str) -> str:
    """'IMF:NGDP_RPCH' -> 'IMF' (the key into SOURCES; World Bank WDI codes start with 'WB:')."""
    prefix = series_code.split(":", 1)[0]
    return "WDI" if prefix == "WB" else prefix


def series_of(source: str) -> list[str]:
    return [code for code in SERIES if source_of(code) == source]


# --------------------------------------------------------------------------
# Shared helpers
# --------------------------------------------------------------------------

RETRY_STATUSES = {500, 502, 503, 504}  # server-side errors worth a second try
RETRY_WAIT = 2  # seconds before the second attempt, doubled before each later one


def _get(session, url, *, accept: str | None = None, timeout: float = TIMEOUT, attempts: int = 1, **params):
    """One GET. With attempts > 1, a request that times out or gets a server error (RETRY_STATUSES)
    is tried again after a short wait; any other failure (unreachable host, 403, 404) is raised at once."""
    headers = {**HEADERS, **({"Accept": accept} if accept else {})}
    for attempt in range(1, attempts + 1):
        try:
            resp = session.get(url, params=params or None, headers=headers, timeout=timeout)
            resp.raise_for_status()
            return resp
        except (requests.exceptions.Timeout, requests.exceptions.HTTPError) as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            retryable = isinstance(exc, requests.exceptions.Timeout) or status in RETRY_STATUSES
            if attempt == attempts or not retryable:
                raise
            log.warning("%s failed (%s), attempt %d of %d; retrying", url, type(exc).__name__, attempt, attempts)
            time.sleep(RETRY_WAIT * 2 ** (attempt - 1))


def _finish(long_df: pd.DataFrame) -> pd.DataFrame:
    """Schema column order and types; drop rows without a value/year and years before FIRST_YEAR.
    Keeps one row per series/country/year (the first)."""
    out = long_df.assign(series_name=long_df["series_code"].map(SERIES))
    if "is_projection" not in out:
        out["is_projection"] = False
    out = out[SCHEMA].copy()
    out["year"] = pd.to_numeric(out["year"], errors="coerce")
    out["value"] = pd.to_numeric(out["value"], errors="coerce")
    out = out.dropna(subset=["year", "value", "country_code", "series_name"])
    out["year"] = out["year"].astype(int)
    out["is_projection"] = out["is_projection"].astype(bool)
    out = out[out["year"] >= FIRST_YEAR].drop_duplicates(["series_code", "country_code", "year"])
    return out.sort_values(["series_code", "country_code", "year"]).reset_index(drop=True)


def parse_date(value) -> dt.date | None:
    """A date from a publisher's metadata ("2026-07-01", "2026-02-08T19:59:09Z"), or None."""
    try:
        ts = pd.to_datetime(value, errors="coerce", utc=True)
    except Exception:  # noqa: BLE001 -- not a date at all (a dict, a list...)
        return None
    return None if pd.isna(ts) else ts.date()


def _latest(dates) -> dt.date | None:
    """The most recent of `dates`, ignoring None (several series of one source: the source's last release)."""
    return max((d for d in dates if d is not None), default=None)


def _release_date(source: str, get_date) -> dt.date | None:
    """get_date(), or None if it fails: a missing release date must never fail the source's data."""
    try:
        return get_date()
    except Exception as exc:  # noqa: BLE001
        log.warning("Could not read the %s release date: %s", source, exc)
        return None


def _read_excel(content: bytes, **kwargs) -> pd.DataFrame | dict[str, pd.DataFrame]:
    """pd.read_excel with the fast calamine engine where available (pandas >= 2.2 plus
    python-calamine: large workbooks load many times faster than with openpyxl)."""
    try:
        return pd.read_excel(io.BytesIO(content), engine="calamine", **kwargs)
    except Exception:  # noqa: BLE001 -- no calamine (ImportError/ValueError) or it choked: use openpyxl
        return pd.read_excel(io.BytesIO(content), **kwargs)


# --------------------------------------------------------------------------
# World Bank WDI (JSON API)
# --------------------------------------------------------------------------

WDI_URL = "https://api.worldbank.org/v2/country/all/indicator/{code}"
# The World Bank API now and then leaves a request hanging, and one failed series fails the whole
# source (seen on Streamlit Community Cloud, 2026-10-11: a 180 s read timeout). A series normally
# answers within seconds, so: give up on a request after WDI_TIMEOUT and try it again.
WDI_TIMEOUT = 45
WDI_ATTEMPTS = 3


def _wdi_one(session, code: str) -> tuple[pd.DataFrame, dt.date | None]:
    """One series, plus the "lastupdated" date the API sends with it (the WDI database's last update)."""
    rows, page, pages, updated = [], 1, 1, None
    while page <= pages:
        payload = _get(session, WDI_URL.format(code=code), timeout=WDI_TIMEOUT, attempts=WDI_ATTEMPTS,
                       format="json", per_page=20000, page=page,
                       date=f"{FIRST_YEAR}:{dt.date.today().year}").json()
        if not isinstance(payload, list) or len(payload) < 2:
            raise ValueError(f"unexpected WDI response for {code}: {str(payload)[:200]}")
        pages = int(payload[0].get("pages") or 1)
        updated = updated or parse_date(payload[0].get("lastupdated"))
        rows += [{"code": rec.get("countryiso3code") or rec["country"]["id"],  # income groups: ISO3 is ""
                  "year": rec["date"], "value": rec["value"]}
                 for rec in payload[1] or [] if rec.get("value") is not None]
        page += 1
    raw = pd.DataFrame(rows, columns=["code", "year", "value"])
    return cd.unify_countries(raw, code_col="code", label=f"WDI {code}").assign(series_code=f"WB:{code}"), updated


def fetch_wdi(session) -> tuple[pd.DataFrame, dt.date | None]:
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:  # ~30 series: don't hammer the API
        frames, dates = zip(*ex.map(lambda code: _wdi_one(session, code), WDI_SERIES))
    return _finish(pd.concat(frames, ignore_index=True)), _latest(dates)


# --------------------------------------------------------------------------
# IMF World Economic Outlook (SDMX API; fallback: DataMapper API)
# --------------------------------------------------------------------------

IMF_SDMX_URL = "https://api.imf.org/external/sdmx/3.0/data/dataflow/IMF.RES/WEO/~/"
IMF_DATAMAPPER_URL = "https://www.imf.org/external/datamapper/api/v1"


def _imf_projection_start(published: dt.date | None, update_dates: pd.Series | None = None) -> int:
    """
    First projected year. Neither IMF API marks actual vs. projected values (the SDMX attribute
    LATEST_ACTUAL_ANNUAL_DATA exists but is empty), so: the year the WEO edition was published
    (_imf_publication_date: the October 2025 edition projects 2025 onward, the April 2026 one 2026
    onward). Without it, the latest SDMX COUNTRY_UPDATE_DATE, which can lag an edition (the April
    2026 one still carries September 2025 dates); without either, a date rule: from April (the
    spring edition) this year, before that last year.
    """
    if published is not None:
        return published.year
    if update_dates is not None:
        years = pd.to_datetime(update_dates, errors="coerce").dt.year.dropna()
        if len(years):
            return int(years.max())
    today = dt.date.today()
    return today.year if today.month >= 4 else today.year - 1


def _imf_from_sdmx(session) -> pd.DataFrame:
    key = "*." + "+".join(IMF_SERIES) + ".A"  # every country, all listed indicators, annual
    text = _get(session, IMF_SDMX_URL + key, accept="text/csv", **{"c[TIME_PERIOD]": f"ge:{FIRST_YEAR}"}).text
    raw = pd.read_csv(io.StringIO(text))
    raw.columns = [str(c).strip() for c in raw.columns]
    missing = {"COUNTRY", "INDICATOR", "TIME_PERIOD", "OBS_VALUE"} - set(raw.columns)
    if raw.empty or missing:
        raise ValueError(f"IMF SDMX returned no rows or lacks columns {missing}; columns: {list(raw.columns)}")
    return raw.assign(year=raw["TIME_PERIOD"].astype(str).str[:4])


def _imf_from_datamapper(session) -> pd.DataFrame:
    rows = []
    for ind in IMF_SERIES:
        values = _get(session, f"{IMF_DATAMAPPER_URL}/{ind}", accept="application/json").json()
        rows += [{"COUNTRY": c, "INDICATOR": ind, "year": y, "OBS_VALUE": v}
                 for c, by_year in values.get("values", {}).get(ind, {}).items() for y, v in by_year.items()]
    return pd.DataFrame(rows)


def _imf_publication_date(session) -> dt.date | None:
    """
    The WEO edition's publication date: the SDMX attribute PUBLICATION_DATE (2026-04-14 for the April
    2026 edition), for "Last updated" and the first projected year. The data request leaves the attributes out (with them, the whole table is about
    250 MB instead of 6), so this reads them for one short series, World real GDP growth.
    COUNTRY_UPDATE_DATE can't be used here: the April 2026 edition still carries September 2025 dates.
    """
    text = _get(session, IMF_SDMX_URL + "G001.NGDP_RPCH.A", accept="text/csv", attributes="all",
                **{"c[TIME_PERIOD]": f"ge:{dt.date.today().year - 1}"}).text
    raw = pd.read_csv(io.StringIO(text))
    return _latest(parse_date(v) for v in raw["PUBLICATION_DATE"].dropna().unique())


def fetch_imf(session) -> tuple[pd.DataFrame, dt.date | None]:
    try:
        raw = _imf_from_sdmx(session)
        updated = _release_date("IMF", lambda: _imf_publication_date(session))
    except Exception as exc:  # noqa: BLE001 -- any SDMX failure: try the other API
        log.warning("IMF SDMX API failed (%s); using the DataMapper API", exc)
        raw, updated = _imf_from_datamapper(session), None  # DataMapper has no edition date
    start = _imf_projection_start(updated, raw.get("COUNTRY_UPDATE_DATE"))
    df = cd.unify_countries(raw, code_col="COUNTRY", label="IMF")
    return _finish(df.assign(series_code="IMF:" + df["INDICATOR"].astype(str), value=df["OBS_VALUE"],
                             is_projection=pd.to_numeric(df["year"]) >= start)), updated


# --------------------------------------------------------------------------
# ND-GAIN Country Index (zip of CSVs, years as columns)
# --------------------------------------------------------------------------

# Update from https://gain.nd.edu/our-work/country-index/download-data/ when a new release is out.
# Every release recalculates the whole history, so the full series is always replaced.
# The file carries no date: NDGAIN_RELEASED is its release, updated together with NDGAIN_URL.
NDGAIN_URL = "https://gain.nd.edu/assets/647440/ndgain_countryindex_2026.zip"
NDGAIN_RELEASED = dt.date(2026, 7, 15)  # 2026 edition, announced by ND-GAIN on 15 July 2026


def fetch_ndgain(session) -> tuple[pd.DataFrame, dt.date | None]:
    zf = zipfile.ZipFile(io.BytesIO(_get(session, NDGAIN_URL).content))
    names = [n for n in zf.namelist() if not n.startswith("__MACOSX")]
    frames = []
    for member, (code, _) in NDGAIN_SERIES.items():
        # "<release folder>/gain/gain.csv" -- not "trends/gain.csv", which holds trend slopes
        path = next((n for n in names if n.lower().endswith("/" + member) or n.lower() == member), None)
        if path is None:
            raise KeyError(f"ND-GAIN {member} not in the zip; files: {names[:40]}")
        raw = pd.read_csv(zf.open(path))
        years = [c for c in raw.columns if re.fullmatch(r"\d{4}", str(c))]
        long_ = raw.melt(id_vars=["ISO3", "Name"], value_vars=years, var_name="year", value_name="value")
        frames.append(cd.unify_countries(long_, code_col="ISO3", name_col="Name", label="ND-GAIN")
                      .assign(series_code=code))
    return _finish(pd.concat(frames, ignore_index=True)), NDGAIN_RELEASED


# --------------------------------------------------------------------------
# World Happiness Report (Excel, data for Figure 2.1: every year since 2011 in one table)
# --------------------------------------------------------------------------

# Update each spring (https://www.worldhappiness.report/data-sharing/). Year = the last year of
# the 3-year average (the 2026 report's latest is 2025, i.e. 2023-2025).
# The file carries no date: WHR_RELEASED is the report's release, updated together with WHR_URL.
WHR_URL = "https://files.worldhappiness.report/WHR26_Data_Figure_2.1.xlsx"
WHR_RELEASED = dt.date(2026, 3, 19)  # World Happiness Report 2026


def fetch_whr(session) -> tuple[pd.DataFrame, dt.date | None]:
    raw = _read_excel(_get(session, WHR_URL).content)
    raw.columns = [str(c).strip() for c in raw.columns]
    # "Life evaluation (3-year average)" since 2026, "Ladder score" before; not its whiskers or rank
    score = next((c for c in raw.columns if re.match(r"life evaluation|ladder score", c, re.I)), None)
    if score is None or not {"Country name", "Year"} <= set(raw.columns):
        raise KeyError(f"WHR country/year/score columns not found; columns are {list(raw.columns)}")
    df = cd.unify_countries(raw, name_col="Country name", label="WHR")
    return _finish(df.assign(series_code="WHR:LADDER", year=df["Year"], value=df[score])), WHR_RELEASED


# --------------------------------------------------------------------------
# Harvard Growth Lab: Economic Complexity Index (Harvard Dataverse API)
# --------------------------------------------------------------------------

DATAVERSE_URL = "https://dataverse.harvard.edu/api"
ECI_DOI = "doi:10.7910/DVN/XTAQMC"  # "Growth Projections and Complexity Rankings"
ECI_COLUMN = "eci_sitc"  # the file also has eci_hs92 / eci_hs12 (other product classifications)


def fetch_eci(session) -> tuple[pd.DataFrame, dt.date | None]:
    meta = _get(session, f"{DATAVERSE_URL}/datasets/:persistentId/", persistentId=ECI_DOI).json()
    # Release date: when the dataset's latest version was published on Dataverse
    updated = _release_date("ECI", lambda: parse_date(meta["data"]["latestVersion"]["releaseTime"]))
    files = [(f["dataFile"]["id"], f["dataFile"].get("originalFileName") or f["dataFile"]["filename"])
             for f in meta["data"]["latestVersion"]["files"]]
    # growth_proj_eci_rankings.csv, not rankings_data_dictionary.csv
    file_id = next((i for i, name in files if "rank" in name.lower() and "dictionary" not in name.lower()), None)
    if file_id is None:
        raise KeyError(f"No ECI rankings file in the Dataverse dataset; files: {files}")
    raw = pd.read_csv(io.BytesIO(_get(session, f"{DATAVERSE_URL}/access/datafile/{file_id}",
                                      format="original").content))
    df = cd.unify_countries(raw, code_col="country_iso3_code", label="ECI")
    return _finish(df.assign(series_code="ECI:ECI", value=df[ECI_COLUMN])), updated


# --------------------------------------------------------------------------
# UNDP Human Development Report: composite indices time series (CSV, one column per year)
# --------------------------------------------------------------------------

# Update with each new report. The file carries no date: UNDP_RELEASED is the report's release,
# updated together with UNDP_URL.
UNDP_URL = "https://hdr.undp.org/sites/default/files/2025_HDR/HDR25_Composite_indices_complete_time_series.csv"
UNDP_RELEASED = dt.date(2025, 5, 6)  # Human Development Report 2025, launched 6 May 2025
UNDP_SERIES = {"mys": "UNDP:MYS", "eys": "UNDP:EYS"}  # column prefix -> series code


def fetch_undp(session) -> tuple[pd.DataFrame, dt.date | None]:
    content = _get(session, UNDP_URL, accept="text/csv").content
    try:
        raw = pd.read_csv(io.BytesIO(content))
    except UnicodeDecodeError:  # the 2025 file is Latin-1
        raw = pd.read_csv(io.BytesIO(content), encoding="latin-1")
    frames = []
    for prefix, code in UNDP_SERIES.items():
        # Exact match: mys_2020, not mys_f_2020 / mys_m_2020 (by sex)
        years = [c for c in raw.columns if re.fullmatch(rf"{prefix}_\d{{4}}", str(c))]
        if not years:
            raise KeyError(f"No {prefix}_YYYY columns in the UNDP file; columns are {list(raw.columns)[:40]}")
        long_ = raw.melt(id_vars=["iso3", "country"], value_vars=years, var_name="col", value_name="value")
        frames.append(long_.assign(series_code=code, year=long_["col"].str[-4:]))
    # Aggregates have non-ISO codes (ZZA.VHHD ...) and are dropped; Kosovo is KSV.
    return _finish(cd.unify_countries(pd.concat(frames, ignore_index=True), code_col="iso3", name_col="country",
                                      label="UNDP")), UNDP_RELEASED


# --------------------------------------------------------------------------
# ILOSTAT bulk download (one CSV per indicator; ILO modelled estimates)
# --------------------------------------------------------------------------

ILO_URL = "https://rplumber.ilo.org/data/indicator/"
# ILOSTAT's table of contents: one row per indicator, with its "last.update" (day first). The data
# files carry no date, so this is one more request (about 0.7 MB: the API ignores an id filter).
ILO_TOC_URL = "https://rplumber.ilo.org/metadata/toc/indicator/"


def _ilo_projection_start() -> int:
    """
    First projected year of the ILO modelled estimates. The files don't mark projections (the
    labour income share runs to 2026, NEET to 2027), but the estimates come out each November,
    with estimates up to the year before: from November, this year; before that, last year.
    """
    today = dt.date.today()
    return today.year if today.month >= 11 else today.year - 1


def _ilo_one(session, ind_id: str) -> pd.DataFrame:
    raw = pd.read_csv(io.BytesIO(_get(session, ILO_URL, accept="text/csv", id=ind_id, type="code",
                                      format=".csv").content))
    if "sex" in raw:
        raw = raw[raw["sex"] == "SEX_T"]  # both sexes
    df = cd.unify_countries(raw, code_col="ref_area", label=f"ILO {ind_id}")  # X01...: ILO groups, dropped
    year = pd.to_numeric(df["time"].astype(str).str[:4], errors="coerce")
    return df.assign(series_code=ILO_SERIES[ind_id][0], year=year, value=df["obs_value"],
                     is_projection=year >= _ilo_projection_start())


def _ilo_last_update(session) -> dt.date | None:
    """The latest "last.update" in ILOSTAT's table of contents among the indicators fetched."""
    toc = pd.read_csv(io.BytesIO(_get(session, ILO_TOC_URL, accept="text/csv").content), usecols=["id", "last.update"])
    dates = pd.to_datetime(toc.loc[toc["id"].isin(ILO_SERIES), "last.update"], format="%d/%m/%Y %H:%M:%S",
                           errors="coerce").dropna()
    return dates.max().date() if len(dates) else None


def fetch_ilo(session) -> tuple[pd.DataFrame, dt.date | None]:
    df = _finish(pd.concat([_ilo_one(session, ind_id) for ind_id in ILO_SERIES], ignore_index=True))
    return df, _release_date("ILO", lambda: _ilo_last_update(session))


# --------------------------------------------------------------------------
# SWIID: Standardized World Income Inequality Database (CSV on GitHub)
# --------------------------------------------------------------------------

# No explicit licence (cite Solt 2020): fetched at run time, never committed (the disk cache is
# gitignored). Each version recalculates the whole history.
SWIID_URL = "https://raw.githubusercontent.com/fsolt/swiid/master/data/swiid_summary.csv"
# Release date: the last commit to that file (GitHub API: 60 requests an hour without a token, and
# the result is cached for 24h). Each version is one commit, e.g. "update for 9.92".
SWIID_COMMITS_URL = "https://api.github.com/repos/fsolt/swiid/commits"
SWIID_PATH = "data/swiid_summary.csv"


def _swiid_last_commit(session) -> dt.date | None:
    commits = _get(session, SWIID_COMMITS_URL, accept="application/vnd.github+json", path=SWIID_PATH,
                   per_page=1).json()
    return parse_date(commits[0]["commit"]["committer"]["date"])


def fetch_swiid(session) -> tuple[pd.DataFrame, dt.date | None]:
    raw = pd.read_csv(io.StringIO(_get(session, SWIID_URL, accept="text/csv").text))
    # Matched by name ("Congo-Kinshasa"...); Soviet Union, Yugoslavia and Czechoslovakia are dropped.
    df = cd.unify_countries(raw, name_col="country", label="SWIID")
    return (_finish(df.assign(series_code="SWIID:GINI_DISP", value=df["gini_disp"])),
            _release_date("SWIID", lambda: _swiid_last_commit(session)))


# --------------------------------------------------------------------------
# World Bank Poverty and Inequality Platform (JSON API, line-up estimates for every year)
# --------------------------------------------------------------------------

PIP_URL = "https://api.worldbank.org/pip/v1/pip"
PIP_POVERTY_LINE = 3.0  # $ a day, 2021 PPP
PIP_PPP_YEAR = 2021  # the PPP base of the data the API serves by default (and of the poverty line)
# The data carries no version: pip-info lists the releases ("20260922_2021_01_02_PROD": release date,
# PPP year, ...), and the API serves the latest by default.
PIP_INFO_URL = "https://api.worldbank.org/pip/v1/pip-info"


def _pip_release(session) -> dt.date | None:
    versions = _get(session, PIP_INFO_URL, accept="application/json").json()["available_data_versions"]
    return _latest(dt.datetime.strptime(v[:8], "%Y%m%d").date() for v in versions
                   if v.split("_")[1] == str(PIP_PPP_YEAR))


def fetch_pip(session) -> tuple[pd.DataFrame, dt.date | None]:
    raw = pd.DataFrame(_get(session, PIP_URL, accept="application/json", country="all", year="all",
                            povline=PIP_POVERTY_LINE, fill_gaps="true", format="json").json())
    # National level only (China, India... also have urban/rural rows). "CMD estimation" rows are
    # countries without any survey, filled in from their region's average: not country data.
    raw = raw[(raw["reporting_level"] == "national") & (raw["estimation_type"] != "CMD estimation")]
    raw = raw.drop_duplicates(["country_code", "reporting_year"])  # two welfare types in a year: keep one
    df = cd.unify_countries(raw, code_col="country_code", name_col="country_name", label="PIP")
    # Years after the latest line-up year (2025 on, as of Sep 2026) are nowcasts: shown like projections.
    # Two series from the same call: poverty headcount and the median (daily, 2021 PPP $).
    common = dict(year=df["reporting_year"], is_projection=df["estimate_type"].eq("nowcast"))
    poverty = df.assign(series_code="PIP:POV_3_00", value=df["headcount"] * 100, **common)
    median = df.assign(series_code="PIP:MEDIAN", value=df.get("median"), **common)
    return (_finish(pd.concat([poverty, median], ignore_index=True)),
            _release_date("PIP", lambda: _pip_release(session)))


# --------------------------------------------------------------------------
# Registry
# --------------------------------------------------------------------------

SOURCES: dict[str, dict] = {
    "WDI": dict(label="World Bank, World Development Indicators", fetch=fetch_wdi),
    "IMF": dict(label="IMF, World Economic Outlook", fetch=fetch_imf),
    "NDGAIN": dict(label="University of Notre Dame, ND-GAIN Country Index", fetch=fetch_ndgain),
    "WHR": dict(label="World Happiness Report 2026, from the Gallup World Poll", fetch=fetch_whr),
    "ECI": dict(label="Harvard Growth Lab, Atlas of Economic Complexity", fetch=fetch_eci),
    "UNDP": dict(label="UNDP, Human Development Report 2025", fetch=fetch_undp),
    "ILO": dict(label="International Labour Organization, ILOSTAT", fetch=fetch_ilo),
    "SWIID": dict(label="Standardized World Income Inequality Database (Solt 2020)", fetch=fetch_swiid),
    "PIP": dict(label="World Bank, Poverty and Inequality Platform", fetch=fetch_pip),
}
