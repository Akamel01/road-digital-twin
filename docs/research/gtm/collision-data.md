# Collision data for the four target cities

## Answer and scope

- The Insurance Corporation of British Columbia (ICBC) publishes two free, province-wide crash products on the BC Data Catalogue under the Open Data Licence for ICBC Information v1.0: ICBC Reported Crashes and Police-Reported Crash Data (Traffic Accident System, TAS). [1][2][6] These are the only free, province-wide, commercial-use-permitted sources found in this scan. (Inference)
- Scope of this scan: the four city open-data portals, the BC Data Catalogue, the ICBC site, the Transportation Association of Canada (TAC) publisher pages, and the Action2Zero summary. Access date for all fetches: 2026-11-24.
- ICBC public data gives counts, severity, coarse location (intersection vs mid-block flags, street/cross-street text, approximate latitude/longitude), road-user flags, time bands, year and month. [1] No structured civic address or 100-block masking. [1][25]
- City portals mostly publish no collision layer: Surrey publishes a Fatal/Injury Collision point layer at 100-block; Vancouver, Richmond and Coquitlam publish none found. [25][26][27][13] Absence is "not found in <portal/search> on <date>", not proof of absence.
- Richer records need a data-sharing agreement (DSA) with the holder (ICBC or the city/police) or a Freedom of Information (FOI) request under the Freedom of Information and Protection of Privacy Act (FIPPA) ($10 CAD application fee for general requests, 2026-11-24). [20] No DSA is assumed to exist. (Inference)
- Methods a city expects: crash frequency and rate (per million entering vehicles, MEV; per 100 million vehicle-kilometres travelled, VKT), severity weighting (equivalent property-damage-only, EPDO; the KABCO injury scale (K fatal, A incapacitating, B non-incapacitating, C possible, O no injury); killed and seriously injured, KSI), multi-year trends, and network screening including Highway Safety Manual (HSM) empirical Bayes. [7][17][24] Exact coefficients and formulas are paywalled and listed in Gaps.
- Privacy: FIPPA, de-identification, small-population suppression, and withheld personal information limit what can be released. [22] (Inference)
- Reporting unit is the Facility (Intersection, Segment, Access point). A per-facility collision layer is buildable for Intersection and Segment from public data; Access point not reliably buildable publicly. [1][2] (Inference) This is go-to-market (GTM)/feasibility research, not a design decision, data request, or legal advice. No one was contacted.

## What each city publishes today

| City | Published today (collision set, fields, location granularity) | Years | Update cadence | Licence/terms | Data holder / FOI recipient | What needs DSA/FOI | Refs |
|---|---|---|---|---|---|---|---|
| Coquitlam | No collision dataset found in the portal category list (Administrative, Boundaries, Imagery & LiDAR, Environment, Parks, Transportation, Utilities, Planning and Development, Service Requests, Finance & Budgets, Street Lighting). Transportation map service and projects published. | n/a — no collision set | n/a — no collision set | Open Government Licence – BC v2.0 | not fetched — Gap | Record-level crash fields | [13] |
| Surrey | Fatal/Injury Collision point layer on the public map service: fields HUNDRED_BLOCK (100-block), INCIDENT_TIME (24hr), INCIDENT_DATE, INCIDENT_TYPE, CASE_NUMBER (file number), ICOUNT, WEBLINK (prevention info); point geometry. | not stated on the layer page — Gap (2026-11-24) | not stated on the layer page — Gap (2026-11-24) | not stated on the fetched layer page — Gap (2026-11-24); location masked to 100-block | not fetched — Gap | Record-level TAS/ICBC fields; contributing factors | [25] |
| Vancouver | No collision dataset found in the open-data catalogue search (API search for "collision" returned 0 datasets on 2026-11-24). [26] Published proxies: street intersections [23] and intersection traffic movement counts (approximate locations, static dataset). [30] | n/a — no collision set | n/a — no collision set | not stated on fetched page — Gap | not fetched — Gap | All crash records; traffic volumes | [23][26][30] |
| Richmond | No collision layer found on the Richmond GIS site (csgeo.richmond.ca) on 2026-11-24; the city's broader open-data catalogue was not searched — Gap. [27] City runs "Top 20 Collision-Prone Intersections" using ICBC data and an ICBC–City Road Safety Improvement Program cost-share. [14][15] | n/a — no collision set | n/a — no collision set | not stated on fetched page — Gap | not fetched — Gap | All crash records; traffic volumes | [14][15][27] |

## ICBC crash data

### Fields and location granularity

| Product | Storage / access | Last modified (catalogue) | Public field list |
|---|---|---|---|
| ICBC Reported Crashes [1] | txt; indirect via Tableau Public view | 2021-03-08 | Crash Count; Crash Severity; Cross Street Full Name; Cyclist Flag; Date of Loss Year; Day of Week; Derived Crash Configuration; Heavy Vehicle Flag; Intersection Crash; Latitude; Longitude; Mid Block Crash; Month of Year; Motorcycle Flag; Municipality Name; Municipality with Boundary; Parking Lot Flag; Pedestrian Flag; Region; Road Location Description; Street Full Name; Time Category (22 fields) |
| Police-Reported Crash Data (TAS) [2] | Tableau Public view | 2021-06-04 | Not stated on the catalogue page beyond "Accident details for all police-attended crashes"; the TAS metadata CSV describes date/time, location, road condition, primary occurrence; one record per crash [4]. The public TAS product's location granularity is not stated on the fetched catalogue/metadata pages on 2026-11-24; the metadata record describes a location field but not its granularity — Gap. [2][4] |

Intersection or address: the ICBC set carries `Intersection Crash` / `Mid Block Crash` flags plus `Street Full Name` and `Cross Street Full Name`, so intersection vs mid-block is explicit. [1] There is no structured civic-address field. Coordinates are approximate and blank where location information was insufficient. [1] 100-block masking is Surrey's layer, not ICBC's. [25] Small municipalities may be withheld where counts are too small. [2] (Inference)

### Years, cadence and the police-reported set

Catalogue "last modified" dates (2021-03-08 / 2021-06-04) are not data currency. The Tableau view "ICBC Reported Crashes" was last published 2026-05-26. [28] The "Police-Reported Crashes" intro view: source not retrievable on 2026-11-24: https://public.tableau.com/app/profile/icbc/viz/Police-ReportedCrashes-IntroPage/Police-ReportedCrashes (metadata from search snippet only: first published 2021-05-20, last published 2025-11-12). [29] The actual crash-year range in the public view is not stated on the Tableau view on 2026-11-24. [28]

Refresh cadence: the catalogue resource is updated annually; ICBC data is available by late spring/early summer of the following year (e.g., spring 2024 for 2023 data); police data by late summer/early fall (e.g., summer/fall 2021 for 2020 data). [5] TAS data was captured as of 30-Jun-2020. [2] Since 2008, legislative changes to police reporting thresholds reduced police-attended reports, particularly for non-fatal crashes; the March 2019 threshold rose from CAD 1,000 (CAD 600 motorcycles) to CAD 10,000 damage regardless of vehicle type — reporting threshold, not a price. [4] TAS allows up to four contributing factors per crash [2] and excludes forest-service roads, industrial roads, private driveways, off-road snowmobile crashes, homicides and suicides. [2] (Inference)

Richer record-level fields (collision number, date/time, location, configuration, causation, injuries, charges) sit in the Protected-B "Metadata for ICBC Crash" (Jan 2015–Dec 2024) and "Metadata for ICBC Traffic Accident System (TAS)" (Jan 2010–Dec 2024) records, available only through the Data Innovation Program to named users; not downloadable. [3][4] Whether "charges" appears among richer fields is not confirmed. [3][4] (Inference)

### Licence, commercial use and attribution

Open Data Licence for ICBC Information v1.0 (last updated 2020-07-22): [6] "ICBC grants you a worldwide, royalty-free, perpetual, non-exclusive license to use the Information, including for commercial purposes." You may "copy, modify, publish, translate, adapt, distribute or otherwise use the Information in any medium, mode or format for any lawful purpose." Attribution: "Contains information licensed under ICBC's Open Data Licence." Non-endorsement: you must not attribute to ICBC results derived from the Information; analysis and conclusions are the authors'. Exemptions: Personal Information as defined in FIPPA, and records not accessible under FIPPA. BC law; no warranty. (Inference)

## City and police records

### Access routes for a contractor

1. ICBC public open data (free, licence above).
2. A data-sharing agreement (DSA) with ICBC or a municipality for record-level or richer fields — suited to ongoing structured access; no such agreement is assumed to exist. (Inference)
3. FOI request under FIPPA [19][20][21] to the public body holding the records (municipalities, police departments including RCMP, health authorities, crown corporations each run their own FOI office). Written request with enough detail to identify the record; response within 30 business days (may be extended); $10 CAD non-refundable application fee for general requests (published fee, 2026-11-24); no fee for personal requests; processing fees may apply if locating/retrieving/preparing exceeds 3 hours (first 3 hours free, severing not charged); fees waivable on public-interest or hardship grounds; exemptions in Part 2 of the Act; severance allowed. Outcomes and terms vary by body. (Inference)
4. Purchase where offered — the Collision Information System (CIS) is not public [7]; ICBC data support is published on the CIS page (not a contact attempt).

### Typical record fields

TAS record fields (from the metadata description): date/time, location, road condition, primary occurrence; one record per crash. [4] The provincial Collision Information System (CIS) produces Fatal/Injury/property-damage-only (PDO) counts, collision-prone locations and sections, a collision rate table, a per-100 m histogram, and specified-sections analysis on uploaded CSV sections, and holds MV6020 (motor-vehicle collision report form) fields (collision date, time, location, type, total killed, total injured, primary occurrence). [7] The CIS is not publicly available. [7] Whether CIS distinguishes a Summary Report from a Details Report is not confirmed on the fetched pages and is listed in Gaps. (Inference)

## Methods a city expects

### Rates and severity weighting

Frequency: collisions per year at a location. Rate per million entering vehicles (MEV) or per 100 million vehicle-kilometres travelled (VKT); per-100 m histograms. [7] CIS functions include Fatal/Injury/PDO counts, collision-prone locations/sections, collision rate table, histogram, and specified-sections analysis. [7] Surrey reports killed-and-injured collisions per 100,000 population. [10][11] (Inference)

Severity: EPDO (equivalent property-damage-only), where an injury/fatal crash is weighted as multiple PDOs; KABCO is the US convention; BC uses ICBC/TAS injury counts and KSI. [17][24] Richmond's severity index is "a measure of how severe collisions are and whether they resulted in injuries or fatalities." [14] Exact EPDO coefficients and the KABCO-to-BC mapping are not in the fetched pages. (Inference)

### Trends and network screening

Richmond states that "to accurately assess changes in collision statistics at improved intersections, 5 full calendar years of data is needed" plus a one-year delay for ICBC to process and release data, and that a three-year average rate mitigates random annual fluctuations. [14] (Inference)

Network screening methods: crash frequency/rate ranking and empirical Bayes excess (expected vs predicted). [17][24] Empirical Bayes, in plain words: combine the site's own observed crash count with the count predicted for similar sites, weighted by reliability, to separate true risk from random year-to-year noise. (Inference) Formulas and safety performance function (SPF) calibration are not read. (Inference)

### TAC and HSM references

Transportation Association of Canada (TAC) titles (list price, CAD, publisher page, 2026-11-24; full text not read): [16][17][18] Canadian Road Safety Audit Guide (2001, PTM-CRSAG-E, 81 pp, $199.00); Canadian Guide to In-Service Road Safety Reviews (2004, PTM-INSERVICE-E, 232 pp, $239.00); Guidelines for the Network Screening of Collision-Prone Locations (2011, PTM-CLLSN-E, 168 pp, $225.00). Both the TAC screening guide [17] and the US Highway Safety Manual (HSM, AASHTO) [24] are references for network screening; [24] summarises the HSM. HSM is the US reference for empirical Bayes and SPFs; exact edition/year not confirmed. [24] No quotes or forum reports were used for any price; TAC prices are publisher list prices and the FOI amount is a published application fee. BC MUTCDC (Manual of Uniform Traffic Control Devices for Canada) and T-02/04 were not fetched and are omitted.

## Privacy limits

FIPPA applies to public bodies (ministries, agencies, municipalities, school districts, health authorities, crown corporations such as ICBC). [19][21] Personal information is excepted from disclosure; severance is allowed where information can be reasonably severed. [19][21] De-identification: aggregation alone is not necessarily de-identification; small populations must be suppressed or masked; methods include suppression, generalization, aggregation; risk assessment is required. [22] No fixed numeric minimum cell size for crash data was found. [22] (Inference)

Routinely released (aggregate): crash counts by municipality/region, severity, year, road-user type; ICBC public set carries municipality, region, approximate latitude/longitude, intersection/mid-block flag. [1] Contributing factors are not in the ICBC public field list; they appear in richer/protected records. [1][4] (Inference)

Withheld: names, licence plates, medical/injury detail, exact addresses, records of identifiable individuals. ICBC's licence exempts Personal Information as defined in FIPPA and records not accessible under FIPPA. [6] Surrey masks location to the 100-block. [25] Municipalities may be undisclosed where counts are too small. [2] (Inference)

## Buildable per-facility layer

| Facility | Public join keys | Fields usable | Denominators | Public-only computable | Needs client records |
|---|---|---|---|---|---|
| Intersection | ICBC `Intersection Crash` flag + street/cross-street text match, or spatial join of latitude/longitude to node geometry [1] | Counts, severity, year/month, trend | Entering vehicles / annual average daily traffic (AADT) | Counts, severity, trend, frequency ranking | Validated node match, rates, empirical Bayes (EB) (Inference) |
| Segment | ICBC `Mid Block Crash` flag + latitude/longitude snap to centreline [1] | Counts, severity, year/month, trend | AADT × segment length (VKT) | Counts, severity, trend, corridor ranking | Rates, empirical Bayes (EB), length/AADT (Inference) |
| Access point | No direct field; geocoding `Road Location Description`/`Street Full Name` to a driveway is ambiguous [1] | Not reliably buildable publicly | n/a | Not reliably buildable publicly | Inventory of access points + records + better geocoding (Inference) |

Minimum viable layer from public data: counts and severity flags for all four cities; KSI/severity weighting from TAS where police-attended; trend from multi-year ICBC sets. [1][2] Rates and empirical Bayes require traffic volumes and SPFs, needing city data-sharing or FOI. (Inference)

## Gaps and unverified points

- ICBC public crash-year range in the Tableau view: not stated on the Tableau view on 2026-11-24; metadata record covers 2015–2024. [3][28]
- Police-Reported Crashes Tableau view: source not retrievable on 2026-11-24: https://public.tableau.com/app/profile/icbc/viz/Police-ReportedCrashes-IntroPage/Police-ReportedCrashes (metadata from search snippet only: first published 2021-05-20, last published 2025-11-12). [29]
- Surrey years/cadence/neighbourhood scale: not stated on the fetched layer page (2026-11-24). [25]
- Exact EPDO coefficients and KABCO-to-BC mapping: not in fetched primary sources; TAC/AASHTO texts paywalled.
- HSM empirical Bayes formulas and SPF calibration: AASHTO HSM not fetched (paywalled). [24]
- Office of the Information and Privacy Commissioner (OIPC) for BC numeric minimum cell size for crash data: not found. [22]
- Whether CIS distinguishes Summary vs Details reports, and whether "charges" appears among richer fields: not confirmed. [3][4][7]
- The public TAS product's location granularity is not stated on the fetched catalogue/metadata pages on 2026-11-24; the metadata record describes a location field but not its granularity — Gap. [2][4]
- BC MUTCDC not retrieved; T-02/04 omitted (no URL).
- Absence claims (Coquitlam/Vancouver/Richmond/Surrey) are as-of 2026-11-24 searches only.

## Sources

| # | Title | Publisher | URL | Access date | What it supports | New? |
|---|---|---|---|---|---|---|
| 1 | ICBC Reported Crashes (dataset page) | BC Data Catalogue (ICBC) | https://catalogue.data.gov.bc.ca/dataset/icbc-reported-crashes | 2026-11-24 | fields, granularity, licence, cadence | |
| 2 | Police-Reported Crash Data (TAS) (dataset page) | BC Data Catalogue (ICBC) | https://catalogue.data.gov.bc.ca/dataset/police-reported-crash-data-tas- | 2026-11-24 | TAS fields, exclusions, capture date, cadence | |
| 3 | Metadata for ICBC Crash | BC Data Catalogue (Data Innovation Program) | https://catalogue.data.gov.bc.ca/dataset/metadata-for-icbc-crash | 2026-11-24 | richer metadata, Protected-B, 2015–2024 | |
| 4 | Metadata for ICBC Traffic Accident System (TAS) | BC Data Catalogue (Data Innovation Program) | https://catalogue.data.gov.bc.ca/dataset/metadata-for-icbc-traffic-accident-system-tas | 2026-11-24 | TAS metadata, reporting thresholds, 2010–2024 | |
| 5 | Data availability and background information (PDF) | ICBC | https://www.icbc.com/assets/en/3MhMVKX1BftrU7KVDFLMDG/background-data.pdf | 2026-11-24 | cadence, sources, regional definitions | |
| 6 | Open Data Licence (ICBC) | ICBC | https://www.icbc.com/policies/open-data-licence | 2026-11-24 | licence, commercial use, attribution, exemptions | |
| 7 | Collision Information System | Province of BC | https://www2.gov.bc.ca/gov/content/transportation/transportation-infrastructure/engineering-standards-guidelines/collision-information-system | 2026-11-24 | CIS not public; MV6020 fields | |
| 10 | What the Data Tells Us (Vision Zero Surrey) | City of Surrey | https://www.surrey.ca/services-payments/parking-streets-transportation/vision-zero-surrey/what-the-data-tells-us | 2026-11-24 | Surrey KSI, ICBC/TAS usage | |
| 11 | Vision Zero Surrey Safe Mobility Plan 2019–2023 (corporate report) | City of Surrey | https://www.surrey.ca/sites/default/files/corporate-reports/CR_2019-R010.pdf | 2026-11-24 | multi-source compilation, gaps | |
| 13 | Coquitlam Open Data Portal | City of Coquitlam | https://data.coquitlam.ca/ | 2026-11-24 | portal categories, OGL-BC v2.0, no collision set | |
| 14 | Top 20 Collision-Prone Intersections Update 2026 | City of Richmond | https://citycouncil.richmond.ca/__shared/assets/Top_20_Collision-Prone_Intersections_Update_202679943.pdf | 2026-11-24 | Richmond severity index, 5-year data need | |
| 15 | ICBC–City of Richmond Road Safety Improvement Program Update 2026 | City of Richmond | https://citycouncil.richmond.ca/__shared/assets/ICBC-City_of_Richmond_Road_Safety_Improvement_Program_Update_202679416.pdf | 2026-11-24 | city–ICBC cost-share program | |
| 16 | Canadian Guide to In-service Road Safety Reviews (2004) | TAC | https://www.tac-atc.ca/en/publications/ptm-inservice | 2026-11-24 | title, year, price, publisher page | |
| 17 | Guidelines for the Network Screening of Collision-Prone Locations (2011) | TAC | https://www.tac-atc.ca/en/knowledge-centre/technical-resources-search/publications/ptm-cllsn-e/ | 2026-11-24 | title, year, price, methods | |
| 18 | Canadian Road Safety Audit Guide (2001) | TAC | https://www.tac-atc.ca/en/knowledge-centre/technical-resources-search/publications/ptm-crsag-e | 2026-11-24 | title, year, price | |
| 19 | Freedom of Information (FOI) FAQ | Province of BC | https://www2.gov.bc.ca/gov/content/governments/about-the-bc-government/open-government/open-information/freedom-of-information/foi-faq | 2026-11-24 | FOI process, fees, timelines | |
| 20 | Fees for Freedom of Information Requests | Province of BC | https://www2.gov.bc.ca/gov/content/governments/about-the-bc-government/open-government/open-information/freedom-of-information/11936 | 2026-11-24 | $10 CAD application fee, processing fees | |
| 21 | Guidance on FIPPA's FOI Process | OIPC BC | https://www.oipc.bc.ca/documents/guidance-documents/3009 | 2026-11-24 | 30-business-day response, fee practice | |
| 22 | De-Identification Guidance (PDF) | Province of BC | https://www2.gov.bc.ca/assets/gov/british-columbians-our-governments/services-policies-for-government/information-management-technology/information-privacy/privacy-impact-assessments/sharing-personal-information/de-identification_guidance.pdf | 2026-11-24 | de-identification, small-population risk | |
| 23 | Vancouver open data (street intersections) | City of Vancouver | https://opendata.vancouver.ca/explore/dataset/street-intersections/ | 2026-11-24 | no collision dataset; traffic-count proxies | |
| 24 | Action2Zero network screening summary | TIRF | https://action2zero.tirf.ca/modules/road-safety-engineering/network-screening | 2026-11-24 | network screening methods, HSM ref | |
| 25 | Surrey Fatal/Injury Collision layer (public map service) | City of Surrey | https://tstgissrvcs.surrey.ca/arcgis/rest/services/Public/MapServer/44 | 2026-11-24 | 100-block collision layer, fields | yes |
| 26 | Vancouver open-data catalogue API search ("collision") | City of Vancouver | https://opendata.vancouver.ca/api/explore/v2.1/catalog/datasets?where=search(%22collision%22)&limit=10 | 2026-11-24 | 0 collision datasets found | yes |
| 27 | Richmond Criminal Activity Map | City of Richmond | https://csgeo.richmond.ca/ | 2026-11-24 | property crime only; no collision dataset | yes |
| 28 | ICBC Reported Crashes (Tableau Public view) | ICBC | https://public.tableau.com/app/profile/icbc/viz/ICBCReportedCrashes/ICBCReportedCrashes | 2026-11-24 | last published 2026-05-26; caveats not read | yes |
| 29 | Police-Reported Crashes (Tableau Public, intro view) | ICBC | https://public.tableau.com/app/profile/icbc/viz/Police-ReportedCrashes-IntroPage/Police-ReportedCrashes | 2026-11-24 | direct fetch 403; metadata from snippet | yes |
| 30 | Vancouver intersection traffic movement counts | City of Vancouver | https://opendata.vancouver.ca/explore/dataset/intersection-traffic-movement-counts/ | 2026-11-24 | intersection traffic counts, static dataset | yes |

All URLs accessed 2026-11-24. Paywalled TAC/HSM full texts were not read; only publisher catalogue metadata (title, year, pages, price) was quoted.