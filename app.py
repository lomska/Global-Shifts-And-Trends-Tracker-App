"""
Global Shifts Explorer -- an interactive Streamlit app in two tabs: Trends
(every indicator over time for one country, region or income group, in sections from
Economics to Healthcare) and Distributions (one indicator across all countries, two
years compared).

Data: the sources in sources.py -- World Bank population estimates and projections (source 40,
history from 1960 plus projections through 2050, for Demographics), World Bank WDI and PIP, IMF
World Economic Outlook, ND-GAIN, World Happiness Report, Harvard Growth Lab, UNDP, ILOSTAT and
SWIID -- loaded by data_utils.load_data() into one long table, `data`. Pulled live and cached for
a day at a time.

Chart styling: clean, light charts with horizontal gridlines only, titles and units above the plot
and sources below, in Streamlit's own font. See style_fig() and data_utils' palette constants.
"""

from __future__ import annotations

import base64
import datetime as dt
import html
import math
import traceback
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import data_utils as du
import sources as ds

# --------------------------------------------------------------------------
# Page config
# --------------------------------------------------------------------------

APP_NAME = "Global Shifts Explorer"  # browser tab and page heading

st.set_page_config(
    page_title=APP_NAME,
    page_icon="\U0001F30D",
    layout="wide",
    initial_sidebar_state="collapsed",
)


# --------------------------------------------------------------------------
# Shared chart styling (style_fig)
# --------------------------------------------------------------------------

# Display-only short names for the World Bank regions. Data columns and color maps stay
# keyed by the full names; only what's shown (legends, axis labels, hovers, tables) changes.
REGION_SHORT_LABEL: dict[str, str] = {
    "East Asia & Pacific": "East Asia & Pac.",
    "Europe & Central Asia": "Europe & C. Asia",
    "Latin America & Caribbean": "Latin Am. & Carib.",
    "Middle East, North Africa, Afghanistan & Pakistan": "MENAAP",
    "North America": "North America",
    "South Asia": "South Asia",
    "Sub-Saharan Africa": "Sub-Saharan Afr.",
}


# Round flags (512x512 SVG circles, the same size for every country) from the circle-flags set,
# v2.8.0 (MIT, flags/LICENSE.md).
FLAGS_DIR = Path(__file__).with_name("flags")


def flag_file(iso2: str | None) -> Path | None:
    """The flag file for an ISO2 country code, or None if there is none."""
    # "JG" = World Bank's Channel Islands (Jersey + Guernsey): not a real ISO code, no single flag.
    if not isinstance(iso2, str) or len(iso2) != 2 or not iso2.isalpha() or iso2.upper() == "JG":
        return None
    path = FLAGS_DIR / f"{iso2.lower()}.svg"
    return path if path.is_file() else None


# st.dataframe's ImageColumn scales every image to the cell's height 
# (row height minus vertical padding: 34px and 3px top/bottom in Streamlit 1.64).
# To show a flag at FLAG_ROW_SHARE of the row height, pad the SVG's viewBox so the
# circle fills only that share of the image.
_GRID_ROW_PX, _GRID_CELL_PAD_PX = 34, 3
FLAG_ROW_SHARE = 0.65
_FLAG_SCALE = FLAG_ROW_SHARE * _GRID_ROW_PX / (_GRID_ROW_PX - 2 * _GRID_CELL_PAD_PX)


@st.cache_data(show_spinner=False)
def flag_image(iso2: str | None, scale: float = _FLAG_SCALE) -> str | None:
    """flag_file's round flag as an embeddable data: URI, shrunk to `scale` of the image with
    transparent padding (default: table-row size; 1.0 = no padding). None if unavailable."""
    path = flag_file(iso2)
    if path is None:
        return None
    try:
        svg = path.read_text(encoding="utf-8")
    except OSError:  # a missing flag just leaves the cell blank
        return None
    size = 512 / scale
    offset = (size - 512) / 2
    svg = svg.replace('viewBox="0 0 512 512"', f'viewBox="{-offset:.1f} {-offset:.1f} {size:.1f} {size:.1f}"', 1)
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode()


def region_pill_column(label: str = "Region"):
    """
    Read-only column showing each region as a pill in its chart color. 
    Cells must be lists of short region names; MultiselectColumn maps `color` 
    onto `options` by position.
    """
    return st.column_config.MultiselectColumn(
        label,
        options=[REGION_SHORT_LABEL.get(r, r) for r in du.REGION_COLOR_MAP],
        color=list(du.REGION_COLOR_MAP.values()),
    )


def with_short_regions(df: pd.DataFrame, col: str = "region") -> pd.DataFrame:
    """Copy of df with its region column shown as short region names (for tables/bar labels)."""
    return df.assign(**{col: df[col].map(lambda r: REGION_SHORT_LABEL.get(r, r))})


# Streamlit's own font, so charts match the rest of the page. Text sizes: axis labels 12px, sources 11px;
# titles and legends are a step smaller in the three-per-row Trends charts (TREND_*_PX).
FONT = '"Source Sans", "Source Sans Pro", sans-serif'
AXIS_TEXT = dict(family=FONT, size=12, color="black")


def style_fig(
    fig: go.Figure,
    title: str,
    y_title: str,
    x_title: str = "",
    height: int = 440,
    legend: bool = True,
    legend_px: int = 14,
) -> go.Figure:
    """
    The app's chart style: white background, solid
    light-gray horizontal gridlines only, a black x-axis line with outside ticks, no y-axis line
    or ticks, no frame, a solid black zero line, and the legend in one horizontal row across the
    top, between the title/subtitle and the plot. Units belong in the subtitle (stated once),
    so tick labels carry no suffix.
    """
    fig.update_layout(
        plot_bgcolor="white",
        paper_bgcolor="white",
        title=dict(text=title, font=dict(family=FONT, size=20, color="black")),
        hovermode="x unified",
        hoverlabel=dict(bgcolor="rgba(255,255,255,0.9)", font=AXIS_TEXT),
        height=height,
        margin=dict(l=10, r=10, t=50, b=10),
        showlegend=legend,
        # One row across the top, left-aligned with the plot. traceorder "normal": with legend
        # groups (add_split_line) Plotly would otherwise stack the entries vertically.
        legend=dict(orientation="h", x=0, xanchor="left", y=1, yanchor="bottom", traceorder="normal",
                    bgcolor="rgba(0,0,0,0)", font=dict(family=FONT, size=legend_px, color="black")),
        font=dict(family=FONT, color="black"),
    )
    fig.update_xaxes(
        showline=True, linecolor="black", linewidth=1, mirror=False, ticks="outside", tickcolor="black",
        showgrid=False, zeroline=False, automargin=True,
        title=dict(text=x_title, font=AXIS_TEXT), tickfont=AXIS_TEXT,
    )
    fig.update_yaxes(
        showline=False, mirror=False, ticks="", showgrid=True, gridcolor=du.GRID_COLOR, gridwidth=1, griddash="solid",
        # Plotly's default zero line is white -- invisible on a white plot. Solid black instead,
        # shown whenever y = 0 is inside the axis range.
        zeroline=True, zerolinecolor=du.ZERO_LINE_COLOR, zerolinewidth=1, automargin=True,
        title=dict(text=y_title, font=AXIS_TEXT), tickfont=AXIS_TEXT,
    )
    return fig


# Headline case for titles, sentence case for subtitles.
_MINOR_WORDS = {"a", "an", "and", "as", "at", "but", "by", "for", "from", "in", "into", "nor", "of", "on", "or",
                "per", "the", "to", "vs.", "vs", "via", "with"}


def headline_case(text: str) -> str:
    """'Birth and death rates' -> 'Birth and Death Rates': major words capitalized, minor ones
    (and, of, per, to, vs. ...) lowercase except first, last and after a colon. Words that
    already have a capital after their first letter (GDP, CO₂, ND-GAIN, R&D) are left alone."""
    words = text.split(" ")
    out = []
    for i, w in enumerate(words):
        core = w.lstrip("(\"'“")
        lead = w[:len(w) - len(core)]
        after_colon = i > 0 and words[i - 1].endswith(":")
        if not core or any(ch.isupper() for ch in core[1:]) or not core[0].isalpha():
            out.append(w)
        elif core.lower() in _MINOR_WORDS and 0 < i < len(words) - 1 and not after_colon:
            out.append(lead + core.lower())
        else:
            out.append(lead + core[0].upper() + core[1:])
    return " ".join(out)


def sentence_case(text: str) -> str:
    """'live births per woman' -> 'Live births per woman'; '% of GDP' stays as it is."""
    return text[:1].upper() + text[1:] if text[:1].isalpha() else text


def add_split_line(
    fig: go.Figure,
    s: pd.Series,
    forecast_x: float,
    *,
    name: str,
    legendgroup: str,
    line: dict,
    hovertemplate: str,
):
    """
    Add series s (indexed by year) as a solid line over observed years (< forecast_x)
    and a dotted line over forecast years (>= forecast_x). All pieces share a
    legendgroup so the single legend entry toggles the whole series.
    The drawn pieces (solid, dotted, and a dotted bridge from the last observed to the first
    forecast point) don't answer hover. The tooltip comes from one invisible trace over all
    the series' years, with " (forecast)" after the value in forecast years.
    Being invisible, it also shows no line swatch in the tooltip.
    """
    hist, fcst = s[s.index < forecast_x], s[s.index >= forecast_x]
    fig.add_trace(go.Scatter(x=hist.index, y=hist, mode="lines", line=line, name=name,
                             legendgroup=legendgroup, hoverinfo="skip"))
    if not fcst.dropna().empty:
        dotted = {**line, "dash": "dot"}
        fig.add_trace(go.Scatter(x=fcst.index, y=fcst, mode="lines", line=dotted, name=name,
                                 legendgroup=legendgroup, showlegend=False, hoverinfo="skip"))
        last_hist, first_fcst = hist.dropna().tail(1), fcst.dropna().head(1)
        if not last_hist.empty:
            bridge = pd.concat([last_hist, first_fcst])
            fig.add_trace(go.Scatter(x=bridge.index, y=bridge, mode="lines", line=dotted,
                                     legendgroup=legendgroup, showlegend=False, hoverinfo="skip"))
    fig.add_trace(go.Scatter(
        x=s.index, y=s, mode="lines", line=dict(width=0, color="rgba(0,0,0,0)"), name=name,
        legendgroup=legendgroup, showlegend=False,
        text=[" (forecast)" if year >= forecast_x else "" for year in s.index],
        hovertemplate=hovertemplate.replace("<extra>", "%{text}<extra>"),
    ))


def shared_legend(names, color_map: dict, forecast_key: bool = False, margin_top: str = "0", bar: bool = False,
                  indent: int = 0):
    """
    One HTML legend (colored swatch + name per series) for a chart that hides its own
    legend: line swatches, or bar swatches with bar=True (trend_stacked_bar).
    forecast_key=True appends grey "Observed" / "Forecast" keys, each with a line swatch
    (solid / dotted, as add_split_line draws them) and a bar swatch (full / half strength,
    as trend_stacked_bar draws them). A negative margin_top (e.g. "-1rem") pulls the
    legend up into Streamlit's gap between elements, closer to the chart above. indent is a
    left padding in px.
    """
    def line_swatch(color, style="solid"):
        return f'<span style="display:inline-block;width:18px;height:0;border-top:3px {style} {color}"></span>'

    def bar_swatch(color, opacity):
        # A small upright bar, filled like trend_stacked_bar's bars.
        return (f'<span style="display:inline-block;width:8px;height:12px;'
                f'background:{_hex_rgba(color, opacity)}"></span>')

    def item(label, *swatches):
        return (
            f'<span style="display:inline-flex;align-items:center;gap:6px;margin:0 12px 4px 0;white-space:nowrap">'
            f'{"".join(swatches)}{label}</span>'
        )

    def swatch(color):
        return bar_swatch(color, 1.0) if bar else line_swatch(color)

    items = "".join(item(REGION_SHORT_LABEL.get(n, n), swatch(color_map.get(n, du.LIGHT_GREY))) for n in names)
    if forecast_key:
        grey = du.TROLLEY_GREY
        items += (
            (f'<span style="margin:0 12px 4px 0;color:{du.LIGHT_GREY}">|</span>' if items else "")
            + item("Observed", line_swatch(grey), bar_swatch(grey, 1.0))
            + item("Forecast", line_swatch(grey, "dotted"), bar_swatch(grey, FORECAST_BAR_ALPHA))
        )
    # min-height: an empty legend (single-series chart) takes one legend row's height, so
    # the source footers below the charts in a row line up.
    st.markdown(
        f'<div style="display:flex;flex-wrap:wrap;min-height:20px;margin-top:{margin_top};padding-left:{indent}px;'
        f'font-size:14px;color:black">{items}</div>',
        unsafe_allow_html=True,
    )


COUNTRIES_NAME = "World Bank country list"  # du.COUNTRIES_SOURCE's display name


def source_name(key: str) -> str:
    """Display name for a key of the merged errors: a source (du.SOURCE_LABELS) or the country list."""
    return COUNTRIES_NAME if key == du.COUNTRIES_SOURCE else du.SOURCE_LABELS.get(key, key)


# Every source's licence and full credit, shown in a dialog from the sidebar: the short source lines
# under the charts don't carry everything the publishers ask for (licence links, versions, citations).
DATA_SOURCES_FILE = Path(__file__).with_name("DATA_SOURCES.md")
LICENSE_URL = "https://polyformproject.org/licenses/noncommercial/1.0.0"


def data_sources_markdown() -> str | None:
    """DATA_SOURCES.md for the dialog: without its "# Data sources" heading (the dialog's title), its
    relative link to LICENSE pointed at the licence's own page. None if the file can't be read."""
    try:
        text = DATA_SOURCES_FILE.read_text(encoding="utf-8")
    except OSError:
        return None
    if text.startswith("# "):
        text = text.split("\n", 1)[1] if "\n" in text else ""
    return text.replace("](LICENSE)", f"]({LICENSE_URL})")


@st.dialog("Data sources and licences", width="large")
def show_data_sources():
    text = data_sources_markdown()
    if text is None:
        st.warning(f"Couldn't read {DATA_SOURCES_FILE.name}.")
    else:
        st.markdown(text)


# English month abbreviations whatever the machine's locale (strftime's %b follows the locale).
MONTH_ABBR = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def month_year(date: dt.date) -> str:
    """dt.date(2026, 7, 1) -> 'Jul-2026' (%b-%Y in English)."""
    return f"{MONTH_ABBR[date.month - 1]}-{date.year}"


def source_text(source: str | list[str], updated: dt.date | None | list[dt.date | None] = None) -> str:
    """The text after "Source: ": each source, followed by " · Last updated MMM-YYYY" when its
    publisher's release date is known (a list of sources takes a list of dates, in the same order),
    joined by "; "."""
    sources = [source] if isinstance(source, str) else list(source)
    dates = list(updated) if isinstance(updated, (list, tuple)) else [updated] * len(sources)
    return "; ".join(s + (f" · Last updated {month_year(d)}" if d else "") for s, d in zip(sources, dates))


def source_footer(source: str | list[str], indent: int = 0, note: str | None = None,
                  margin_top: str = "-0.75rem", updated: dt.date | None | list[dt.date | None] = None):
    """The data-source line under a chart, then an optional `note` line, both 11px black
    ("Source: ..." first, "Note: ..." after it). updated: the
    source's release date (or a list, one per source), shown as "Last updated" (source_text).
    indent is a left padding in px; a negative margin_top pulls it up towards the chart."""
    note_html = f"<br>Note: {html.escape(note)}" if note else ""
    st.markdown(
        f'<div style="margin-top:{margin_top};padding-left:{indent}px;font-size:11px;color:black">'
        f"Source: {html.escape(source_text(source, updated))}{note_html}</div>",
        unsafe_allow_html=True,
    )


def _hex_rgba(hex_color: str, alpha: float) -> str:
    r, g, b = (int(hex_color.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
    return f"rgba({r},{g},{b},{alpha})"


# --------------------------------------------------------------------------
# Data loading
# --------------------------------------------------------------------------

def load_countries() -> tuple[pd.DataFrame, dict[str, str]]:
    """The country list (du.load_countries). Never stops the app: if it can't be fetched, a fallback
    list comes back with errors[du.COUNTRIES_SOURCE], for countries_warning()."""
    try:
        return du.load_countries()
    except Exception as exc:  # noqa: BLE001 -- load_countries reports failures; this is a last resort
        return du.fallback_countries(), {du.COUNTRIES_SOURCE: "".join(traceback.format_exception(exc))}


def load_data() -> tuple[pd.DataFrame, dict[str, str]]:
    """Every source's data (du.load_data) with a visible spinner. Never stops the app: a failed source
    only empties its own charts, with a warning where they would be."""
    try:
        with st.spinner("Loading the data -- first run can take up to a minute..."):
            return du.load_data()
    except Exception as exc:  # noqa: BLE001 -- load_data reports per source; this is a last resort
        return du.empty_data(), {s: f"{type(exc).__name__}: {exc}" for s in du.SOURCE_LABELS}


def countries_warning(errors: dict[str, str], countries: pd.DataFrame):
    """A warning at the top of the page if the country list couldn't be loaded, with the details in an
    expander. (A failed source is named where its charts would be, like any other.)"""
    if du.COUNTRIES_SOURCE not in errors:
        return
    st.warning("Couldn't load the World Bank country list: "
               + ("a saved copy is used instead." if du.has_country_groups(countries) else
                  "a basic list of country names is used instead, so region and income-group information "
                  "is missing.")
               + "\n\nUse **Refresh data** in the sidebar to retry.")
    with st.expander("Error details"):
        st.code(f"{COUNTRIES_NAME}: {errors[du.COUNTRIES_SOURCE]}")


def stale_sources_notice():
    """A note at the top of the page naming the sources that couldn't be fetched just now and are shown
    from the copy saved earlier (du.stale_sources), with the details in an expander. Never raises."""
    try:
        stale = du.stale_sources()
    except Exception:  # noqa: BLE001 -- only the note is lost
        return
    if not stale:
        return
    MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
    saved = "; ".join(f"{source_name(key)} (saved {when.day} {MONTHS[when.month - 1]} {when.year})"
                      for key, (when, _) in sorted(stale.items(), key=lambda kv: source_name(kv[0])))
    st.info(f"Couldn't reach some data sources just now, so their charts show the copy saved earlier: {saved}. "
            "Use **Refresh data** in the sidebar to try again.")
    with st.expander("Error details"):
        st.code("\n".join(f"{key}: {message}" for key, (_, message) in stale.items()))


def stop_if_nothing_loaded(errors: dict[str, str], data: pd.DataFrame):
    """Stop the app, with an error, only when nothing can be shown: every source failed or returned no data."""
    if not data.empty:
        return
    st.error(
        "Couldn't reach the World Bank API or any other data source.\n\n"
        "This app needs live outbound access to api.worldbank.org (and the other publishers in the sidebar) "
        "from wherever it's hosted -- check that the host isn't blocking those domains, then use the "
        "Refresh data button or reload the page."
    )
    with st.expander("Full error details"):
        st.code("\n\n".join(f"{source_name(k)}: {v}" for k, v in errors.items()))
    st.stop()


# --------------------------------------------------------------------------
# Tab 1: Trends (every indicator for one chosen entity)
# --------------------------------------------------------------------------

DEFAULT_ENTITY = "DEU"  # Trends tab's initial choice (Germany); the list's first entry, World, if absent
TREND_SINGLE_COLOR = du.DENIM  # charts with one series
TREND_CHART_HEIGHT = 370  # px: three charts per row
# Title, italic gray subtitle (the unit) and the legend row stacked above the plot. Every Trends
# chart reserves the legend row, even single-series ones without a legend, so the plots in a
# row line up.
TREND_TITLE_PX, TREND_SUBTITLE_PX, TREND_LEGEND_PX = 16, 13, 13
TREND_MARGIN_TOP = 86
SECTION_GAP_PX = 16  # extra space above each Trends section header (1rem)
SECTION_HEADER_GAP_BELOW_PX = 4  # and below it, before its notes and charts (0.25rem)
FORECAST_BAR_ALPHA = 0.5  # forecast-year bars at half strength (observed ones solid)
# Chart and map subtitles: the lightest gray that still passes WCAG AA
# contrast on white (5.5:1) -- the next step, #9d9d9d, is only 2.7:1.
SUBTITLE_COLOR = "#696969"
# Left indent (px) for each chart's title, unit line, legend and footer. (The y-axis tick labels
# start at ~32px: Streamlit's Plotly theme reserves room for an axis title plus padding there.)
TREND_TEXT_INDENT = 8


def count_unit(max_abs: float, base: str = "people") -> tuple[float, str]:
    """(divisor, unit name) that keeps a count readable: 8.1 billions, not 8,100,000,000. base
    is the unit when no scaling is needed."""
    for divisor, unit in [(1e12, "trillions"), (1e9, "billions"), (1e6, "millions"), (1e3, "thousands")]:
        if max_abs >= divisor:
            return divisor, unit
    return 1.0, base


def symmetric_axis(lo: float, hi: float, mid: float) -> dict:
    """
    y-axis settings for data in [lo, hi]: a range symmetric around mid (e.g. 0.25-0.75 around
    0.5), 10% wider than the data's largest distance from mid, with ticks at mid +- k * a round
    step (1, 2, 2.5 or 5 x 10^n; 2-4 steps per half), so mid is always a tick. For a bounded
    score (mid > 0), never wider than the scale itself (0 to 2 x mid); around 0 (e.g. the Economic
    Complexity Index) there is no such bound.
    """
    half = max(abs(hi - mid), abs(mid - lo), 1e-9) * 1.1
    if mid > 0:
        half = min(half, mid)
    magnitude = 10 ** np.floor(np.log10(half / 2))
    step = next(m * magnitude for m in (1, 2, 2.5, 5, 10) if half / (m * magnitude) <= 4)
    return dict(range=[mid - half, mid + half], tickmode="linear", tick0=mid, dtick=float(step))


def trend_chart(
    lines: dict[str, pd.Series],
    colors: dict[str, str],
    *,
    title: str,
    y_suffix: str = "",
    y_format: str = ",.2f",
    hline_zero: bool = False,
    forecast_x: float = math.inf,
    y_mid: float | None = None,
    y_extent: tuple[float, float] | None = None,
    ref_line: tuple[float, str] | None = None,
    ref_band: tuple[float, float, str] | None = None,
    y_log: bool = False,
) -> go.Figure | None:
    """
    Line chart for the Trends tab: each series split into solid (observed) and dotted
    (forecast) parts at forecast_x (series_spec sets it from the data, du.series_split; the default,
    math.inf, means no projections). No axis titles (the unit is in the subtitle); multi-line charts get
    a legend across the top. y_suffix is for the tooltip only. None if no series has data. hline_zero=True draws a
    zero line and extends the y-axis to include 0, so the line shows even for all-positive data.
    y_mid (e.g. 50 on a 0-100 score, 0.5 on a 0-1 one): the y-axis is symmetric around it, with
    a tick on it (see symmetric_axis). y_extent: the (min, max) that axis must cover, instead of
    this chart's own data -- e.g. a whole index's, or GDP and GNI per capita together, so those
    charts share one y-axis range (with or without y_mid).
    ref_line=(value, label): a dashed, labelled reference line (e.g. 2.1, the replacement fertility
    rate; 100, the US price level), with the y-axis extended to include it.
    ref_band=(low, high, label): a labelled reference range (e.g. 4-6% of GDP for education spending),
    shaded in du.REF_BAND_COLOR behind the data (translucent, so the gridlines show through), with no
    edge lines, the y-axis extended to include it.
    y_log: a signed log axis, sign * log10(1 + |y|) (as the maps' signed_log), so a few extreme years
    (hyperinflation) don't flatten the rest; ticks and tooltips show the real values. Say so in the
    chart's note.
    """
    lines = {label: s.dropna() for label, s in lines.items()}
    lines = {label: s for label, s in lines.items() if not s.empty}
    if not lines:
        return None
    split = forecast_x
    fig = go.Figure()
    if hline_zero:
        fig.add_hline(y=0, line_width=1, line_color=du.ZERO_LINE_COLOR)
    for label, s in lines.items():
        add_split_line(
            fig, s, split, name=label, legendgroup=label,
            line=dict(color=colors.get(label, TREND_SINGLE_COLOR), width=2),
            hovertemplate=f"{label}: <b>%{{y:{y_format}}}{y_suffix}</b><extra></extra>",
        )
    fig = style_fig(fig, title=title, y_title="", legend=len(lines) > 1, legend_px=TREND_LEGEND_PX,
                    height=TREND_CHART_HEIGHT)
    if y_log:
        values = pd.concat(lines.values())
        for trace in fig.data:
            real = np.asarray(trace.y, dtype=float)
            trace.customdata = real
            trace.y = _slog(real)
            if trace.hovertemplate:
                trace.hovertemplate = trace.hovertemplate.replace("%{y", "%{customdata")
        fig.update_yaxes(**signed_log_axis(float(values.min()), float(values.max()), include_zero=hline_zero))
        fig.update_layout(margin_b=0)
        return fig
    if hline_zero:
        fig.update_yaxes(rangemode="tozero")
    ref_values = []
    if ref_line is not None:
        value, label = ref_line
        fig.add_hline(y=value, line_width=1, line_dash="dash", line_color=REF_LINE_COLOR,
                      annotation_text=label, annotation_position="top left",
                      annotation_font=dict(family=FONT, size=11, color=REF_LINE_COLOR))
        ref_values.append(value)
    if ref_band is not None:
        low, high, label = ref_band
        fig.add_hrect(y0=low, y1=high, layer="below", line_width=0, fillcolor=du.REF_BAND_COLOR,
                      opacity=du.REF_BAND_OPACITY,
                      annotation_text=label, annotation_position="top left",
                      annotation_font=dict(family=FONT, size=11, color=REF_LINE_COLOR))
        ref_values += [low, high]
    if ref_values and y_mid is None and y_extent is None:  # extend the axis to the line or band
        values = pd.concat(lines.values())
        y_extent = (min(float(values.min()), *ref_values), max(float(values.max()), *ref_values))
    if y_mid is not None:
        values = pd.concat(lines.values())
        lo, hi = y_extent or (float(values.min()), float(values.max()))
        fig.update_yaxes(**symmetric_axis(lo, hi, y_mid))
        fig.add_hline(y=y_mid, line_width=1, line_color=du.ZERO_LINE_COLOR)  # styled like the zero lines
    elif y_extent is not None:
        # A fixed range, so charts given the same y_extent line up; 5% headroom, like Plotly's
        # autorange, but no padding below a zero baseline.
        lo, hi = y_extent
        if hline_zero:
            lo, hi = min(lo, 0.0), max(hi, 0.0)
        pad = (hi - lo) * 0.05 or 1.0  # (a flat zero series has no span)
        fig.update_yaxes(range=[lo if hline_zero and lo == 0 else lo - pad, hi + pad])
    fig.update_layout(margin_b=0)
    return fig


def trend_stacked_bar(
    lines: dict[str, pd.Series],
    colors: dict[str, str],
    *,
    title: str,
    y_suffix: str = "",
    y_format: str = ",.2f",
    hover_only: dict[str, pd.Series] | None = None,
    forecast_x: float = math.inf,
) -> go.Figure | None:
    """
    Stacked bars, one per year (first series at the bottom). barmode "relative" stacks
    positive values above zero and negative ones below. Solid fill for observed years,
    FORECAST_BAR_ALPHA for forecast years (>= forecast_x, see trend_chart). Bars
    are about twice as wide as the gaps between them. hover_only series (e.g. a total)
    appear in the tooltip without being drawn.
    Only years where every series has a value are drawn: a gap would otherwise stack as 0
    (e.g. birth/death rates are forecast only every 5 years, net migration yearly).
    """
    wide = pd.DataFrame(lines).dropna(how="any")
    if wide.empty:
        return None
    split = forecast_x
    opacity = [FORECAST_BAR_ALPHA if year >= split else 1.0 for year in wide.index]
    fig = go.Figure()
    for label in wide.columns:
        color = colors.get(label, TREND_SINGLE_COLOR)
        fig.add_bar(
            x=wide.index, y=wide[label], name=label,
            marker=dict(color=[_hex_rgba(color, o) for o in opacity], line_width=0),
            hovertemplate=f"{label}: <b>%{{y:{y_format}}}{y_suffix}</b><extra></extra>",
        )
    for label, s in (hover_only or {}).items():
        s = s.reindex(wide.index)  # same years as the bars
        fig.add_trace(go.Scatter(
            x=s.index, y=s.values, mode="lines", line=dict(width=0, color="rgba(0,0,0,0)"), showlegend=False,
            hovertemplate=f"{label}: <b>%{{y:{y_format}}}{y_suffix}</b><extra></extra>",
        ))
    fig.update_layout(barmode="relative", bargap=1 / 3)
    fig = style_fig(fig, title=title, y_title="", legend=len(wide.columns) > 1, legend_px=TREND_LEGEND_PX,
                    height=TREND_CHART_HEIGHT)
    fig.update_layout(margin_b=0)
    return fig


def trend_title(name: str, unit: str, subtitle_px: int = TREND_SUBTITLE_PX) -> str:
    """Chart title in bold headline case, then the unit as an italic sentence-case subtitle in
    SUBTITLE_COLOR."""
    return (f"<b>{headline_case(name)}</b><br>"
            f'<span style="font-size:{subtitle_px}px;color:{SUBTITLE_COLOR}"><i>{sentence_case(unit)}</i></span>')


def entity_header(name: str, countries: pd.DataFrame, code: str):
    """The chosen entity's name as a header, with its round flag in front for a real country
    (World, regions and income groups have none; neither does a flag that fails to load)."""
    flag = None
    if code in du.real_country_codes(countries):
        flag = flag_image(countries.set_index("country_code")["iso2_code"].get(code), scale=1.0)
    img = (f'<img src="{flag}" alt="" style="height:0.9em;vertical-align:-0.1em;margin-right:0.35em">'
           if flag else "")
    st.markdown(f"<h2>{img}{html.escape(name)}</h2>", unsafe_allow_html=True)


def trends_entity_options(data: pd.DataFrame, countries: pd.DataFrame) -> dict[str, str]:
    """code -> World Bank name: World, the 7 regions, the 4 income groups, then every country
    (alphabetical) with any data."""
    names = countries.set_index("country_code")["country_name"].to_dict()
    with_data = set(data["country_code"].unique())
    options = {du.WORLD_CODE: names.get(du.WORLD_CODE, "World")}
    options.update({code: names.get(code, name) for code, name in du.REGION_CODES.items()})
    options.update({code: names.get(code, name) for code, name in du.INCOME_CODES.items()})
    country_codes = [c for c in du.real_country_codes(countries) if c in with_data]
    options.update(dict(sorted(((c, names[c]) for c in country_codes), key=lambda kv: kv[1])))
    return options


REF_LINE_COLOR = "#696969"  # reference lines (replacement fertility, US price level): dashed, gray
HIST_REF_LINE_COLOR = du.BLACK  # the same reference lines on the Distributions histograms: dotted, black
# Reference marks drawn on both tabs: (value(s), label) -- trend_chart's ref_line / ref_band and the
# Distributions spec's vlines / band.
REPLACEMENT_LINE = (du.REPLACEMENT_LEVEL, "Replacement level (2.1)")
U5_MORTALITY_LINE = (du.U5_MORTALITY_TARGET, "SDG target for 2030 (25)")
POVERTY_LINE = (du.POVERTY_TARGET, "Global target for 2030 (3%)")
POVERTY_TARGET_NOTE = "The 3% target is for the world as a whole by 2030, not for each country."
EDUCATION_BAND = (*du.EDUCATION_SPENDING_BENCHMARK, "Education 2030 benchmark (4–6% of GDP)")


def _slog(x):
    """sign * log10(1 + |x|): a log scale that also takes 0 and negative values."""
    return np.sign(x) * np.log10(1 + np.abs(x))


def signed_log_axis(lo: float, hi: float, include_zero: bool = True) -> dict:
    """y-axis settings for data in [lo, hi] drawn with _slog: ticks at 0 and +-1, 3, 10, 30,
    100, ... (only the powers of 10 on ranges wider than three of them), labelled with the real
    values; 5% headroom."""
    if include_zero:
        lo, hi = min(lo, 0.0), max(hi, 0.0)
    a, b = float(_slog(lo)), float(_slog(hi))
    pad = (b - a) * 0.05 or 0.1
    magnitudes = [m * 10 ** k for k in range(0, 8) for m in ((1, 3) if b - a <= 3 else (1,))]
    ticks = sorted({0.0, *(v for m in magnitudes for v in (m, -m))})
    ticks = [v for v in ticks if a - pad <= _slog(v) <= b + pad]
    return dict(range=[a - pad if not (include_zero and lo == 0) else a, b + pad], tickmode="array",
                tickvals=[float(_slog(v)) for v in ticks],
                ticktext=[("−" if v < 0 else "") + f"{abs(v):,.0f}" for v in ticks])


def global_extent(data: pd.DataFrame, codes: list[str]) -> tuple[float, float] | None:
    """(min, max) of these series over every country and year in the data, so a chart's y-axis is
    the same for whichever country is selected (index_extent's counterpart across countries)."""
    ranges = du.series_ranges(data).reindex(codes).dropna()
    return (float(ranges["min"].min()), float(ranges["max"].max())) if len(ranges) else None


def trend_spec(chart_fn, lines: dict[str, pd.Series], colors: dict[str, str], title: str, unit: str, *,
               sources: list[tuple[str, str]], note: str | None = None, **kw) -> dict:
    """One Trends chart: chart_fn(lines, colors, title=..., **kw), with its data sources as
    [(footer label, source key)] (the key looks up its release date, du.source_updates) and an
    optional note, for the footer."""
    return dict(chart_fn=chart_fn, lines=lines, colors=colors, title=title, unit=unit, sources=sources, note=note,
                kw=kw)


def place_title_and_legend(fig: go.Figure, height: int, margin_top: int, title_px: int, top_px: int = 14):
    """Title (with its subtitle line) left-aligned top_px below the chart's top edge. The legend
    (set up in style_fig) sits in a row under it, just above the plot (legends
    go between the title/subtitle and the chart). margin_top reserves room for all three."""
    fig.update_layout(title_yref="container", title_y=1 - top_px / height, title_yanchor="top",
                      title_xref="container", title_x=0, title_xanchor="left", title_pad_l=TREND_TEXT_INDENT,
                      title_font_size=title_px, margin_t=margin_top)


def render_trend_section(header: str, charts: list[dict], entity_name: str,
                         x_errors: dict[str, str] | None = None, sources: list[str] = (),
                         caption: str | None = None, updates: dict[str, dt.date | None] | None = None) -> bool:
    """
    A Trends section: its header, a warning for any of `sources` that failed to load, then its
    charts three per row, each with its legend (multi-series charts) and source footer. Charts
    tagged with a row (in_rows()) start a new row with each group, so a short row stays short;
    untagged charts just fill rows of three. Charts without data for this entity are left out, with
    one note under the header naming them; a section where no chart has data is skipped entirely,
    header included. caption: a line under the header. updates: {source key: release date}
    (du.source_updates) for each footer's "Last updated". Returns whether it was drawn.
    """
    updates = updates or {}
    figs = [(spec, spec["chart_fn"](spec["lines"], spec["colors"], title=trend_title(spec["title"], spec["unit"]),
                                    **spec["kw"]))
            for spec in charts]
    shown = [(spec, fig) for spec, fig in figs if fig is not None]
    if not shown:
        return False
    st.space(SECTION_GAP_PX)  # extra space above each section header
    st.subheader(header)
    st.space(SECTION_HEADER_GAP_BELOW_PX)
    if caption:
        st.caption(caption)
    failed_sources_warning(x_errors or {}, list(sources))
    if len(shown) < len(figs):
        missing = ", ".join(f"“{spec['title']}”" for spec, fig in figs if fig is None)
        st.info(f"{len(shown)} of {len(figs)} indicators have data for {entity_name}. No data: {missing}.")
    groups: dict[int, list] = {}
    for spec, fig in shown:
        groups.setdefault(spec.get("row", 0), []).append((spec, fig))
    rows = [group[i:i + 3] for group in groups.values() for i in range(0, len(group), 3)]
    for n, row in enumerate(rows):
        if n:
            st.space(24)  # extra 1.5rem gap between rows
        for col, (spec, fig) in zip(st.columns(3), row):
            with col:
                place_title_and_legend(fig, TREND_CHART_HEIGHT, TREND_MARGIN_TOP, TREND_TITLE_PX)
                st.plotly_chart(fig, width="stretch")
                # -1.25rem: cancels Streamlit's 1rem element gap and part of the blank space
                # Plotly leaves under the x-axis labels.
                source_footer(indent=TREND_TEXT_INDENT, note=spec["note"],
                              source=[label for label, _ in spec["sources"]],
                              updated=[updates.get(key) for _, key in spec["sources"]], margin_top="-1.25rem")
    return True


def in_rows(*rows: list[dict]) -> list[dict]:
    """Chart specs tagged with their row number, for a section laid out in fixed rows
    (render_trend_section starts each row on a new line)."""
    return [dict(spec, row=n) for n, row in enumerate(rows) for spec in row]


def failed_sources_warning(errors: dict[str, str], sources: list[str]):
    """A warning naming which of `sources` failed to load (their charts are empty), with details."""
    failed = [s for s in sources if s in errors]
    if not failed:
        return
    names = "; ".join(source_name(s) for s in failed)
    st.warning(f"Couldn't load data from: {names}. Charts from these sources are empty. "
               "Use **Refresh data** in the sidebar to retry.")
    with st.expander("Error details"):
        st.code("\n".join(f"{s}: {errors[s]}" for s in failed))


def series_spec(chart_fn, series: dict[str, str], t: pd.DataFrame, data: pd.DataFrame, colors: dict[str, str],
                title: str, unit: str, *, note: str | None = None, **kw) -> dict:
    """trend_spec for {line label: series code} (columns of t, du.trends_data): the forecast split
    (du.series_split: projections dotted, a series without them solid throughout) comes from the first
    code. The footer names each source once, in the order of the lines, with its release date (the
    Observed/Forecast legend at the top of the tab explains the dotted lines, so the footer doesn't).
    The note joins every code's ds.ESTIMATE_NOTES entry, once each (a note contained in another one
    is dropped)."""
    first = next(iter(series.values()))
    split = du.series_split(first, data)
    keys = list(dict.fromkeys(ds.source_of(code) for code in series.values()))
    sources = [(du.SOURCE_LABELS[key], key) for key in keys]
    notes = list(dict.fromkeys(ds.ESTIMATE_NOTES[c] for c in series.values() if c in ds.ESTIMATE_NOTES))
    notes = [n for n in notes if not any(n != m and n in m for m in notes)] + ([note] if note else [])
    return trend_spec(chart_fn, {label: t[code] for label, code in series.items()}, colors, title, unit,
                      sources=sources, note=" ".join(notes) or None, forecast_x=split, **kw)


def demographics_charts(t: pd.DataFrame, data: pd.DataFrame) -> list[dict]:
    pop_div, pop_unit = count_unit(t[du.POP_TOTAL].abs().max())
    ni_div, ni_unit = count_unit(t[[du.NATURAL_INCREASE, du.NET_MIGRATION]].abs().max().max())
    # Counts shown in readable units (millions of people, ...): those columns divided by their scale.
    t = t.assign(**{du.POP_TOTAL: t[du.POP_TOTAL] / pop_div, du.NET_MIGRATION: t[du.NET_MIGRATION] / ni_div,
                    du.NATURAL_INCREASE: t[du.NATURAL_INCREASE] / ni_div})

    def fmt(divisor):  # whole people when unscaled, else two decimals
        return ",.0f" if divisor == 1.0 else ",.2f"

    c = du.CATEGORICAL_COLORS  # #2057a7, #f2bc40, #202020, #d3d3d3, #c43d4d, #287c6f, ...
    return [
        series_spec(trend_chart, {"Population": du.POP_TOTAL}, t, data, {},
                    "Total population", pop_unit, y_format=fmt(pop_div), hline_zero=True),
        series_spec(trend_chart, {"Growth rate": "POP:SP.POP.GROW"}, t, data, {},
                    "Annual population growth rate", "%", y_suffix="%", hline_zero=True),
        series_spec(trend_chart, {"Birth rate": du.BIRTH_RATE, "Death rate": du.DEATH_RATE}, t, data,
                    {"Birth rate": c[0], "Death rate": c[1]},
                    "Birth and death rates", "births/deaths per 1,000 population", hline_zero=True),
        series_spec(trend_chart, {"Fertility rate": "POP:SP.DYN.TFRT.IN"}, t, data, {},
                    "Total fertility rate", "live births per woman", hline_zero=True,
                    ref_line=REPLACEMENT_LINE),
        series_spec(trend_chart, {"Under-5 mortality": "POP:SH.DYN.MORT"}, t, data, {},
                    "Under-5 mortality rate", "deaths per 1,000 live births", y_format=",.1f", hline_zero=True,
                    ref_line=U5_MORTALITY_LINE),
        series_spec(trend_chart, {"Ages 0–14": "POP:SP.POP.0014.TO.ZS", "Ages 15–64": "POP:SP.POP.1564.TO.ZS",
                                  "Ages 65+": "POP:SP.POP.65UP.TO.ZS"}, t, data,
                    {"Ages 0–14": c[0], "Ages 15–64": c[2], "Ages 65+": c[1]},
                    "Age group shares", "%", y_suffix="%", hline_zero=True),
        series_spec(trend_stacked_bar, {"Youth": "POP:SP.POP.DPND.YG", "Elderly": "POP:SP.POP.DPND.OL"}, t, data,
                    {"Youth": c[0], "Elderly": c[1]},
                    "Age dependency ratio", "# dependents per 100 working-age people",
                    y_format=",.1f", hover_only={"Total": t["POP:SP.POP.DPND"]}),
        series_spec(trend_chart, {"Total": "POP:SP.DYN.LE00.IN", "Female": "POP:SP.DYN.LE00.FE.IN",
                                  "Male": "POP:SP.DYN.LE00.MA.IN"}, t, data,
                    {"Total": c[2], "Female": c[1], "Male": c[0]},
                    "Life expectancy at birth", "years", y_format=",.1f"),
        series_spec(trend_stacked_bar, {"Net migration": du.NET_MIGRATION, "Natural growth": du.NATURAL_INCREASE},
                    t, data, {"Natural growth": c[1], "Net migration": c[0]},
                    "Natural population growth & net migration", f"{ni_unit} (natural growth = births minus deaths)",
                    y_format=fmt(ni_div)),
    ]


def scaled_count(t: pd.DataFrame, code: str, noun: str) -> tuple[pd.DataFrame, str, str]:
    """t with column `code` divided to a readable scale (1.8 trillions, not 1.8e12), plus the
    chart's unit ("trillions of <noun>", or just noun unscaled) and its number format."""
    div, word = count_unit(t[code].abs().max(), base=noun)
    return (t.assign(**{code: t[code] / div}), noun if div == 1 else f"{word} of {noun}",
            ",.0f" if div == 1 else ",.2f")


ECI_SCALE = 2.5  # the Economic Complexity Index's usual range, +-


# Agriculture, industry, services: the same colors in the output and employment charts.
SECTOR_COLORS = {"Agriculture": du.CATEGORICAL_COLORS[1], "Industry": du.CATEGORICAL_COLORS[2],
                 "Services": du.CATEGORICAL_COLORS[0]}


def economics_charts(t: pd.DataFrame, data: pd.DataFrame) -> list[dict]:
    """Five rows: the headline trio
    (growth, prices, unemployment); the fiscal block (revenue and expenditure -> balance -> debt:
    the balance is revenue minus expenditure, and deficits build up the debt); the external block;
    investment and finance; then size and structure (GDP is a size measure, not a headline trend)."""
    c = du.CATEGORICAL_COLORS
    t, gdp_unit, gdp_format = scaled_count(t, "WB:NY.GDP.MKTP.PP.KD", "constant 2021 international $")
    pct = dict(y_suffix="%", y_format=",.1f", hline_zero=True)
    # Output and employment by sector on one shared y-axis range, so the two charts read side by side
    sector_codes = ["WB:NV.AGR.TOTL.ZS", "WB:NV.IND.TOTL.ZS", "WB:NV.SRV.TOTL.ZS",
                    "WB:SL.AGR.EMPL.ZS", "WB:SL.IND.EMPL.ZS", "WB:SL.SRV.EMPL.ZS"]
    sector = dict(pct, y_extent=index_extent(t, sector_codes))
    return in_rows(
        [
            series_spec(trend_chart, {"GDP growth": "IMF:NGDP_RPCH"}, t, data, {},
                        "Real GDP growth", "annual % change", y_suffix="%", hline_zero=True),
            series_spec(trend_chart, {"Consumer prices": "IMF:PCPIPCH"}, t, data, {},
                        "Consumer prices", "annual average, % change (log scale)", y_suffix="%", y_format=",.1f",
                        hline_zero=True, y_log=True,
                        note="Log scale: each step up the axis is about ten times larger, so years of very high "
                             "inflation don't flatten the rest; deflation (below 0) is mirrored below the zero line."),
            series_spec(trend_chart, {"Unemployment": "WB:SL.UEM.TOTL.ZS"}, t, data, {},
                        "Unemployment rate", "% of labor force (modelled ILO estimate)", y_suffix="%", hline_zero=True),
        ],
        [
            # Fiscal block. The gap between the two lines is the deficit or surplus.
            series_spec(trend_chart, {"Revenue": "IMF:GGR_NGDP", "Expenditure": "IMF:GGX_NGDP"}, t, data,
                        {"Revenue": c[0], "Expenditure": c[1]},
                        "Government revenue and expenditure", "% of GDP (general government)", **pct),
            series_spec(trend_chart, {"Budget balance": "IMF:GGXCNL_NGDP"}, t, data, {},
                        "Government budget balance", "% of GDP (net lending/borrowing)", y_suffix="%", y_format=",.1f",
                        y_mid=0),
            series_spec(trend_chart, {"Government debt": "IMF:GGXWDG_NGDP"}, t, data, {},
                        "General government gross debt", "% of GDP", **pct),
        ],
        [
            # External block: the whole economy's position, not a fiscal indicator
            series_spec(trend_chart, {"Current account": "IMF:BCA_NGDPD"}, t, data, {},
                        "Current account balance", "% of GDP", y_suffix="%", y_format=",.1f", y_mid=0),
            series_spec(trend_chart, {"FDI inflows": "WB:BX.KLT.DINV.WD.GD.ZS"}, t, data, {},
                        "Foreign direct investment, net inflows", "% of GDP", y_suffix="%", y_format=",.1f",
                        hline_zero=True),
            series_spec(trend_chart, {"Private credit": "WB:FS.AST.PRVT.GD.ZS"}, t, data, {},
                        "Domestic credit to private sector", "% of GDP", **pct),
        ],
        [
            series_spec(trend_chart, {"Price level": "WB:PA.NUS.GDP.PLI"}, t, data, {},
                        "Price level relative to the US", "price level index of GDP (US = 100)",
                        y_format=",.1f", hline_zero=True, ref_line=(100, "US = 100")),
            series_spec(trend_chart, {"Net energy imports": "WB:EG.IMP.CONS.ZS"}, t, data, {},
                        "Net energy imports", "% of energy use (negative = net exporter)", **pct),
        ],
        [
            series_spec(trend_chart, {"GDP": "WB:NY.GDP.MKTP.PP.KD"}, t, data, {},
                        "GDP, PPP", gdp_unit, y_format=gdp_format, hline_zero=True),
            # Two charts side by side, not one per sector: the gap between
            # agriculture's share of jobs and of output is the story. Lines,
            # not stacked bars, on a shared y-axis.
            series_spec(trend_chart, {"Agriculture": "WB:NV.AGR.TOTL.ZS", "Industry": "WB:NV.IND.TOTL.ZS",
                                           "Services": "WB:NV.SRV.TOTL.ZS"}, t, data, SECTOR_COLORS,
                        "Output by sector", "value added, % of GDP", **sector),
            series_spec(trend_chart, {"Agriculture": "WB:SL.AGR.EMPL.ZS", "Industry": "WB:SL.IND.EMPL.ZS",
                                           "Services": "WB:SL.SRV.EMPL.ZS"}, t, data, SECTOR_COLORS,
                        "Employment by sector", "% of total employment", **sector),
        ],
    )


def labour_charts(t: pd.DataFrame, data: pd.DataFrame) -> list[dict]:
    """Who takes part in the labour market, which young people are left out, and what share of
    national income goes to workers (one row). All ILO modelled.
    Each chart's y-axis runs from 0 to the highest value any country reaches, so it is the same
    whichever country is selected, without a 0-100 scale's empty top."""
    def pct(code):
        top = (global_extent(data, [code]) or (0, 100))[1]
        return dict(y_suffix="%", y_format=",.1f", hline_zero=True, y_extent=(0, top))
    return [
        series_spec(trend_chart, {"Participation": "WB:SL.TLF.CACT.ZS"}, t, data, {},
                    "Labour force participation rate", "% of population aged 15+", **pct("WB:SL.TLF.CACT.ZS")),
        series_spec(trend_chart, {"NEET rate": "ILO:NEET"}, t, data, {},
                    "Youth not in employment, education or training", "% of youth aged 15–24", **pct("ILO:NEET")),
        series_spec(trend_chart, {"Labour income share": "ILO:LABOUR_SHARE"}, t, data, {},
                    "Labour income share", "% of GDP", **pct("ILO:LABOUR_SHARE")),
    ]


def industry_charts(t: pd.DataFrame, data: pd.DataFrame) -> list[dict]:
    """How much a country makes, how advanced it is, how much of what it sells abroad is
    manufactured, its overall productive know-how, and investment in new technology (SDG 9.2.1,
    9.b.1 and 9.5.1)."""
    pct = dict(y_suffix="%", y_format=",.1f", hline_zero=True)
    # ECI is standardised every year (world mean 0, roughly -2.5 to +2.5):
    # one fixed scale for every country, widened only for outliers.
    eci = t["ECI:ECI"].dropna()
    eci_extent = (min(-ECI_SCALE, eci.min()), max(ECI_SCALE, eci.max())) if len(eci) else None
    return [
        series_spec(trend_chart, {"Manufacturing": "WB:NV.IND.MANF.ZS"}, t, data, {},
                    "Manufacturing contribution to GDP", "% of GDP", **pct),
        series_spec(trend_chart, {"Medium & high-tech share": "WB:NV.MNF.TECH.ZS.UN"}, t, data, {},
                    "Medium and high-tech manufacturing", "% of manufacturing value added", **pct),
        series_spec(trend_chart, {"Manufactured exports": "WB:TX.VAL.MANF.ZS.UN"}, t, data, {},
                    "Manufactured exports", "% of total merchandise exports", **pct),
        series_spec(trend_chart, {"ECI": "ECI:ECI"}, t, data, {},
                    "Economic Complexity Index", "relative to other countries (0 = world average)", y_mid=0,
                    y_extent=eci_extent),
        series_spec(trend_chart, {"R&D expenditure": "WB:GB.XPD.RSDV.GD.ZS"}, t, data, {},
                    "Research and development expenditure", "% of GDP", y_suffix="%", hline_zero=True),
    ]


def climate_charts(t: pd.DataFrame, data: pd.DataFrame) -> list[dict]:
    # ND-GAIN: y-axis from the lowest to the highest value of any country:
    # 50 / 0.5 is not a meaningful midpoint for these scores, which mostly fall between ~30 and ~75.
    c = du.CATEGORICAL_COLORS
    return [
        # Section story: emissions (per person, then total) -> how much
        # energy the economy uses -> how clean that energy is -> the land side -> climate risk.
        series_spec(trend_chart, {"GHG per capita": "WB:EN.GHG.ALL.PC.CE.AR5"}, t, data, {},
                    "Greenhouse gas emissions per capita", "tonnes of CO₂-equivalent, excl. land use",
                    hline_zero=True),
        series_spec(trend_chart, {"GHG emissions": "WB:EN.GHG.ALL.MT.CE.AR5"}, t, data, {},
                    "Total greenhouse gas emissions", "million tonnes of CO₂-equivalent, excl. land use",
                    y_format=",.1f", hline_zero=True),
        # Next to greenhouse gases: the two emission drivers of the Kaya decomposition (energy per unit
        # of GDP, emissions per unit of energy).
        series_spec(trend_chart, {"Energy intensity": "WB:EG.EGY.PRIM.PP.KD"}, t, data, {},
                    "Energy intensity", "megajoules per constant 2021 PPP $ of GDP (lower = more efficient)",
                    y_format=",.2f", hline_zero=True),
        series_spec(trend_chart, {"Renewable share": "WB:EG.FEC.RNEW.ZS"}, t, data, {},
                    "Renewable energy share", "% of final energy consumption", y_suffix="%", y_format=",.1f",
                    hline_zero=True, y_extent=(0, 100)),
        series_spec(trend_chart, {"Forest area": "WB:AG.LND.FRST.ZS"}, t, data, {},
                    "Forest area", "% of land area", y_suffix="%", y_format=",.1f", hline_zero=True),
        series_spec(trend_chart, {"ND-GAIN index": "NDGAIN:GAIN"}, t, data, {},
                    "ND-GAIN country index", "0–100 (higher = better prepared to climate change)",
                    y_format=",.1f", y_extent=global_extent(data, ["NDGAIN:GAIN"])),
        series_spec(trend_chart, {"Vulnerability": "NDGAIN:VULNERABILITY", "Readiness": "NDGAIN:READINESS"},
                    t, data, {"Vulnerability": c[0], "Readiness": c[1]},
                    "Vulnerability and readiness to climate change", "ND-GAIN scores, 0–1", y_format=",.3f",
                    y_extent=global_extent(data, ["NDGAIN:VULNERABILITY", "NDGAIN:READINESS"])),
    ]


def index_extent(t: pd.DataFrame, codes: list[str]) -> tuple[float, float] | None:
    """(min, max) over all of an index's series for this entity, so its charts can share one
    y-axis range (trend_chart's y_extent); None if it has no data here."""
    values = t[codes].stack()
    return (float(values.min()), float(values.max())) if len(values) else None


def infrastructure_charts(t: pd.DataFrame, data: pd.DataFrame) -> list[dict]:
    """Access to the internet and to basic services (all WDI; the services are modelled from
    household surveys, see ds.ESTIMATE_NOTES). Fixed 0-100% axes: the
    question is how close a country is to universal access, which a data-fitted axis would hide."""
    c = du.CATEGORICAL_COLORS
    pct = dict(y_suffix="%", y_format=",.1f", hline_zero=True, y_extent=(0, 100))
    return [
        series_spec(trend_chart, {"Drinking water": "WB:SH.H2O.BASW.ZS", "Sanitation": "WB:SH.STA.BASS.ZS",
                                 "Hygiene": "WB:SH.STA.HYGN.ZS"}, t, data,
                    {"Drinking water": c[0], "Sanitation": c[1], "Hygiene": c[2]},
                    "Basic drinking water, sanitation and hygiene", "% of population with at least basic services",
                    **pct),
        # Together on one scale: the gap between them is the story --
        # households with power that still cook with wood or charcoal.
        series_spec(trend_chart, {"Electricity": "WB:EG.ELC.ACCS.ZS", "Clean cooking": "WB:EG.CFT.ACCS.ZS"}, t, data,
                    {"Electricity": c[0], "Clean cooking": c[1]},
                    "Access to electricity and clean cooking", "% of population", **pct),
        series_spec(trend_chart, {"Internet users": "WB:IT.NET.USER.ZS"}, t, data, {},
                    "Internet users", "% of population", **pct),
    ]


def living_standards_charts(t: pd.DataFrame, data: pd.DataFrame) -> list[dict]:
    """Average income, the typical person's (the median), then how it is shared (inequality), poverty, and how
    people rate their lives (happiness). GDP per capita measures production, GNI per capita
    residents' income (GDP plus net income from abroad): they differ strongly for Ireland,
    Luxembourg and some resource exporters. Both real and PPP-adjusted,
    on one shared y-axis range so the two can be compared at a glance."""
    extent = index_extent(t, ["WB:NY.GDP.PCAP.PP.KD", "WB:NY.GNP.PCAP.PP.KD"])
    return [
        series_spec(trend_chart, {"GDP per capita": "WB:NY.GDP.PCAP.PP.KD"}, t, data, {},
                    "GDP per capita, PPP", "constant 2021 international $", y_format=",.0f", hline_zero=True,
                    y_extent=extent),
        series_spec(trend_chart, {"GNI per capita": "WB:NY.GNP.PCAP.PP.KD"}, t, data, {},
                    "GNI per capita, PPP", "constant 2021 international $", y_format=",.0f", hline_zero=True,
                    y_extent=extent),
        # The typical person's living standard, often a fraction of GDP per capita (pulled up by the rich)
        series_spec(trend_chart, {"Median": "PIP:MEDIAN"}, t, data, {},
                    "Median income or consumption", "2021 PPP $ per person per day", y_format=",.2f",
                    hline_zero=True),
        series_spec(trend_chart, {"Gini index": "SWIID:GINI_DISP"}, t, data, {},
                    "Income inequality", "Gini index of disposable income, 0–100", y_format=",.1f", hline_zero=True),
        series_spec(trend_chart, {"Poverty rate": "PIP:POV_3_00"}, t, data, {},
                    "Poverty at $3.00 a day", "% of population (2021 PPP)", y_suffix="%", y_format=",.1f",
                    hline_zero=True, ref_line=POVERTY_LINE, note=POVERTY_TARGET_NOTE),
        series_spec(trend_chart, {"Life evaluation": "WHR:LADDER"}, t, data, {},
                    "Happiness: life evaluation", "Cantril ladder, 0–10 (3-year average)",
                    y_format=",.2f", hline_zero=True),
    ]


def education_charts(t: pd.DataFrame, data: pd.DataFrame) -> list[dict]:
    """Spending, attainment, then enrollment. Mean years of schooling (adults 25+, the stock of
    education, changes slowly) and expected years (a child entering school now, if current
    enrollment rates persist) share a chart: the gap shows how fast education levels are rising."""
    c = du.CATEGORICAL_COLORS
    pct = dict(y_suffix="%", y_format=",.1f", hline_zero=True)
    return [
        series_spec(trend_chart, {"Education spending": "WB:SE.XPD.TOTL.GD.ZS"}, t, data, {},
                    "Government expenditure on education", "% of GDP", ref_band=EDUCATION_BAND, **pct),
        series_spec(trend_chart, {"Expected (school entrants)": "UNDP:EYS", "Mean (adults 25+)": "UNDP:MYS"}, t, data,
                    {"Expected (school entrants)": c[0], "Mean (adults 25+)": c[1]},
                    "Mean and expected years of schooling", "years", y_format=",.1f", hline_zero=True),
        series_spec(trend_chart, {"Tertiary enrollment": "WB:SE.TER.ENRR"}, t, data, {},
                    "Tertiary school enrollment", "gross enrollment ratio, %", **pct),
    ]


def healthcare_charts(t: pd.DataFrame, data: pd.DataFrame) -> list[dict]:
    """How much a country spends on health, and who pays. Both WDI,
    from the WHO Global Health Expenditure Database (about a 2-year lag)."""
    pct = dict(y_suffix="%", y_format=",.1f", hline_zero=True)
    return [
        series_spec(trend_chart, {"Health spending": "WB:SH.XPD.CHEX.GD.ZS"}, t, data, {},
                    "Current health expenditure", "% of GDP", **pct),
        series_spec(trend_chart, {"Out-of-pocket spending": "WB:SH.XPD.OOPC.CH.ZS"}, t, data, {},
                    "Out-of-pocket health spending", "% of current health expenditure", **pct),
    ]


ECONOMICS_SOURCES = ["WDI", "IMF"]
LABOUR_SOURCES = ["WDI", "ILO"]
# A line under a Trends section's header.
SECTION_CAPTIONS = {"Labour market": "Read with the unemployment rate in Economics."}
CLIMATE_SOURCES = ["WDI", "NDGAIN"]


@st.fragment  # a widget in this tab reruns only this tab, not the other one
def tab_trends(data: pd.DataFrame, countries: pd.DataFrame, errors: dict[str, str]):
    """errors: {source key: message} for the failed sources."""
    options = trends_entity_options(data, countries)
    codes = list(options)
    entity = st.selectbox("Country or region", options=codes, format_func=options.get, key="trends_entity",
                          index=codes.index(DEFAULT_ENTITY) if DEFAULT_ENTITY in codes else 0)
    t = du.trends_data(data, entity)
    updates = load_source_updates()
    entity_header(options[entity], countries, entity)
    shared_legend([], {}, forecast_key=True)

    # A section with no data for this entity is skipped. If that's because its source failed to
    # load, the warning goes here at the top instead, so a failure never goes unnoticed.
    top_warnings, skipped_sources = st.container(), []
    sections = [  # (header, charts, sources behind them)
        ("Economics", economics_charts(t, data), ECONOMICS_SOURCES),
        ("Labour market", labour_charts(t, data), LABOUR_SOURCES),
        ("Industry & innovation", industry_charts(t, data), ["WDI", "ECI"]),
        ("Living standards", living_standards_charts(t, data), ["WDI", "SWIID", "PIP", "WHR"]),
        ("Demographics", demographics_charts(t, data), [du.POPULATION_SOURCE]),
        ("Climate", climate_charts(t, data), CLIMATE_SOURCES),
        ("Infrastructure & basic services", infrastructure_charts(t, data), ["WDI"]),
        ("Education", education_charts(t, data), ["WDI", "UNDP"]),
        ("Healthcare", healthcare_charts(t, data), ["WDI"]),
    ]
    for header, charts, sources in sections:
        if not render_trend_section(header, charts, options[entity], errors, sources,
                                    caption=SECTION_CAPTIONS.get(header), updates=updates):
            skipped_sources += [s for s in sources if s not in skipped_sources]
    with top_warnings:  # one warning, even when several skipped sections share a failed source
        failed_sources_warning(errors, skipped_sources)


# --------------------------------------------------------------------------
# Tab 2: Distributions (one indicator across countries, two years compared)
# --------------------------------------------------------------------------

def _short_count(n: float) -> str:
    """1e5 -> '100k', 3e6 -> '3M', 1e9 -> '1B', 1e12 -> '1T' (bin labels)."""
    for div, suffix in [(1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "k")]:
        if abs(n) >= div:
            return f"{n / div:g}{suffix}"
    return f"{n:g}"


def _edge_labels(edges: list[float], fmt) -> list[str]:
    """Labels for pd.cut bins [edges[i], edges[i+1]): open-ended first/last bins read '< x' / 'x+'."""
    labels = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        if lo == -np.inf:
            labels.append(f"< {fmt(hi)}")
        elif hi == np.inf:
            labels.append(f"{fmt(lo)}+")
        else:
            labels.append(f"{fmt(lo)} to {fmt(hi)}")
    return labels


_POP_EDGES = [0, 1e5, 3e5, 1e6, 3e6, 1e7, 3e7, 1e8, 3e8, 1e9, np.inf]

# label -> settings. bins: ("width", w) = equal-width bins of w (("width", w, "clip_tails") also
# folds the outer 1% at each end into open-ended edge bins); ("edges", edges, labels) = fixed,
# roughly log-spaced bins for values spanning several orders of magnitude. fmt is both a
# Python and a d3 (Plotly hover) number format. lower_is_better=True reverses the year map's color
# scale, so the darkest color marks the best values. map_scale: "log" colors by log10(value),
# "signed_log" by sign * log10(1 + |value|) around a diverging scale. bins_note: a line under
# the chart explaining uneven bins. vlines: [(value, label)] reference lines, band: (low, high, label)
# a reference range, both on bin edges and on the indicator's Trends chart too (ref_line / ref_band);
# note: a line for the chart's footer. Grouped by section like the Trends tab (DISTRIBUTION_SECTIONS);
# series is a du.SERIES code (e.g. "POP:SP.POP.TOTL", "IMF:NGDP_RPCH") or a derived one (du.NATURAL_CHANGE_RATE).
DEPENDENTS_UNIT = "# dependents per 100 working-age people"

DEMOGRAPHIC_DISTRIBUTIONS: dict[str, dict] = {
    "Total population": dict(
        series="POP:SP.POP.TOTL", unit="people", fmt=",.0f", map_scale="log",
        bins_note="Bins widen with the values (roughly ×3 each step), since countries differ by orders "
                  "of magnitude on this indicator.",
        bins=("edges", _POP_EDGES, ["< 100k"] + _edge_labels(_POP_EDGES, _short_count)[1:])),
    "Annual population growth rate": dict(
        series="POP:SP.POP.GROW", unit="percent", fmt=",.2f", suffix="%", bins=("width", 0.5, "clip_tails"), zero_mid=True),
    "Birth rate": dict(series="POP:SP.DYN.CBRT.IN", unit="births per 1,000 population", fmt=",.1f", bins=("width", 2)),
    "Death rate": dict(series="POP:SP.DYN.CDRT.IN", unit="deaths per 1,000 population", fmt=",.1f", bins=("width", 1)),
    "Fertility rate": dict(
        series="POP:SP.DYN.TFRT.IN", unit="live births per woman", fmt=",.2f", bins=("width", 0.1),
        vlines=[REPLACEMENT_LINE]),
    "Under-5 mortality rate": dict(series="POP:SH.DYN.MORT", unit="deaths per 1,000 live births", fmt=",.1f",
                                   bins=("width", 5), vlines=[U5_MORTALITY_LINE]),  # 25 on a bin edge
    "Children population share (0–14 years old)": dict(
        series="POP:SP.POP.0014.TO.ZS", unit="percent", fmt=",.1f", suffix="%", bins=("width", 2)),
    "Working age population share (15–64 years old)": dict(
        series="POP:SP.POP.1564.TO.ZS", unit="percent", fmt=",.1f", suffix="%", bins=("width", 2)),
    "Elderly population share (65+ years old)": dict(
        series="POP:SP.POP.65UP.TO.ZS", unit="percent", fmt=",.1f", suffix="%", bins=("width", 1)),
    "Age dependency ratio, Total": dict(series="POP:SP.POP.DPND", unit=DEPENDENTS_UNIT, fmt=",.1f",
                                       bins=("width", 5)),
    "Age dependency ratio, Old": dict(series="POP:SP.POP.DPND.OL", unit=DEPENDENTS_UNIT, fmt=",.1f",
                                      bins=("width", 2)),
    "Age dependency ratio, Young": dict(series="POP:SP.POP.DPND.YG", unit=DEPENDENTS_UNIT, fmt=",.1f",
                                        bins=("width", 5)),
    "Life expectancy at birth, Total": dict(series="POP:SP.DYN.LE00.IN", unit="years", fmt=",.1f", bins=("width", 1)),
    "Life expectancy at birth, Female": dict(series="POP:SP.DYN.LE00.FE.IN", unit="years", fmt=",.1f",
                                             bins=("width", 1)),
    "Life expectancy at birth, Male": dict(series="POP:SP.DYN.LE00.MA.IN", unit="years", fmt=",.1f", bins=("width", 1)),
    "Natural population change rate": dict(
        series=du.NATURAL_CHANGE_RATE, unit="people per 1,000 population", fmt=",.1f",
        bins=("width", 2), zero_mid=True),
    "Net migration rate": dict(
        series=du.NET_MIGRATION_RATE, unit="people per 1,000 population", fmt=",.1f",
        map_scale="signed_log", bins=("width", 2, "clip_tails")),  # small states reach +-50 and beyond
}


def _log_edges(edges: list[float]) -> tuple:
    """Fixed bins for values spanning orders of magnitude (edges from 0): the first reads '< x'."""
    return ("edges", edges, [f"< {_short_count(edges[1])}"] + _edge_labels(edges, _short_count)[1:])


PERCENT = "percent"
PCT_OF_GDP = "percent of GDP"
TENFOLD_NOTE = "Bins widen tenfold each step, since countries differ by orders of magnitude on this indicator."

ECONOMIC_DISTRIBUTIONS: dict[str, dict] = {
    # Same order as economics_charts.
    "Real GDP growth": dict(series="IMF:NGDP_RPCH", unit=PERCENT, fmt=",.1f", suffix="%",
                            bins=("width", 1, "clip_tails"), zero_mid=True),
    "Consumer prices": dict(series="IMF:PCPIPCH", unit=PERCENT, fmt=",.1f", suffix="%",
                      map_scale="signed_log", bins=("width", 1, "clip_tails")),  # hyperinflations reach 10,000%+
    "Unemployment rate": dict(series="WB:SL.UEM.TOTL.ZS", unit="percent of labor force", fmt=",.1f", suffix="%",
                              bins=("width", 1)),
    "General government revenue": dict(series="IMF:GGR_NGDP", unit=PCT_OF_GDP, fmt=",.1f", suffix="%",
                                       bins=("width", 5, "clip_tails")),
    "General government expenditure": dict(series="IMF:GGX_NGDP", unit=PCT_OF_GDP, fmt=",.1f", suffix="%",
                                           bins=("width", 5, "clip_tails")),
    "Government budget balance": dict(series="IMF:GGXCNL_NGDP", unit=PCT_OF_GDP, fmt=",.1f", suffix="%",
                                      bins=("width", 1, "clip_tails"), zero_mid=True),
    "General government gross debt": dict(series="IMF:GGXWDG_NGDP", unit=PCT_OF_GDP, fmt=",.1f", suffix="%",
                                          bins=("width", 10, "clip_tails")),
    "Current account balance": dict(series="IMF:BCA_NGDPD", unit=PCT_OF_GDP, fmt=",.1f", suffix="%",
                                    bins=("width", 2, "clip_tails"), zero_mid=True),
    "Foreign direct investment, net inflows": dict(series="WB:BX.KLT.DINV.WD.GD.ZS", unit=PCT_OF_GDP, fmt=",.1f",
                                                   suffix="%", bins=("width", 1, "clip_tails"), zero_mid=True),
    "Domestic credit to private sector": dict(series="WB:FS.AST.PRVT.GD.ZS", unit=PCT_OF_GDP, fmt=",.1f",
                                              suffix="%", bins=("width", 10, "clip_tails")),
    "Price level relative to the US": dict(series="WB:PA.NUS.GDP.PLI", unit="price level index of GDP (US = 100)",
                                           fmt=",.1f", bins=("width", 10, "clip_tails")),
    "Net energy imports": dict(series="WB:EG.IMP.CONS.ZS", unit="percent of energy use (negative = net exporter)",
                               fmt=",.1f", suffix="%", map_scale="signed_log",  # oil exporters reach -3,000%
                               bins=("width", 10, "clip_tails")),
    "GDP, PPP": dict(series="WB:NY.GDP.MKTP.PP.KD", unit="constant 2021 international $", fmt=",.0f",
                     map_scale="log", bins_note=TENFOLD_NOTE,
                     bins=_log_edges([0, 1e9, 1e10, 1e11, 1e12, 1e13, np.inf])),
    # Sector structure: agriculture's shares vary most (1-2% of jobs in rich countries, over 60% in
    # some poor ones); industry's employment share and services, largely the mirror image, are
    # Trends-only (TRENDS_ONLY_SERIES).
    "Agriculture, share of employment": dict(series="WB:SL.AGR.EMPL.ZS", unit="percent of total employment",
                                             fmt=",.1f", suffix="%", bins=("width", 5)),
    "Agriculture, share of GDP": dict(series="WB:NV.AGR.TOTL.ZS", unit="value added, percent of GDP", fmt=",.1f",
                                      suffix="%", bins=("width", 2, "clip_tails")),
    "Industry, share of GDP": dict(series="WB:NV.IND.TOTL.ZS", unit="value added, percent of GDP (incl. mining, "
                                                                    "utilities and construction)",
                                   fmt=",.1f", suffix="%", bins=("width", 5, "clip_tails")),
}

# Same order as labour_charts.
LABOUR_DISTRIBUTIONS: dict[str, dict] = {
    "Labour force participation rate": dict(series="WB:SL.TLF.CACT.ZS", unit="percent of population aged 15+",
                                            fmt=",.1f", suffix="%", bins=("width", 2)),
    "Youth NEET rate": dict(series="ILO:NEET", unit="percent of youth aged 15–24 not in employment, education "
                                                    "or training", fmt=",.1f", suffix="%", bins=("width", 2)),
    "Labour income share": dict(series="ILO:LABOUR_SHARE", unit=PCT_OF_GDP, fmt=",.1f", suffix="%",
                                bins=("width", 2)),
}

# Same order as industry_charts.
INDUSTRY_DISTRIBUTIONS: dict[str, dict] = {
    "Manufacturing contribution to GDP": dict(series="WB:NV.IND.MANF.ZS", unit=PCT_OF_GDP, fmt=",.1f", suffix="%",
                                              bins=("width", 2)),  # SDG indicator 9.2.1
    "Medium and high-tech manufacturing": dict(series="WB:NV.MNF.TECH.ZS.UN",
                                               unit="percent of manufacturing value added", fmt=",.1f",
                                               suffix="%", bins=("width", 5)),
    "Manufactured exports": dict(series="WB:TX.VAL.MANF.ZS.UN", unit="percent of total merchandise exports", fmt=",.1f",
                                 suffix="%", bins=("width", 5)),
    "Economic Complexity Index": dict(series="ECI:ECI", unit="score relative to other countries (0 = world average)",
                                      fmt=",.2f", bins=("width", 0.25, "clip_tails"), zero_mid=True),
    "R&D expenditure": dict(series="WB:GB.XPD.RSDV.GD.ZS", unit=PCT_OF_GDP, fmt=",.2f", suffix="%",
                            bins=("width", 0.25)),
}

PCT_OF_POPULATION = "percent of population"
WIDENING_NOTE = "Bins widen with the values, since countries differ by orders of magnitude on this indicator."
_INCOME_EDGES = [0, 1e3, 2e3, 5e3, 1e4, 2e4, 5e4, 1e5, np.inf]  # $ per person

# Same order as living_standards_charts.
LIVING_STANDARDS_DISTRIBUTIONS: dict[str, dict] = {
    "GDP per capita, PPP": dict(series="WB:NY.GDP.PCAP.PP.KD", unit="constant 2021 international $", fmt=",.0f",
                                map_scale="log", bins_note=WIDENING_NOTE, bins=_log_edges(_INCOME_EDGES)),
    "GNI per capita, PPP": dict(series="WB:NY.GNP.PCAP.PP.KD", unit="constant 2021 international $", fmt=",.0f",
                                map_scale="log", bins_note=WIDENING_NOTE, bins=_log_edges(_INCOME_EDGES)),
    "Median income or consumption": dict(series="PIP:MEDIAN", unit="2021 PPP $ per person per day", fmt=",.2f",
                                         map_scale="log", bins_note=WIDENING_NOTE,
                                         bins=_log_edges([0, 2, 5, 10, 20, 50, 100, np.inf])),
    "Income inequality (Gini index)": dict(series="SWIID:GINI_DISP", unit="Gini index of disposable income (0–100)",
                                           fmt=",.1f", bins=("width", 2)),
    "Poverty at $3.00 a day": dict(series="PIP:POV_3_00", unit="percent of population (2021 PPP)", fmt=",.1f",
                                   suffix="%", bins=("width", 1),  # 3% on a bin edge
                                   vlines=[POVERTY_LINE], note=POVERTY_TARGET_NOTE),
    "Happiness: life evaluation": dict(series="WHR:LADDER", unit="Cantril ladder, 0–10 (3-year average)",
                                       fmt=",.2f", bins=("width", 0.25)),
}

INFRASTRUCTURE_DISTRIBUTIONS: dict[str, dict] = {
    "Access to basic drinking water": dict(series="WB:SH.H2O.BASW.ZS", unit=PCT_OF_POPULATION, fmt=",.1f",
                                           suffix="%", bins=("width", 5)),
    "Access to basic sanitation": dict(series="WB:SH.STA.BASS.ZS", unit=PCT_OF_POPULATION, fmt=",.1f", suffix="%",
                                       bins=("width", 5)),
    "Access to basic hygiene": dict(series="WB:SH.STA.HYGN.ZS", unit="percent of population with a handwashing "
                                                                   "facility with soap and water at home",
                                    fmt=",.1f", suffix="%", bins=("width", 5)),
    "Access to electricity": dict(series="WB:EG.ELC.ACCS.ZS", unit=PCT_OF_POPULATION, fmt=",.1f", suffix="%",
                                  bins=("width", 5)),
    "Access to clean cooking": dict(series="WB:EG.CFT.ACCS.ZS", unit="percent of population relying on clean "
                                                                   "fuels and technologies for cooking",
                                    fmt=",.1f", suffix="%", bins=("width", 5)),
    "Internet users": dict(series="WB:IT.NET.USER.ZS", unit=PCT_OF_POPULATION, fmt=",.1f", suffix="%",
                           bins=("width", 5)),
}

EDUCATION_DISTRIBUTIONS: dict[str, dict] = {
    "Government expenditure on education": dict(series="WB:SE.XPD.TOTL.GD.ZS", unit=PCT_OF_GDP, fmt=",.1f",
                                                suffix="%", bins=("width", 0.5, "clip_tails"),
                                                band=EDUCATION_BAND),
    "Mean years of schooling": dict(series="UNDP:MYS", unit="years, adults aged 25 and older", fmt=",.1f",
                                    bins=("width", 0.5)),
    "Expected years of schooling": dict(series="UNDP:EYS", unit="years, for a child entering school now",
                                        fmt=",.1f", bins=("width", 0.5, "clip_tails")),
    "Tertiary school enrollment": dict(series="WB:SE.TER.ENRR", unit="gross enrollment ratio (%)", fmt=",.1f",
                                       suffix="%", bins=("width", 5)),
}

HEALTHCARE_DISTRIBUTIONS: dict[str, dict] = {
    "Current health expenditure": dict(series="WB:SH.XPD.CHEX.GD.ZS", unit=PCT_OF_GDP, fmt=",.1f", suffix="%",
                                       bins=("width", 1, "clip_tails")),
    "Out-of-pocket health spending": dict(series="WB:SH.XPD.OOPC.CH.ZS", unit="percent of current health "
                                                                             "expenditure",
                                          fmt=",.1f", suffix="%", bins=("width", 5)),
}

CLIMATE_DISTRIBUTIONS: dict[str, dict] = {
    "Greenhouse gas emissions per capita": dict(series="WB:EN.GHG.ALL.PC.CE.AR5",
                                                unit="tonnes of CO₂-equivalent per person, excl. land use",
                                                fmt=",.2f", bins=("width", 1, "clip_tails")),
    "Total greenhouse gas emissions": dict(series="WB:EN.GHG.ALL.MT.CE.AR5",
                                           unit="million tonnes of CO₂-equivalent, excl. land use", fmt=",.1f",
                                           map_scale="log", bins_note=TENFOLD_NOTE,
                                           bins=_log_edges([0, 1, 10, 100, 1000, 10000, np.inf])),
    "Energy intensity": dict(series="WB:EG.EGY.PRIM.PP.KD",
                             unit="megajoules per constant 2021 PPP $ of GDP (lower = more efficient)",
                             fmt=",.2f", bins=("width", 0.5, "clip_tails"), lower_is_better=True),
    "Renewable energy share": dict(series="WB:EG.FEC.RNEW.ZS", unit="percent of final energy consumption",
                                   fmt=",.1f", suffix="%", bins=("width", 10)),
    "Forest area": dict(series="WB:AG.LND.FRST.ZS", unit="percent of land area", fmt=",.1f", suffix="%",
                        bins=("width", 5)),
    "ND-GAIN country index": dict(series="NDGAIN:GAIN",
                                  unit="score (0–100, higher = better prepared to climate change)",
                                  fmt=",.1f", bins=("width", 2)),
    "ND-GAIN vulnerability": dict(series="NDGAIN:VULNERABILITY", unit="score (0–1, higher = more vulnerable)",
                                  fmt=",.3f", bins=("width", 0.02)),
    "ND-GAIN readiness": dict(series="NDGAIN:READINESS", unit="score (0–1, higher = more ready)",
                              fmt=",.3f", bins=("width", 0.02)),
}


# Series charted in Trends but deliberately not in Distributions: the sector shares
# left to the single-country charts. 
TRENDS_ONLY_SERIES = {"WB:SL.IND.EMPL.ZS", "WB:NV.SRV.TOTL.ZS", "WB:SL.SRV.EMPL.ZS", du.NET_MIGRATION}

# Same sections, in the same order, as the Trends tab.
DISTRIBUTION_SECTIONS: dict[str, dict[str, dict]] = {
    "Economics": ECONOMIC_DISTRIBUTIONS,
    "Labour market": LABOUR_DISTRIBUTIONS,
    "Industry & innovation": INDUSTRY_DISTRIBUTIONS,
    "Living standards": LIVING_STANDARDS_DISTRIBUTIONS,
    "Demographics": DEMOGRAPHIC_DISTRIBUTIONS,
    "Climate": CLIMATE_DISTRIBUTIONS,
    "Infrastructure & basic services": INFRASTRUCTURE_DISTRIBUTIONS,
    "Education": EDUCATION_DISTRIBUTIONS,
    "Healthcare": HEALTHCARE_DISTRIBUTIONS,
}
DISTRIBUTION_INDICATORS: dict[str, dict] = {
    label: spec for specs in DISTRIBUTION_SECTIONS.values() for label, spec in specs.items()
}


def widening_bins(bins: tuple) -> bool:
    """True for fixed, widening ("edges") bins, i.e. values spanning orders of magnitude. The one
    rule for both Distributions charts: such bins on the histogram, a log y-axis on the box plot."""
    return bins[0] == "edges"


def distribution_counts(values: pd.DataFrame, bins: tuple) -> pd.DataFrame:
    """
    Country counts per bin, one column per year of `values` (country x year). Index = bin
    position (x), plus a 'label' column for the tooltip / categorical axis. Equal-width bins
    run from the lowest to the highest occupied bin with no gaps, so empty bins show as 0.
    """
    if widening_bins(bins):
        _, edges, labels = bins
        counts = {y: pd.cut(values[y].dropna(), edges, labels=labels, right=False).value_counts()
                  for y in values.columns}
        out = pd.DataFrame(counts).reindex(labels).fillna(0).astype(int)
        occupied = out.index[out.sum(axis=1) > 0]
        out = out.loc[occupied[0]:occupied[-1]] if len(occupied) else out.iloc[0:0]
        return out.assign(label=out.index).reset_index(drop=True)
    width = bins[1]
    # Small epsilon: 2.1 / 0.1 is 20.999... in floating point and would land in the wrong bin.
    idx = {y: np.floor(values[y].dropna() / width + 1e-9).astype(int) for y in values.columns}
    all_idx = pd.concat(idx.values())
    if all_idx.empty:
        return pd.DataFrame(columns=[*values.columns, "label"])
    lo_idx, hi_idx = all_idx.min(), all_idx.max()
    if len(bins) > 2 and bins[2] == "clip_tails":
        # A handful of outliers (war/refugee years: -20%, +15% growth) would otherwise stretch
        # the axis until every other country sits in a narrow band. Values beyond the 1st/99th
        # percentile go into open-ended edge bins instead.
        lo_idx, hi_idx = int(all_idx.quantile(0.01)), int(all_idx.quantile(0.99))
        idx = {y: s.clip(lo_idx, hi_idx) for y, s in idx.items()}
    full = range(lo_idx, hi_idx + 1)
    out = pd.DataFrame({y: s.value_counts() for y, s in idx.items()}).reindex(full).fillna(0).astype(int)
    lefts = np.round(out.index.to_numpy() * width, 6)
    labels = [f"{lo:g} to {lo + width:g}" for lo in lefts]
    if all_idx.min() < lo_idx:
        labels[0] = f"< {lefts[0] + width:g}"
    if all_idx.max() > hi_idx:
        labels[-1] = f"{lefts[-1]:g}+"
    out["label"] = labels
    out.index = np.round(lefts + width / 2, 6)  # bar centers
    return out


DIST_BAR_OPACITY = 0.6  # the two years' bars overlap, so both stay see-through
# The Distributions charts' titles are drawn above each figure by html_title() (so a chart's
# toggles can sit between its title and the plot); the figures only reserve their legend row.
DIST_CHART_HEIGHT = 400
DIST_MARGIN_TOP = 40  # the 14px legend row


def dist_bars_title(label: str, year_a: int, year_b: int) -> tuple[str, str]:
    """(title, subtitle) over the histogram, for html_title()."""
    return f"Distribution of countries by {label}, {year_a} vs. {year_b}", "Number of countries"


def dist_boxes_title(label: str, first: int, last: int, unit: str, log: bool) -> tuple[str, str]:
    """(title, subtitle) over the box plot per year, for html_title()."""
    return f"Distribution of countries by {label}, {first}–{last}", unit + (", log scale" if log else "")


def zero_line_x(dist: pd.DataFrame, bins: tuple) -> float | None:
    """
    Where a zero line goes on distribution_bars' x-axis, or None if 0 isn't inside the
    axis range (including when 0 is where the range starts, e.g. population's "< 100k" bin).
    Equal-width bins: x = 0 if it falls strictly within the bars' span. Fixed edges (a
    categorical axis): the boundary between the bin ending at 0 and the one starting at 0.
    """
    if widening_bins(bins):
        _, edges, labels = bins
        if 0 not in edges[:-1]:
            return None
        rows = list(dist["label"])
        starts_at_zero = labels[edges.index(0)]
        if starts_at_zero not in rows or rows.index(starts_at_zero) == 0:
            return None
        return rows.index(starts_at_zero) - 0.5  # categories sit at 0, 1, 2, ...
    half = bins[1] / 2
    lo, hi = dist.index.min() - half, dist.index.max() + half
    return 0.0 if lo < -1e-9 and hi > 1e-9 else None


def bin_intervals(dist: pd.DataFrame, bins: tuple, suffix: str = "") -> list[str]:
    """
    Each bin of `dist` (see distribution_counts) as an interval, e.g. "[2.1, 2.2)". Bins are
    closed on the left and open on the right, like distribution_counts' floor() / pd.cut(right=False).
    Open-ended edge bins run from/to infinity: "(-∞, -1.5%)", "[5%, +∞)".
    """
    def fmt(v, number):
        if v == -np.inf:
            return "-∞"
        if v == np.inf:
            return "+∞"
        return f"{number(v)}{suffix}"

    def interval(lo, hi, number):
        return f"{'(' if lo == -np.inf else '['}{fmt(lo, number)}, {fmt(hi, number)})"

    if widening_bins(bins):
        _, edges, labels = bins
        at = {label: i for i, label in enumerate(labels)}
        return [interval(edges[at[lb]], edges[at[lb] + 1], _short_count) for lb in dist["label"]]
    width = bins[1]
    out = []
    for center, lb in zip(dist.index, dist["label"]):
        lo, hi = float(np.round(center - width / 2, 6)), float(np.round(center + width / 2, 6))
        # distribution_counts folds clipped tails into "< x" / "x+" edge bins.
        out.append(interval(-np.inf if lb.startswith("< ") else lo, np.inf if lb.endswith("+") else hi,
                            lambda v: f"{v:g}"))
    return out


def _edge_ticks(left: float, right: float, width: float, max_ticks: int = 12) -> list[float]:
    """Round tick values on bin edges between left and right: a step of width x 1, 2, 5, 10, ..."""
    for mult in (1, 2, 5, 10, 20, 50, 100, 200, 500, 1000):
        step = width * mult
        if (right - left) / step + 1 <= max_ticks:
            break
    first = np.ceil(left / step - 1e-9) * step
    return [float(np.round(v, 6)) for v in np.arange(first, right + step * 1e-6, step)]


def distribution_bars(dist: pd.DataFrame, bins: tuple, label: str, year_a: int, year_b: int, *, x_title: str,
                      x_suffix: str = "", vlines: list | None = None, band: tuple | None = None) -> go.Figure:
    """
    Two overlaid bar sets; the tooltip is headed by the bin as an interval (e.g. "[2.1, 2.2)",
    see bin_intervals), then one row per year. No title of its own (dist_bars_title, drawn above
    the figure by html_title); the two years' legend is a row above the plot. A solid zero line
    where zero_line_x() finds one. The unit
    is the x-axis title, so tick labels carry no suffix (x_suffix is for the tooltip only).
    Equal-width bins are a histogram of a continuous value, so they almost touch; fixed-edge
    bins are categories, with bars about twice as wide as the gaps.

    The x-axis is always categorical, with each bin's interval as its category: that's what
    heads a unified tooltip with text (the header is otherwise the x value, i.e. a bar's center).
    The tick labels are set separately. Equal-width numeric bins read as a number line: ticks at
    round bin edges, and vlines placed by pos(), which maps a value to the category scale (bin k
    spans k - 0.5 .. k + 0.5). Fixed-edge bins keep their short labels ("< 100k", "1M to 3M").
    vlines [(value, label)]: dotted black reference lines, labelled at the top; band (low, high, label):
    a reference range shaded in du.REF_BAND_COLOR behind the bars (translucent over the gridlines), no
    edge lines. Both sit on bin edges.
    """
    numeric = not widening_bins(bins)
    if numeric:
        width = bins[1]
        left = float(dist.index[0]) - width / 2  # dist.index holds bin centers

        def pos(v):
            return (v - left) / width - 0.5

    else:
        def pos(v):
            return v  # vlines on fixed-edge bins are already category positions (see zero_line_x)

    x = bin_intervals(dist, bins, x_suffix)
    fig = go.Figure()
    for year, color in [(year_a, du.DIST_COLORS[0]), (year_b, du.DIST_COLORS[1])]:
        fig.add_trace(go.Bar(
            x=x, y=dist[year], name=str(year), marker_color=color, opacity=DIST_BAR_OPACITY,
            hovertemplate=f"{year}: <b>%{{y}}</b> countries<extra></extra>",
        ))
    fig.update_layout(barmode="overlay", bargap=0.05 if numeric else 1 / 3)
    ref_font = dict(family=FONT, size=11, color=REF_LINE_COLOR)
    if band is not None:
        low, high, band_label = band
        fig.add_vrect(x0=pos(low), x1=pos(high), layer="below", line_width=0, fillcolor=du.REF_BAND_COLOR,
                      opacity=du.REF_BAND_OPACITY,
                      annotation_text=band_label, annotation_position="top left", annotation_font=ref_font)
    for xv, line_label in (vlines or []):
        fig.add_vline(x=pos(xv), line_width=1, line_dash="dot", line_color=HIST_REF_LINE_COLOR,
                      annotation_text=line_label, annotation_position="top right", annotation_font=ref_font)
    zero_x = zero_line_x(dist, bins)
    if zero_x is not None:
        fig.add_vline(x=pos(zero_x), line_width=1, line_color=du.ZERO_LINE_COLOR)

    fig = style_fig(fig, title="", y_title="", x_title=x_title, height=DIST_CHART_HEIGHT)
    fig.update_xaxes(type="category")
    if numeric:
        ticks = _edge_ticks(left, left + width * len(dist), width)
        fig.update_xaxes(tickmode="array", tickvals=[pos(v) for v in ticks], ticktext=[f"{v:g}" for v in ticks])
    else:
        # A tick on a bar would head its tooltip with the tick text ("1M to 3M"); unifiedhovertitle
        # (plotly >= 6.3) heads it with the category, i.e. the interval, instead.
        fig.update_xaxes(tickmode="array", tickvals=x, ticktext=dist["label"].tolist(),
                         unifiedhovertitle_text="%{x}")
    fig.update_layout(margin_t=DIST_MARGIN_TOP)
    return fig


# --- Box plot per year (the last block on the Distributions tab) ---
# Quartiles (boxes and tooltip alike): pandas' default linear interpolation, i.e. numpy's "linear"
# method (Hyndman & Fan type 7). Whiskers reach the furthest value within 1.5 IQR of the box.
BOX_WIDTH = 0.7  # of a year
BOX_WHISKER_WIDTH = 0.4  # caps, as a share of the box width
BOX_OUTLIER_PX = 3
# Alphas: (outline / median / mean, fill, outlier dots), observed vs. forecast years.
BOX_ALPHAS = {False: (1.0, 0.25, 0.7), True: (0.5, 0.12, 0.35)}
BOX_FIT_PAD = 0.05  # "fit axis to whiskers": padding as a share of the range (log units on a log axis)


@st.cache_data(ttl=du.CACHE_TTL_SECONDS, show_spinner=False, hash_funcs=du._DF_HASH_FUNCS)
def yearly_box_stats(wide: pd.DataFrame, countries: pd.DataFrame, log: bool
                     ) -> tuple[pd.DataFrame, pd.DataFrame, int]:
    """
    Per-year box statistics of `wide` (country x year, country_indicator_wide), for every year
    with a value. Returns (stats, outliers, hidden):
      stats     indexed by year: n, min / max with min_country / max_country (names), q1, median,
                q3, mean (arithmetic), lo_whisker / hi_whisker
      outliers  year, value, country: values beyond the whiskers
      hidden    on a log axis (log=True), the number of countries left out of some year for a
                value <= 0, which a log axis can't show (they're out of that year's statistics too)
    """
    long = (wide.rename_axis(index="country_code", columns="year").stack().rename("value")
            .reset_index().dropna(subset=["value"]))
    hidden = 0
    if log:
        non_positive = long["value"] <= 0
        hidden = int(long.loc[non_positive, "country_code"].nunique())
        long = long[~non_positive]
    long = long.reset_index(drop=True)
    long["year"] = long["year"].astype(int)
    names = countries.drop_duplicates("country_code").set_index("country_code")["country_name"]
    long["country"] = long["country_code"].map(names).fillna(long["country_code"])
    g = long.groupby("year")["value"]
    stats = pd.DataFrame({"n": g.size(), "min": g.min(), "max": g.max(), "mean": g.mean(),
                          "q1": g.quantile(0.25), "median": g.quantile(0.5), "q3": g.quantile(0.75)})
    stats["min_country"] = long.loc[g.idxmin(), "country"].to_numpy() if len(long) else []
    stats["max_country"] = long.loc[g.idxmax(), "country"].to_numpy() if len(long) else []
    iqr = stats["q3"] - stats["q1"]
    fences = pd.DataFrame({"lo": stats["q1"] - 1.5 * iqr, "hi": stats["q3"] + 1.5 * iqr})
    bounds = fences.reindex(long["year"]).to_numpy()
    inside = (long["value"] >= bounds[:, 0]) & (long["value"] <= bounds[:, 1])
    within = long[inside].groupby("year")["value"]
    stats["lo_whisker"] = within.min().reindex(stats.index).fillna(stats["q1"])
    stats["hi_whisker"] = within.max().reindex(stats.index).fillna(stats["q3"])
    outliers = long.loc[~inside, ["year", "value", "country"]].reset_index(drop=True)
    return stats, outliers, hidden


def _segments(years, values, half: float) -> tuple[list, list]:
    """Horizontal segments year +- half at each value, None-separated for one line trace."""
    x, y = [], []
    for year, v in zip(years, values):
        x += [year - half, year + half, None]
        y += [v, v, None]
    return x, y


def _log_ticks(lo: float, hi: float) -> list[float]:
    """Powers of ten from just below lo to just above hi."""
    return [10.0 ** k for k in range(math.floor(math.log10(lo)), math.ceil(math.log10(hi)) + 1)]


def distribution_boxes(stats: pd.DataFrame, outliers: pd.DataFrame, label: str, unit: str, *, split: float,
                       log: bool, fmt: str, suffix: str = "", fit: bool = False, show_mean: bool = True
                       ) -> go.Figure:
    """
    One box per year from yearly_box_stats: #2057a7 boxes (Plotly's precomputed q1 / median / q3 /
    fences, so the browser gets one row per year, not every country's value), outlier dots, and the
    median (#2057a7) and mean (#c43d4d) as 2px segments of their own (a box's own median takes its
    outline's colour and width; Plotly's boxmean is dashed). Forecast years (> split) are lighter.
    A fixed number of traces whatever the number of years: per group (observed / forecast) one box
    trace, one outlier trace, one median and one mean trace (None-separated segments), then one
    invisible hover trace over all years (one tooltip per year, also at the split) and the legend
    keys. fit: y-range from the lowest to the highest whisker end (+ padding), so extreme dots fall
    off. log: a log y-axis, ticks at powers of ten. No title of its own (dist_boxes_title, drawn
    above the figure and its toggles by html_title).
    """
    years = stats.index.to_numpy()
    forecast = years > split
    fig = go.Figure()
    half = BOX_WIDTH / 2
    for is_fc in (False, True):
        sub = stats[forecast if is_fc else ~forecast]
        if sub.empty:
            continue
        line_a, fill_a, dot_a = BOX_ALPHAS[is_fc]
        line_color = _hex_rgba(du.DENIM, line_a)
        group = "forecast" if is_fc else "observed"
        fig.add_trace(go.Box(
            x=sub.index, q1=sub["q1"], median=sub["median"], q3=sub["q3"], lowerfence=sub["lo_whisker"],
            upperfence=sub["hi_whisker"], width=BOX_WIDTH, whiskerwidth=BOX_WHISKER_WIDTH, boxpoints=False,
            line=dict(color=line_color, width=1), fillcolor=_hex_rgba(du.DENIM, fill_a),
            legendgroup=group, showlegend=False, hoverinfo="skip"))
        dots = outliers[outliers["year"].isin(sub.index)]
        fig.add_trace(go.Scatter(
            x=dots["year"], y=dots["value"], mode="markers", legendgroup=group, showlegend=False, hoverinfo="skip",
            marker=dict(size=BOX_OUTLIER_PX, color=_hex_rgba(du.DENIM, dot_a), line_width=0)))
        x, y = _segments(sub.index, sub["median"], half)
        fig.add_trace(go.Scatter(x=x, y=y, mode="lines", line=dict(color=line_color, width=2),
                                 legendgroup="median", showlegend=False, hoverinfo="skip"))
        if show_mean:
            x, y = _segments(sub.index, sub["mean"], half)
            fig.add_trace(go.Scatter(x=x, y=y, mode="lines", line=dict(color=_hex_rgba(du.OLD_ROSE, line_a), width=2),
                                     legendgroup="mean", showlegend=False, hoverinfo="skip"))

    def value(i):
        return f"<b>%{{customdata[{i}]:{fmt}}}{suffix}</b>"

    rows = [f"Max: {value(0)} (%{{customdata[1]}})", f"Upper quartile: {value(2)}", f"Median: {value(3)}",
            f"Lower quartile: {value(4)}", f"Min: {value(5)} (%{{customdata[6]}})"]
    if show_mean:
        rows.append(f"Mean: {value(7)}")
    rows.append("Countries: <b>%{customdata[8]}</b>")
    custom = stats[["max", "max_country", "q3", "median", "q1", "min", "min_country", "mean", "n"]]
    fig.add_trace(go.Scatter(
        x=years, y=stats["median"], mode="markers", marker=dict(color="rgba(0,0,0,0)", size=1),
        customdata=custom.to_numpy(dtype=object), hovertemplate="<br>".join(rows) + "<extra></extra>",
        showlegend=False, name=""))

    # Legend keys (no data of their own): each toggles its group's traces.
    def key(name, group, **kw):
        fig.add_trace(go.Scatter(x=[None], y=[None], name=name, legendgroup=group, hoverinfo="skip", **kw))

    for is_fc, name in ((False, "Observed"), (True, "Forecast")):
        if (forecast if is_fc else ~forecast).any():
            line_a, fill_a, _ = BOX_ALPHAS[is_fc]
            key(name, name.lower(), mode="markers", marker=dict(
                symbol="square", size=12, color=_hex_rgba(du.DENIM, fill_a),
                line=dict(color=_hex_rgba(du.DENIM, line_a), width=1)))
    key("Median", "median", mode="lines", line=dict(color=du.DENIM, width=2))
    if show_mean:
        key("Mean", "mean", mode="lines", line=dict(color=du.OLD_ROSE, width=2))

    first, last = int(years[0]), int(years[-1])
    fig = style_fig(fig, title="", y_title="", height=DIST_CHART_HEIGHT)
    fig.update_layout(boxmode="overlay")
    fig.update_xaxes(range=[first - 1, last + 1], tickmode="linear", tick0=0,
                     dtick=10 if len(years) > 40 else 5, hoverformat="d")
    lo, hi = ((stats["lo_whisker"].min(), stats["hi_whisker"].max()) if fit
              else (stats["min"].min(), stats["max"].max()))
    if log:
        fig.update_yaxes(type="log")
        ticks = _log_ticks(lo, hi)
        fig.update_yaxes(tickmode="array", tickvals=ticks, ticktext=[_short_count(t) for t in ticks])
        if fit:
            lo10, hi10 = math.log10(lo), math.log10(hi)
            pad = BOX_FIT_PAD * (hi10 - lo10) or BOX_FIT_PAD
            fig.update_yaxes(range=[lo10 - pad, hi10 + pad])
    elif fit:
        pad = BOX_FIT_PAD * (hi - lo) or BOX_FIT_PAD * max(abs(hi), 1)
        fig.update_yaxes(range=[lo - pad, hi + pad])
    fig.update_layout(margin_t=DIST_MARGIN_TOP)
    return fig


def _even_scale(colors: list[str]) -> list[list]:
    return [[i / (len(colors) - 1), c] for i, c in enumerate(colors)]


# Choropleths use the blue sequential ramp (#bfddff to #032461); values on both sides of 0 the
# diverging palette (gold negative, blue positive).
BLUE_SCALE, DIVERGING_SCALE = _even_scale(du.SEQUENTIAL_RAMP), _even_scale(du.DIVERGING)
MAP_HEIGHT, MAP_MARGIN_TOP = 430, 10  # the title is above the figure (html_title)


def indicator_choropleth(values: pd.Series, names: pd.Series, spec: dict, *,
                         z_range: tuple[float, float]) -> go.Figure:
    """
    World map of one year's values (index = ISO3 country_code); z_range is (min, max) of the
    values the color scale spans. Diverging scales (zero_mid, signed_log) are symmetric around 0,
    so zero is always their center: Plotly ignores zmid once zmin/zmax are set. The unit is the
    subtitle (html_title, above the map), so the color bar's labels carry no suffix.
    """
    v = values.dropna()
    scale = spec.get("map_scale")
    lo, hi = z_range
    colorbar = dict(thickness=12, len=0.7, tickfont=AXIS_TEXT, outlinewidth=0)
    if scale == "log":
        # The scale starts at the smallest positive value: a reported 0 (e.g. CO2 of a tiny
        # territory) would otherwise stretch it down to 1e-9. Zeros get the lowest color.
        positive = v[v > 0]
        lo = max(lo, float(positive.min()) if len(positive) else 1e-9)
        z = np.log10(v.clip(lower=lo))
        zmin, zmax = np.log10(lo), np.log10(max(hi, lo))
        ticks = np.arange(np.floor(zmin), np.ceil(zmax) + 1)
        colorbar.update(tickvals=ticks, ticktext=[_short_count(10 ** t) for t in ticks])
        colorscale, zmid = BLUE_SCALE, None
    elif scale == "signed_log":
        z, (zmin, zmax, zmid), ticks = _signed_log_z(v, max(abs(lo), abs(hi)))
        colorbar.update(ticks)
        colorscale = DIVERGING_SCALE
    else:
        z, zmin, zmax = v, lo, hi
        # Rates that can be negative (growth, natural change) use a diverging scale centered on 0,
        # in every year, even one without negative values, so the palette doesn't flip between years.
        if spec.get("zero_mid"):
            m = max(abs(lo), abs(hi), 1e-9)
            zmin, zmax, colorscale, zmid = -m, m, DIVERGING_SCALE, 0.0
        else:
            colorscale, zmid = BLUE_SCALE, None
    fig = go.Figure(go.Choropleth(
        locations=v.index, locationmode="ISO-3", z=z, zmin=zmin, zmax=zmax, zmid=zmid,
        colorscale=colorscale, colorbar=colorbar, marker_line_color="white", marker_line_width=0.4,
        reversescale=bool(spec.get("lower_is_better")),  # e.g. energy intensity: darkest = most efficient
        text=names.reindex(v.index), customdata=v.values,
        hovertemplate=f"%{{text}}: <b>%{{customdata:{spec['fmt']}}}{spec.get('suffix', '')}</b><extra></extra>",
    ))
    return _style_map(fig)


def _signed_log_z(v: pd.Series, max_abs: float):
    """sign * log10(1 + |v|): a color scale for values spanning orders of magnitude on both sides
    of 0. Returns (z, (zmin, zmax, zmid), colorbar tick settings), symmetric around 0 up to max_abs."""
    m = max(float(_slog(max_abs)), 1e-9)
    # Every other power of 10, plus +-10 on small ranges (on wide ones they'd crowd around 0).
    ticks = [t for t in range(-int(np.floor(m)), int(np.floor(m)) + 1) if t % 2 == 0 or (abs(t) == 1 and m < 3)]
    ticktext = [("−" if t < 0 else "") + _short_count(10 ** abs(t)) if t else "0" for t in ticks]
    return _slog(v), (-m, m, 0.0), dict(tickvals=ticks, ticktext=ticktext)


def _style_map(fig: go.Figure) -> go.Figure:
    """No title of its own (html_title draws it above the map mode toggle). Countries without data
    stay light gray."""
    fig.update_geos(projection_type="natural earth", showcountries=True, countrycolor="white",
                    showland=True, landcolor=du.WHISPER, showocean=False,  # #ebebeb
                    showframe=False, coastlinecolor="white", lataxis_range=[-58, 85])  # crop Antarctica
    fig.update_layout(
        paper_bgcolor="white", height=MAP_HEIGHT, margin=dict(l=10, r=10, t=MAP_MARGIN_TOP, b=10),
        font=dict(family=FONT, color="black"), hoverlabel=dict(font=AXIS_TEXT),
    )
    return fig


def change_choropleth(change: pd.Series, names: pd.Series, spec: dict, *, unit: str) -> go.Figure:
    """
    World map of end year minus start year (index = ISO3 country_code), on the diverging palette
    centered on 0 (gold for a decrease, blue for an increase, like the table's arrows). Indicators
    whose level map is log-scaled (total population, net migration rate) get a signed-log scale;
    the rest a linear one, symmetric around 0. The tooltip matches the table's Change column
    (_change_text), e.g. "▲ 2.1 pp".
    """
    v = change.dropna()
    max_abs = float(v.abs().max()) if len(v) else 0.0
    colorbar = dict(thickness=12, len=0.7, tickfont=AXIS_TEXT, outlinewidth=0)
    if spec.get("map_scale") in ("log", "signed_log"):
        z, (zmin, zmax, zmid), ticks = _signed_log_z(v, max_abs)
        colorbar.update(ticks)
    else:
        z, (zmin, zmax, zmid) = v, (-max(max_abs, 1e-9), max(max_abs, 1e-9), 0.0)
    fig = go.Figure(go.Choropleth(
        locations=v.index, locationmode="ISO-3", z=z, zmin=zmin, zmax=zmax, zmid=zmid,
        colorscale=DIVERGING_SCALE, colorbar=colorbar, marker_line_color="white", marker_line_width=0.4,
        text=names.reindex(v.index), customdata=[_change_text(x, spec["fmt"], unit) for x in v],
        hovertemplate="%{text}: <b>%{customdata}</b><extra></extra>",
    ))
    return _style_map(fig)


def _change_arrow(change: float, fmt: str) -> str:
    """▲ / ▼ by sign, ▬ if the change rounds to zero at the indicator's precision (fmt);
    blank if it's missing (a year without data)."""
    if pd.isna(change):
        return ""
    if float(f"{abs(change):{fmt}}".replace(",", "")) == 0:
        return "▬"
    return "▲" if change > 0 else "▼"


def _change_text(change: float, fmt: str, unit: str) -> str:
    """The Change column's display: arrow + size of the change in the indicator's format, e.g.
    '▲ 0.35', '▼ 1,234,567', '▲ 2.1 pp' (the arrow gives the direction, so no sign); '▬ 0.00'
    when it rounds to zero; '–' if missing. Display only: the column still sorts by the signed value."""
    arrow = _change_arrow(change, fmt)
    return f"{arrow} {abs(change):{fmt}}{unit}" if arrow else "–"


def _change_color(change: float, fmt: str) -> str:
    color = {"▲": du.CHANGE_UP_COLOR, "▼": du.CHANGE_DOWN_COLOR,
             "▬": du.NO_CHANGE_COLOR}.get(_change_arrow(change, fmt))
    return f"color: {color}; font-weight: bold" if color else ""


def nearest_year(year: int, years: list[int]) -> int:
    """The year in `years` closest to `year` (the earlier one on a tie)."""
    return min(years, key=lambda y: (abs(y - year), y))


# The pair of years the user last picked on the Distributions year slider (Session State). Set only
# when they actually move a handle; from then on every indicator opens on it (remembered_years).
DIST_USER_YEARS = "dist_user_years"
# Alongside it: whether each of the two years was a projection on the indicator it was picked on.
DIST_USER_PROJECTED = "dist_user_projected"


def _handle_fallback(year: int, was_projected: bool, years: list[int], split: float) -> str | None:
    """Why a remembered handle can't be used on an indicator with data in `years` and projections
    after `split`: "range" (outside the data), "projection" (picked as an observed year, but this
    indicator projects it), or None (it is used, snapped to the nearest year with data)."""
    if not years[0] <= year <= years[-1]:
        return "range"
    if not was_projected and nearest_year(year, years) > split:
        return "projection"
    return None


def remembered_years(remembered: tuple[int, int], years: list[int], default: tuple[int, int],
                     split: float = math.inf, projected: tuple[bool, bool] = (False, False)) -> tuple[int, int]:
    """The slider position for an indicator with data in `years`, given the user's remembered pair.
    Each handle is kept if its year is within the indicator's first..last year (snapped to the
    nearest year with data, e.g. inside the 5-yearly forecasts) and falls back to its own default
    otherwise, so (1960, 2020) on data from 1990 gives (1990, 2020). A year picked as an observed
    one (`projected` False) also falls back when it is a projection here (after `split`), so an
    observed 2025 never shows another indicator's 2025 nowcast; a year picked as a projection is kept."""
    picked = [d if _handle_fallback(y, p, years, split) else nearest_year(y, years)
              for y, d, p in zip(remembered, default, projected)]
    return tuple(sorted(picked))

# An indicator's default years are the first and last observed years with values for at least this
# many countries: a year covered by a handful of countries makes a nearly empty distribution and map.
MIN_DEFAULT_COUNTRIES = 30


@st.cache_data(ttl=du.CACHE_TTL_SECONDS, show_spinner=False, hash_funcs=du._DF_HASH_FUNCS)
def countries_per_year(wide: pd.DataFrame) -> pd.Series:
    """Number of countries with a value in each year of a country_indicator_wide table."""
    return wide.notna().sum().astype(int)


def default_years(counts: pd.Series, split: float,
                  min_countries: int = MIN_DEFAULT_COUNTRIES) -> tuple[int, int]:
    """An indicator's default slider years, from its countries-per-year `counts` (years with data
    only) and its projection split (du.series_split): the first year with at least `min_countries`
    values -> the last observed (year < split) year with that many. Without such a year, the first
    year with data / the last observed year (any year if none is observed) instead, each on its own;
    a start that would come after the end also takes the first year with data."""
    years = sorted(int(y) for y in counts.index)
    observed = [y for y in years if y < split]
    first, last = years[0], (observed[-1] if observed else years[-1])
    dense = [y for y in years if counts[y] >= min_countries]
    if not dense:
        return first, last
    dense_observed = [y for y in dense if y < split]
    end = dense_observed[-1] if dense_observed else last
    start = dense[0] if dense[0] <= end else first
    return start, end


def years_text(years: list[int]) -> str:
    """'1990 and 2020', or '2020' for a pair on the same year."""
    years = sorted(set(years))
    return " and ".join(str(y) for y in years)


def remembered_years_caption(remembered: tuple[int, int], years: list[int], split: float = math.inf,
                             projected: tuple[bool, bool] = (False, False),
                             default: tuple[int, int] | None = None) -> str | None:
    """The line under the year slider, only when a remembered year isn't used on this indicator
    (remembered_years): outside its data, or an observed year that is a projection here. Says
    which year(s) the slider shows the default for instead. None when both are used."""
    reasons = [_handle_fallback(y, p, years, split) for y, p in zip(remembered, projected)]
    missing = sorted({y for y, r in zip(remembered, reasons) if r == "range"})
    lines = []
    if missing:
        lines.append(f"This indicator has data for {years[0]}–{years[-1]} only, so the default is shown "
                     f"instead of {years_text(missing)}.")
    # (handle, remembered year, default) for each observed year that is a projection here
    proj = [(i, y, (default or (years[0], years[-1]))[i])
            for i, (y, r) in enumerate(zip(remembered, reasons)) if r == "projection"]
    if proj:
        observed = [y for y in years if y <= split]
        last_observed = observed[-1] if observed else None
        verb = "is a projection" if len({y for _, y, _ in proj}) == 1 else "are projections"
        if len(proj) == 2:
            shown = f"the default years, {years_text([d for *_, d in proj])}, are"
        elif proj[0][0] == 1 and proj[0][2] == last_observed:
            shown = f"the last observed year, {proj[0][2]}, is"
        else:
            shown = f"the default {'end' if proj[0][0] == 1 else 'start'} year, {proj[0][2]}, is"
        lines.append(f"{years_text([y for _, y, _ in proj])} {verb} for this indicator, so {shown} shown instead.")
    return " ".join(lines) or None


def html_title(title: str, subtitle: str, gap_below: bool = True):
    """The title + subtitle over each of the Distributions tab's four blocks (histogram, map,
    Country Details table, box plot), drawn the same way for all four and outside the figures, so
    a chart's toggles sit between its title and the plot: bold 20px headline case, then an italic
    gray 16px sentence-case subtitle. Not indented (TREND_TEXT_INDENT is for the Country Profiles
    tab only). gap_below: DIST_SUBTITLE_GAP of space under the subtitle, before a toggle or table
    (the histogram's legend, inside its figure, needs none)."""
    st.markdown(
        f'<div style="line-height:1.3;padding-bottom:{DIST_SUBTITLE_GAP if gap_below else 0}px">'
        f'<div style="font-size:20px;font-weight:700;color:black">{html.escape(headline_case(title))}</div>'
        f'<div style="font-size:16px;font-style:italic;color:{SUBTITLE_COLOR}">'
        f"{html.escape(sentence_case(subtitle))}</div></div>",
        unsafe_allow_html=True,
    )


DIST_BLOCK_GAP = 8  # px of extra space above each Distributions block's title
DIST_SUBTITLE_GAP = 8  # px under the map's, Country Details' and box plot's subtitles


# The tab's initial view (section, indicator): the first of these whose series has country data,
# in this order, one per source: IMF, the population data, ILOSTAT,
# SWIID, ND-GAIN, UNDP, Harvard Atlas, World Happiness Report. With none, the first one.
DEFAULT_DIST_VIEWS: list[tuple[str, str]] = [
    ("Economics", "Real GDP growth"),
    ("Demographics", "Birth rate"),
    ("Labour market", "Youth NEET rate"),
    ("Living standards", "Income inequality (Gini index)"),
    ("Climate", "ND-GAIN country index"),
    ("Education", "Mean years of schooling"),
    ("Industry & innovation", "Economic Complexity Index"),
    ("Living standards", "Happiness: life evaluation"),
]
# A section's starting indicator when the user switches to it, where it isn't the first one.
SECTION_START_INDICATOR = {"Demographics": "Birth rate"}
DIST_INITIAL_VIEW = "dist_initial_view"  # Session State: the view picked once per session


def first_available_view(has_data, views=DEFAULT_DIST_VIEWS) -> tuple[str, str]:
    """The first (section, label) of views for which has_data(section, label) is true; views[0]
    if none is."""
    return next((view for view in views if has_data(*view)), views[0])


def initial_dist_view(data: pd.DataFrame, countries: pd.DataFrame, errors: dict[str, str]) -> tuple[str, str]:
    """The Distributions tab's initial view: the first DEFAULT_DIST_VIEWS entry whose source
    loaded and whose series has at least one year of country data."""
    def has_data(section, label):
        try:
            series = DISTRIBUTION_SECTIONS[section][label]["series"]
            if ds.source_of(series) in errors:
                return False
            return len(du.country_indicator_wide(data, countries, series).columns) > 0
        except Exception:  # never let the choice of a default view break the tab
            return False
    return first_available_view(has_data)


@st.fragment  # a widget in this tab reruns only this tab, not the other one
def tab_distributions(data: pd.DataFrame, countries: pd.DataFrame, errors: dict[str, str]):
    # Button rows (segmented controls) rather than radio buttons; required=True keeps exactly one
    # option selected, as a radio does. Buttons show the section names.
    sections = list(DISTRIBUTION_SECTIONS)
    # The initial view is picked once per session, so later runs (or a refresh) never move the
    # defaults under a choice the user has made.
    if DIST_INITIAL_VIEW not in st.session_state:
        st.session_state[DIST_INITIAL_VIEW] = initial_dist_view(data, countries, errors)
    initial_section, initial_label = st.session_state[DIST_INITIAL_VIEW]
    section = st.segmented_control("Indicator Group", sections, default=initial_section, required=True,
                                   key="dist_section")
    # One selectbox per section (its own key), so each section remembers its own choice. Each
    # starts on its first indicator, except the initial view's section (on its indicator) and
    # where SECTION_START_INDICATOR names another.
    labels = list(DISTRIBUTION_SECTIONS[section])
    default_label = initial_label if section == initial_section else SECTION_START_INDICATOR.get(section)
    label = st.selectbox("Indicator", labels, key=f"dist_indicator_{section}",
                         index=labels.index(default_label) if default_label in labels else 0)
    spec = DISTRIBUTION_INDICATORS[label]
    source_key = ds.source_of(spec["series"])
    source = du.SOURCE_LABELS[source_key]
    wide = du.country_indicator_wide(data, countries, spec["series"])
    years = [int(y) for y in wide.columns]
    if not years:
        failed = source_key in errors
        st.info(f"No country data loaded for “{label}”"
                + (f" (couldn't reach {source})" if failed else "") + ". Click **Refresh data** in the sidebar.")
        return
    # Defaults: the first year with values for MIN_DEFAULT_COUNTRIES countries -> the last observed
    # (not projected) year with as many (default_years has the fallbacks). The slider and fields
    # still span every year with data (country_indicator_wide drops empty ones).
    split = du.series_split(spec["series"], data)
    default_a, default_b = default_years(countries_per_year(wide), split)
    # A numeric slider, so its scale is real years (st.select_slider spaces options evenly: the
    # 5-yearly forecasts 2030, 2035, ... would sit one step apart). Years without data (e.g.
    # 2026-2029 for birth rates) snap to the nearest year with data when a handle is released.
    key = f"dist_year_range_{label}"  # per indicator: year lists differ
    start_key, end_key = f"dist_year_start_{label}", f"dist_year_end_{label}"

    # The slider and the two year fields show one pair of years. on_change only fires when the
    # user changes a widget: that pair is the choice every indicator then opens on
    # (DIST_USER_YEARS), saved with whether each year is a projection here (DIST_USER_PROJECTED).
    # A fallback below never overwrites it, so an indicator with a longer history gets the full
    # choice back.
    def remember(picked):
        snapped = tuple(sorted(nearest_year(int(y), years) for y in picked))
        st.session_state[DIST_USER_YEARS] = snapped
        st.session_state[DIST_USER_PROJECTED] = tuple(y > split for y in snapped)

    def reset_years():
        """Back to every indicator's own default: forget the choice and each slider's position."""
        for k in [k for k in st.session_state
                  if k in (DIST_USER_YEARS, DIST_USER_PROJECTED) or str(k).startswith("dist_year_range_")]:
            del st.session_state[k]

    # Positions go in via Session State, not value=: the callbacks also write there, and
    # Streamlit warns when a widget gets both. Until the user picks years, each indicator
    # opens on its own default.
    remembered = st.session_state.get(DIST_USER_YEARS)
    projected = st.session_state.get(DIST_USER_PROJECTED, (False, False))
    if remembered:
        st.session_state[key] = remembered_years(remembered, years, (default_a, default_b), split, projected)
    else:
        st.session_state.setdefault(key, (default_a, default_b))
    st.session_state[start_key], st.session_state[end_key] = st.session_state[key]  # the fields follow the slider
    start_col, end_col, reset_col, _ = st.columns([1, 1, 1, 3], vertical_alignment="bottom")
    year_field = dict(min_value=years[0], max_value=years[-1], step=1, format="%d",
                      on_change=lambda: remember((st.session_state[start_key], st.session_state[end_key])))
    start_col.number_input("Start year", key=start_key, **year_field)
    end_col.number_input("End year", key=end_key, **year_field)
    reset_col.button("Reset to default", key=f"dist_years_reset_{label}", on_click=reset_years,
                     disabled=not remembered, help="Return every indicator to its own default years.")
    ya, yb = st.slider("Select two years to compare country distributions", min_value=years[0],
                       max_value=years[-1], step=1, key=key, label_visibility="collapsed",
                       on_change=lambda: remember(st.session_state[key]))
    caption = (remembered_years_caption(remembered, years, split, projected, (default_a, default_b))
               if remembered else None)
    if caption:
        st.caption(caption)
    ya, yb = nearest_year(ya, years), nearest_year(yb, years)  # in case of a state set before snapping
    suffix, fmt, unit = spec.get("suffix", ""), spec["fmt"], spec["unit"]
    compared = wide[sorted({ya, yb})]

    # 1. Distribution
    dist = distribution_counts(compared, spec["bins"])
    if not dist.empty:
        st.space(DIST_BLOCK_GAP)
        html_title(*dist_bars_title(label, ya, yb), gap_below=False)
        st.plotly_chart(distribution_bars(dist, spec["bins"], label, ya, yb, x_title=sentence_case(unit),
                                          x_suffix=suffix, vlines=spec.get("vlines"), band=spec.get("band")),
                        width="stretch")
        notes = [ds.ESTIMATE_NOTES.get(spec["series"]), spec.get("bins_note"), spec.get("note"),
                 f"Values from {int(split + 0.5)} on are projections." if max(ya, yb) > split else None]
        source_footer(note=" ".join(n for n in notes if n) or None, source=source)

    # 2. Map: either year (each on its own color scale) or the change. Its title depends on the
    # map mode, so a placeholder keeps it above the toggle and it's filled in once the mode is known.
    st.space(DIST_BLOCK_GAP)
    map_title = st.empty()
    names = countries.set_index("country_code")["country_name"]
    change_unit = " pp" if suffix == "%" else ""  # a difference of two percentages: percentage points
    modes = [*sorted({ya, yb}), "change"]
    map_mode = st.segmented_control("Select map mode", modes, required=True, key=f"dist_map_mode_{label}_{ya}_{yb}",
                                    default=modes[-2],  # the end year
                                    format_func=lambda m: f"Change, {ya}–{yb}" if m == "change" else str(m))
    if map_mode == "change":
        with map_title:
            html_title(f"{label}, change {ya}–{yb}", "percentage points" if suffix == "%" else unit)
        st.plotly_chart(change_choropleth(wide[yb] - wide[ya], names, spec, unit=change_unit), width="stretch")
    else:
        with map_title:
            html_title(f"{label}, {map_mode}", unit)
        year_vals = wide[map_mode].dropna()
        st.plotly_chart(indicator_choropleth(
            wide[map_mode], names, spec, z_range=(float(year_vals.min()), float(year_vals.max()))),
            width="stretch")
    source_footer(source=source)

    # 3. Table: both years plus the change between them, headed like the charts
    st.space(DIST_BLOCK_GAP)
    html_title("Country Details", f"{label} ({unit}), {years_text([ya, yb])}, and the change between them")
    meta = countries.set_index("country_code")[["iso2_code", "country_name", "region", "income_group"]]
    table = meta.loc[meta.index.intersection(wide.index)].assign(
        value_a=wide[ya], value_b=wide[yb],
    ).dropna(subset=["value_a", "value_b"], how="all")
    # Numeric (so the column sorts by size); shown as arrow + signed value by the Styler below.
    table["change"] = table["value_b"] - table["value_a"]
    table = table.sort_values("value_b", ascending=False, na_position="last")
    table = table.assign(
        income_group=table["income_group"].str.replace(" income", "", regex=False),
        flag=table["iso2_code"].map(flag_image),
    )
    table = with_short_regions(table)
    table["region"] = table["region"].map(lambda r: [r] if isinstance(r, str) else [])
    col_a, col_b = f"{ya}", f"{yb}" if yb != ya else f"{yb} "
    styler = (
        table[["flag", "country_name", "region", "income_group", "value_a", "value_b", "change"]]
        .rename(columns={"country_name": "Country", "region": "Region", "income_group": "Income group",
                         "value_a": col_a, "value_b": col_b, "change": "Change"})
        .style.format({col_a: f"{{:{fmt}}}{suffix}", col_b: f"{{:{fmt}}}{suffix}",
                       "Change": lambda v: _change_text(v, fmt, change_unit)}, na_rep="–")
    )
    styler = styler.map(lambda v: _change_color(v, fmt), subset=["Change"])
    st.dataframe(
        styler,
        width="stretch", hide_index=True,
        column_config={
            "flag": st.column_config.ImageColumn("Flag", width=50),
            "Region": region_pill_column(),
            "Change": st.column_config.NumberColumn("Change", width=130),
        },
    )

    # 4. Box plot per year: every year with data, observed and projected (the year slider doesn't apply)
    log = widening_bins(spec["bins"])
    stats, outliers, hidden = yearly_box_stats(wide, countries, log)
    if stats.empty:
        return  # no box plot, so no header over nothing
    st.space(DIST_BLOCK_GAP)
    html_title(*dist_boxes_title(label, int(stats.index.min()), int(stats.index.max()), unit, log))
    # Two-button toggles, under the title and above the legend. Per-indicator keys: a widget not rendered in a run
    # loses its state, so switching the indicator (or the group) and back puts both on their
    # defaults again.
    fit_col, mean_col, _ = st.columns([2, 1, 3])
    fit = fit_col.segmented_control("Fit axis to whiskers (hides extreme values)", ["Yes", "No"], default="No",
                                    required=True, key=f"dist_box_fit_{label}") == "Yes"
    show_mean = mean_col.segmented_control("Mean", ["Show", "Hide"], default="Show", required=True,
                                           key=f"dist_box_mean_{label}") == "Show"
    st.plotly_chart(distribution_boxes(stats, outliers, label, unit, split=split, log=log, fmt=fmt, suffix=suffix,
                                       fit=fit, show_mean=show_mean), width="stretch")
    notes = [ds.ESTIMATE_NOTES.get(spec["series"]),
             f"Values from {int(split + 0.5)} on are projections." if stats.index.max() > split else None,
             (f"{hidden} {'country' if hidden == 1 else 'countries'} with a value of 0 in some years "
              f"{'is' if hidden == 1 else 'are'} not shown for those years (log scale).") if hidden else None]
    source_footer(note=" ".join(n for n in notes if n) or None, source=source)


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def load_source_updates() -> dict[str, dt.date | None]:
    """Each source's release date (du.source_updates), or none at all if that fails: a missing date
    only leaves "Last updated" out of the footers."""
    try:
        return du.source_updates()
    except Exception:  # noqa: BLE001
        return {}


def main():
    # Section headers (st.subheader, the app's only <h3>) in the caption gray, #909090.
    # Streamlit's own text colors (":gray[...]") aren't palette colors, hence the CSS.
    st.markdown(f"<style>h3 {{ color: {du.SUVA_GREY} !important; }}</style>", unsafe_allow_html=True)
    st.title(APP_NAME)
    st.caption(
        "This app gathers a curated set of publicly available indicators, from fiscal figures to self-reported "
        "happiness, so you can quickly explore how the world has changed over recent decades. Pick an indicator "
        "and a period to see how countries redistributed across the range, how values vary across the map, "
        "and who climbed or fell in the global ranking. You can also open any country's profile to trace its "
        "full history across all available indicators."
    )

    countries, country_errors = load_countries()

    with st.sidebar:
        st.header("About")
        # Every source is credited in the "Data sources and licences" dialog and under each chart.
        st.caption(
            "The app treats each country as a data point and each year as a time step. Watching how countries "
            "spread out along an indicator, and how that spread changes over time, brings significant shifts into "
            "view at a glance. It's a tool for quick diagnostics, at the global or the country level. What lies "
            "behind each shift is yours to explore further."
        )
        st.caption(
            "**Period & Country Comparisons** is the main tab. See how things stood decades ago and how they stand "
            "now, and how countries and regions have shifted in the world. You can see where they improved or fell "
            "behind on key measures of the economy and society, both in absolute terms and relative to other "
            "countries."
        )
        st.caption(
            "**Country Profiles** puts a country's current state and all its available history on one page. The "
            "indicators cover enough ground to give a well-rounded picture of its economic and social state."
        )
        if st.button("Data sources and licences"):
            show_data_sources()
        if st.button("\U0001F504 Refresh data"):
            # Expire, don't delete: each source goes back to the network, but keeps its saved copy as the
            # fallback if it can't be fetched.
            du.expire_disk_cache()
            st.cache_data.clear()
            st.rerun()

    data, data_errors = load_data()
    errors = {**data_errors, **country_errors}
    stop_if_nothing_loaded(errors, data)
    countries_warning(errors, countries)
    stale_sources_notice()

    # Distributions first, so the app opens on it. Each tab is an st.fragment:
    # a full run (page load, "Refresh data") still builds both, since st.tabs isn't lazy.
    dist_tab, trends_tab = st.tabs(["Period & Country Comparisons", "Country Profiles"])
    with dist_tab:
        tab_distributions(data, countries, errors)
    with trends_tab:
        tab_trends(data, countries, errors)


if __name__ == "__main__":
    main()
