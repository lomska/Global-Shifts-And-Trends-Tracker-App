# Global Shifts Tracker

**Live app: [global-shifts-tracker.streamlit.app](https://global-shifts-tracker.streamlit.app/)**

This app gathers a curated set of publicly available indicators, from fiscal figures to
self-reported happiness, to show how the world and its countries have changed over recent decades.

<table>
<tr>
<td width="50%" align="center"><b>Distribution in two years</b><br><img src="images/histogram.png" alt="Histogram: distribution of countries by birth rate, 1960 vs. 2024"></td>
<td width="50%" align="center"><b>World map</b><br><img src="images/map.png" alt="World map: Economic Complexity Index, 2024"></td>
</tr>
<tr>
<td width="50%" align="center"><b>Country details</b><br><img src="images/table.png" alt="Country Details table: each country's value in both years and the change between them"></td>
<td width="50%" align="center"><b>Distribution by year</b><br><img src="images/boxplot.png" alt="Box plot per year: distribution of countries by internet users, 1990-2025"></td>
</tr>
</table>

The app has two tabs:

- **Period & Country Comparisons** (the landing tab) is the cross-country view of one indicator.
  Pick an indicator group, one of its indicators (67 in all) and two years. The tab draws a histogram
  of countries across value bins for both years, a world map switchable between either year and the
  change between them, a sortable table of every country with both values and the change, and a box
  plot per year over the indicator's whole period.
- **Country Profiles** is the time-series view of one entity: the World, a World Bank region or income
  group, or any of 217 countries. It draws 52 charts in nine sections, three per row, with reference
  lines for widely used targets (such as replacement-level fertility) and each source's latest release
  date under every chart.

The app needs no local data files -- it pulls the data live from the publishers'
APIs each time the cache expires (once a day), so the numbers stay current. The
Country Profiles line charts draw each series solid over observed years and dotted
over forecast years (stacked bar charts draw forecast years at half strength).
No chart shades the forecast period.

## Indicators tracked

<table>
<tr><th>Group</th><th>Indicator</th></tr>
<tr><td rowspan="14"><b>Economics</b></td><td><small>Real GDP growth</small></td></tr>
<tr><td><small>Consumer prices</small></td></tr>
<tr><td><small>Unemployment rate</small></td></tr>
<tr><td><small>Government revenue and expenditure</small></td></tr>
<tr><td><small>Government budget balance</small></td></tr>
<tr><td><small>General government gross debt</small></td></tr>
<tr><td><small>Current account balance</small></td></tr>
<tr><td><small>Foreign direct investment, net inflows</small></td></tr>
<tr><td><small>Domestic credit to private sector</small></td></tr>
<tr><td><small>Price level relative to the US</small></td></tr>
<tr><td><small>Net energy imports</small></td></tr>
<tr><td><small>GDP, PPP</small></td></tr>
<tr><td><small>Output by sector</small></td></tr>
<tr><td><small>Employment by sector</small></td></tr>
<tr><td rowspan="3"><b>Labour market</b></td><td><small>Labour force participation rate</small></td></tr>
<tr><td><small>Youth not in employment, education or training</small></td></tr>
<tr><td><small>Labour income share</small></td></tr>
<tr><td rowspan="5"><b>Industry &amp; innovation</b></td><td><small>Manufacturing contribution to GDP</small></td></tr>
<tr><td><small>Medium and high-tech manufacturing</small></td></tr>
<tr><td><small>Manufactured exports</small></td></tr>
<tr><td><small>Economic Complexity Index</small></td></tr>
<tr><td><small>Research and development expenditure</small></td></tr>
<tr><td rowspan="6"><b>Living standards</b></td><td><small>GDP per capita, PPP</small></td></tr>
<tr><td><small>GNI per capita, PPP</small></td></tr>
<tr><td><small>Median income or consumption</small></td></tr>
<tr><td><small>Income inequality (Gini index)</small></td></tr>
<tr><td><small>Poverty at $3.00 a day</small></td></tr>
<tr><td><small>Happiness: life evaluation</small></td></tr>
<tr><td rowspan="9"><b>Demographics</b></td><td><small>Total population</small></td></tr>
<tr><td><small>Annual population growth rate</small></td></tr>
<tr><td><small>Birth and death rates</small></td></tr>
<tr><td><small>Total fertility rate</small></td></tr>
<tr><td><small>Under-5 mortality rate</small></td></tr>
<tr><td><small>Age group shares</small></td></tr>
<tr><td><small>Age dependency ratio</small></td></tr>
<tr><td><small>Life expectancy at birth</small></td></tr>
<tr><td><small>Natural population growth and net migration</small></td></tr>
<tr><td rowspan="7"><b>Climate</b></td><td><small>Greenhouse gas emissions per capita</small></td></tr>
<tr><td><small>Total greenhouse gas emissions</small></td></tr>
<tr><td><small>Energy intensity</small></td></tr>
<tr><td><small>Renewable energy share</small></td></tr>
<tr><td><small>Forest area</small></td></tr>
<tr><td><small>ND-GAIN country index</small></td></tr>
<tr><td><small>Vulnerability and readiness to climate change</small></td></tr>
<tr><td rowspan="3"><b>Infrastructure &amp; basic services</b></td><td><small>Basic drinking water, sanitation and hygiene</small></td></tr>
<tr><td><small>Access to electricity and clean cooking</small></td></tr>
<tr><td><small>Internet users</small></td></tr>
<tr><td rowspan="3"><b>Education</b></td><td><small>Government expenditure on education</small></td></tr>
<tr><td><small>Mean and expected years of schooling</small></td></tr>
<tr><td><small>Tertiary school enrollment</small></td></tr>
<tr><td rowspan="2"><b>Healthcare</b></td><td><small>Current health expenditure</small></td></tr>
<tr><td><small>Out-of-pocket health spending</small></td></tr>
</table>

Data come from the IMF, the World Bank, the ILO, the Harvard Growth Lab, the UNDP, the World Happiness
Report, ND-GAIN, EDGAR and the Standardized World Income Inequality Database. See
[DATA_SOURCES.md](DATA_SOURCES.md) for the full list of sources, their terms and the credits they ask for.

## Licence

The code is licensed under the [PolyForm Noncommercial License 1.0.0](LICENSE). The licence covers the
code only, not the data shown in the app.
