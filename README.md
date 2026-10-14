# Global Shifts Tracker

**Live app: [global-shifts-tracker.streamlit.app](https://global-shifts-tracker.streamlit.app/)**

This Streamlit app gathers a curated set of publicly available indicators, from fiscal figures to self-reported
happiness, so you can quickly explore how the world has changed over recent decades. Each country is treated as a data point, and each year as a time step. Watching how countries spread
out along an indicator, and how that spread changes over time, brings significant shifts into view at a
glance.

## Features

**Period & Country Comparisons** is the main tab. Pick an indicator and a period to compare where countries stood then and where they stand now. For example, you can see how the birth rate has fallen so dramatically that levels once considered the norm are now found almost nowhere in the world:

![Distribution of countries by birth rate, 1960 vs. 2024](images/birth_rate_distribution.png)

Or trace, year by year, how the Internet went from a luxury to an everyday necessity across the globe:

![Distribution of countries by share of Internet users, 1990–2025](images/internet_users_distribution.png)

Or compare the economic complexity of countries (a measure of how diverse and sophisticated their exports are) 30 years ago and today, and see which countries moved up and which fell behind:

![Economic Complexity Index map, 2024, with country details table](images/map_and_table.png)

**Country Profiles** puts a country's current state and all its available history on one page. The
indicators cover enough ground to give a well-rounded picture of its economy, society and environment. Here, for example, are some of Germany's demographic and climate trends:

![Country profile for Germany: demographic and climate charts](images/trends_and_climate.png)

The app needs no local data files—it fetches data directly from the publishers' APIs and refreshes it
daily, so the numbers stay current.

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

## Run locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Licence

The code is licensed under the [PolyForm Noncommercial License 1.0.0](LICENSE). The licence covers the
code only, not the data shown in the app.
