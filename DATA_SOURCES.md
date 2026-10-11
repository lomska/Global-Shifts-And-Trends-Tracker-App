# Data sources

The app's code is under the PolyForm Noncommercial License 1.0.0 (see [LICENSE](LICENSE)). The data it
shows is not: it belongs to the publishers below and is used under their terms. Each publisher's terms
were checked against its own pages on 11 October 2026. This is a summary, not legal advice.

**Changes made by the app.** The app downloads each source at run time and charts the published values.
It reshapes them (one long table, country names and codes unified through `country_dict.py`) and draws
yearly statistics across countries (histograms, quartiles, box plots, maps). It derives one series:
natural population growth (birth rate minus death rate), from the World Bank population data. Projected
years are drawn dotted, as each publisher marks them. No published value is edited.

## Summary

| Source | Publisher | Licence / terms | Link |
|---|---|---|---|
| Population estimates and projections | World Bank | CC BY 4.0 | [datacatalog.worldbank.org/public-licenses](https://datacatalog.worldbank.org/public-licenses) |
| World Development Indicators | World Bank | CC BY 4.0 (EDGAR series: see below) | [datacatalog.worldbank.org/public-licenses](https://datacatalog.worldbank.org/public-licenses) |
| Poverty and Inequality Platform (PIP) | World Bank | CC BY 4.0 | [pip.worldbank.org](https://pip.worldbank.org) |
| EDGAR greenhouse gases (in WDI) | European Commission JRC, with the IEA | CC BY 4.0; the IEA-derived fossil CO₂ part CC BY-NC-ND 4.0 | [edgar.jrc.ec.europa.eu/dataset_ghg2025](https://edgar.jrc.ec.europa.eu/dataset_ghg2025) |
| World Economic Outlook | International Monetary Fund | IMF copyright and terms: free reuse with credit; commercial reuse needs permission | [imf.org/en/about/copyright-and-terms](https://www.imf.org/en/about/copyright-and-terms) |
| ILOSTAT | International Labour Organization | CC BY 4.0 (data published from 3 May 2023) | [ilo.org rights and permissions](https://www.ilo.org/node/9321) |
| Human Development Report 2025 | UNDP | CC BY 3.0 IGO | [hdr.undp.org/terms-use](https://hdr.undp.org/terms-use) |
| ND-GAIN Country Index | University of Notre Dame | No licence named; "free and open-access" | [gain.nd.edu](https://gain.nd.edu/our-work/country-index/download-data/) |
| World Happiness Report 2026 | Wellbeing Research Centre, University of Oxford | No licence named; Figure 2.1 data free to download | [worldhappiness.report/data-sharing](https://worldhappiness.report/data-sharing/) |
| Growth Projections and Complexity Rankings (ECI) | Growth Lab, Harvard University | CC0 1.0 on Harvard Dataverse; the Atlas asks for a citation | [doi:10.7910/DVN/XTAQMC](https://doi.org/10.7910/DVN/XTAQMC) |
| Standardized World Income Inequality Database | Frederick Solt | No licence named; asks for the citation | [fsolt.org/swiid](https://fsolt.org/swiid/) |

## Sources

### World Bank: Population estimates and projections

- **Takes:** source 40 of the World Bank API: population, growth, fertility, life expectancy (total,
  female, male), age shares, dependency ratios, birth and death rates, net migration, under-5 mortality,
  1960–2050 (projections from the latest estimate year on); the country list with regions and income
  groups (`/country`).
- **Licence:** [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/), the default for datasets the
  World Bank produces. Give appropriate credit and indicate any changes.
- **Credit:** World Bank, Population estimates and projections.
- **Link:** <https://databank.worldbank.org/source/population-estimates-and-projections>

### World Bank: World Development Indicators (WDI)

- **Takes:** 34 series through the WDI API (`api.worldbank.org/v2`): national accounts (GDP and GNI per
  capita PPP, sector value added, manufacturing, medium and high-tech share, manufactures exports,
  credit, FDI, price level), labour (unemployment, participation, employment by sector: ILO modelled
  estimates), education and R&D spending, tertiary enrolment, internet use, health spending, access to
  water, sanitation, hygiene, electricity and clean cooking, energy imports and intensity, renewable
  energy share, forest area, and greenhouse gas emissions (EDGAR, below).
- **Licence:** CC BY 4.0, as above. Some WDI series are compiled from other agencies (ILO, WHO/UNICEF JMP,
  UNIDO, UN Comtrade, FAO, IEA and others for Tracking SDG7); the app names them under the charts.
- **Credit:** World Bank, World Development Indicators.
- **Link:** <https://datacatalog.worldbank.org/search/dataset/0037712>

### World Bank: Poverty and Inequality Platform (PIP)

- **Takes:** the poverty headcount at $3.00 a day and the daily median income or consumption (2021 PPP),
  national rows only, latest 2021-PPP data version.
- **Licence:** CC BY 4.0.
- **Credit** (PIP's own citation, from its `citation` API endpoint; version as of 11 October 2026):
  World Bank (2026), Poverty and Inequality Platform (version 20260922_2021_01_02_PROD) [data set].
  pip.worldbank.org. Accessed on 2026-10-11.
- **Link:** <https://pip.worldbank.org>

### EDGAR greenhouse gas emissions (via the World Bank)

- **Takes:** total greenhouse gas emissions excluding LULUCF, per capita and in total
  (`EN.GHG.ALL.PC.CE.AR5`, `EN.GHG.ALL.MT.CE.AR5`), as published in WDI.
- **Licence:** [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) for material owned by the
  European Union; the IEA-EDGAR CO₂ (v4) data, based on IEA data, is
  [CC BY-NC-ND 4.0](https://creativecommons.org/licenses/by-nc-nd/4.0/). Users of that part outside
  CC BY-NC-ND 4.0 must contact the IEA (compliance@iea.org).
- **Credit** (the dataset page's "How to cite the use of underlying data"):
  - EDGAR (Emissions Database for Global Atmospheric Research) Community GHG Database, a collaboration
    between the European Commission, Joint Research Centre (JRC), the International Energy Agency (IEA),
    and comprising IEA-EDGAR CO2, EDGAR CH4, EDGAR N2O, EDGAR F-GASES version EDGAR_2025_GHG (2025)
    European Commission, JRC (Datasets).
  - IEA-EDGAR CO2, a component of the EDGAR (Emissions Database for Global Atmospheric Research)
    Community GHG database version EDGAR_2025_GHG (2025) including or based on data from IEA (2024)
    Greenhouse Gas Emissions from Energy, www.iea.org/data-and-statistics, as modified by the Joint
    Research Centre.
  - Report: Crippa, M., Guizzardi, D., Pagani, F., Banja, M., Muntean, M. et al., GHG emissions of all
    world countries - 2025 Report, Publications Office of the European Union, Luxembourg, 2025,
    doi:10.2760/9816914, JRC143227.

  The app shows the short form "Data: EDGAR (European Commission JRC) and IEA" under these charts.
- **Link:** <https://edgar.jrc.ec.europa.eu/dataset_ghg2025>

### International Monetary Fund: World Economic Outlook (WEO)

- **Takes:** real GDP growth, consumer price inflation, government revenue, expenditure, net
  lending/borrowing and gross debt, current account balance, from the latest WEO edition through the IMF
  SDMX API, with the IMF's projections (drawn dotted).
- **Terms:** [IMF copyright and terms](https://www.imf.org/en/about/copyright-and-terms). Users may
  download, copy, create derivative works, publish and distribute the data with the credit below.
  Commercial reuse needs permission (copyright@imf.org). Data must not be altered in a way that affects its
  nature or accuracy, and any material transformation must be stated with the citation. The app makes
  none.
- **Credit:** Source: International Monetary Fund, World Economic Outlook Database,
  <https://data.imf.org/datasets/WEO>
- **Link:** <https://data.imf.org/datasets/WEO> (since October 2025 the WEO database is published on the
  IMF Data portal)

### International Labour Organization: ILOSTAT

- **Takes:** labour income share of GDP and youth NEET rate (ILO modelled estimates, with ILO projections).
- **Licence:** [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) for databases and datasets with
  their metadata, as of 3 May 2023 (data from before that date is not automatically covered).
- **Credit:** Source: ILOSTAT, International Labour Organization.
- **Link:** <https://ilostat.ilo.org>

### UNDP: Human Development Report 2025

- **Takes:** mean years of schooling and expected years of schooling, from the composite indices time
  series of the 2025 report.
- **Licence:** [CC BY 3.0 IGO](https://creativecommons.org/licenses/by/3.0/igo/). Give appropriate credit,
  link to the licence and indicate where changes were made.
- **Credit:** UNDP (United Nations Development Programme), Human Development Report 2025, licensed under
  CC BY 3.0 IGO. UNDP recalculates its whole time series every year, so values from different reports
  can't be compared directly; the app uses only the 2025 report's series.
- **Link:** <https://hdr.undp.org/data-center/documentation-and-downloads>

### University of Notre Dame: ND-GAIN Country Index

- **Takes:** the ND-GAIN index, vulnerability and readiness scores (2026 edition, released July 2026).
- **Terms:** no licence named on the download page; the index is offered as "a free and open-access tool".
  The page's footer reads "Copyright © 2026 University of Notre Dame".
- **Credit:** Notre Dame Global Adaptation Initiative Country Index (ND-GAIN). (2026). University of Notre
  Dame.
- **Link:** <https://gain.nd.edu/our-work/country-index/download-data/>

### World Happiness Report 2026

- **Takes:** the life evaluation (Cantril ladder, three-year average) from the Figure 2.1 data file.
- **Terms:** no licence named; the Figure 2.1 data is free to download. It comes from the Gallup World
  Poll.
- **Credit:** Helliwell, J. F., Layard, R., Sachs, J. D., De Neve, J.-E., Aknin, L. B., & Wang, S. (Eds.).
  (2026). World Happiness Report 2026. University of Oxford: Wellbeing Research Centre. Data from the
  Gallup World Poll.
- **Link:** <https://worldhappiness.report/data-sharing/>

### Harvard Growth Lab: Economic Complexity Index

- **Takes:** the Economic Complexity Index (SITC classification) from the "Growth Projections and Complexity
  Rankings" dataset on Harvard Dataverse.
- **Terms:** the dataset is published under [CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/)
  on Harvard Dataverse. The Atlas of Economic Complexity also says: "We encourage reuse and adaptation,
  provided that users cite the Atlas and underlying data sources appropriately."
- **Credit:** The Growth Lab at Harvard University, 2019, "Growth Projections and Complexity Rankings",
  https://doi.org/10.7910/DVN/XTAQMC, Harvard Dataverse, V12 (version released 8 February 2026).
- **Link:** <https://doi.org/10.7910/DVN/XTAQMC>, <https://atlas.hks.harvard.edu>

### Standardized World Income Inequality Database (SWIID)

- **Takes:** the Gini index of disposable income (`data/swiid_summary.csv` in the SWIID's GitHub
  repository).
- **Terms:** no licence named; users are asked to cite the SWIID.
- **Credit:** Solt, Frederick. 2020. "Measuring Income Inequality Across Countries and Over Time: The
  Standardized World Income Inequality Database." Social Science Quarterly 101(3):1183-1199. SWIID Version
  9.92, April 2026.
- **Link:** <https://fsolt.org/swiid/>

## Non-commercial use

The app is a non-commercial project. The IMF data (its terms require permission for commercial reuse), the
IEA-derived part of the EDGAR emissions (CC BY-NC-ND 4.0), and the sources that name no licence (ND-GAIN,
World Happiness Report, SWIID) are used on that basis, with the credits above. If the app is ever used
commercially (advertising, fees, paid client work), these terms must be checked again and permission
sought where needed.

## Not redistributed

The app downloads the IMF, ND-GAIN, World Happiness Report, Harvard Growth Lab, SWIID and EDGAR data at run
time, from the publishers' own servers, and caches it locally (`.wb_data_cache/`, not committed). The
repository holds no copy of that data.

## Country flags

The round flags in the Country Details table and the Country Profiles header are from
[circle-flags](https://github.com/HatScripts/circle-flags) by HatScripts, version 2.8.0, used under the
MIT License. The files are in `flags/`, with the licence in `flags/LICENSE.md`.
