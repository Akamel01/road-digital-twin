# Municipal pricing and competitors

Question: issue #477, part of map #485. Sources read on 2026-11-24 unless a row gives a later date. No one was contacted.
Prices are in CAD where the source is Canadian; USD and unstated currencies are marked, and every price says what kind of price it is.
Citation rule: external claims carry a full URL and an access date; repo claims (the spec, an ADR or CONTEXT.md) link to the repo file and section.

## Answer

- Lethbridge CAD 136,500 (contract award, third-party mirror, 2024; 29 intersections, updated 2025-05-01, give derived CAD 4,706.90/intersection upper bound) and North Bay CAD 166,610 + HST (contract award, 2023). (§1.1)
- Winnipeg audits: CAD 20,475 + GST and CAD 25,200 + tax (single-source contract awards). (§1.1)
- Lakeshore scan-only CAD 292.89/centreline km (derived) and all-in CAD 448.03/km (derived; 543.76 km); Timmins all-in CAD 298.70/paved lane-km (derived). Not merged. (§1.2)
- CAD 120,000–250,000 lines are budget estimates, not awards. (§1.4)
- No comparable vendor publishes a product list price; iRAP publishes accreditation/training fees (list prices), but no assessment or RAP-licence fee; assessments are quotes. (§2)
- The twin measures 3D geometry and sight distance; not conflict analytics, crash prediction or pavement rating. v1 is non-commercial research demo. (§3)

## How to read the prices

- **In-service road safety review**: study of an existing road or intersection using collision history, site visits and engineering judgement. See the [BC toolkit](https://www2.gov.bc.ca/assets/gov/driving-and-transportation/driving/consequences/vision-zero/resource-kit-community-road-safety-toolkit-module3.pdf), accessed 2026-11-24.
- **Mobile LiDAR**: laser scanning from a moving vehicle for geometry and asset inventories. See Lakeshore and Timmins.
- **Network screening**: ranking sites across a network for safety work. See §1.3.
- **iRAP star rating**: 1–5 star rating of road infrastructure against an international assessment method. See iRAP.
- **Measured twin**: this repo's product: georeferenced reconstruction with extracted features, stated accuracy and sight-distance checks. See [the spec](../../design/twin-v1-spec.md).

Rules:

1. **Contract award** = a public body's recorded award value. **Bid result** = an award plus the losing bid, as at Toronto. **Budget estimate** = money set aside, not a payment. **List price** / **quote** = vendor-published price or a price a buyer was given. **Secondary report** = news, vendor blog, forum report or third-party mirror.
2. A budget is never written as an award, a price paid or a vendor fee.
3. A federal, provincial or US item is context, not a Canadian municipal benchmark; mark it `context`.
4. Derived unit prices show the arithmetic and the word `(derived)`. Name the denominator. Road-km and lane-km are different units and never merged.
5. All sources were read on 2026-11-24 unless a row says otherwise. A URL that could not be re-fetched but was read this run keeps 2026-11-24.

## 1. What Canadian municipalities pay

The public record is richer for studies and scans than per-intersection prices.

Shared table columns: Buyer | What was bought | Price | CAD | Unit price (arithmetic) | Basis/date | Source.

### 1.1 In-service road safety reviews, audits and strategies

| Buyer | What was bought | Price as published | CAD | Unit price (arithmetic) | Basis and date | Source (URL, accessed) |
|---|---|---|---|---|---|---|
| City of Lethbridge, Alberta | In-service safety review + preliminary design, awarded 2024-08-01, Parsons Inc. | CAD 136,500 | CAD 136,500 | Award notice gives no intersection count | contract award (third-party mirror), 2024 | [GovMarket mirror](https://govmarket.ca/contract/in-service-safety-review-and-preliminary-design-of-intersections-for-city-of-lethbridge-757807), accessed 2026-11-24 |
| City of Lethbridge (same award) | City page (updated 2025-05-01) lists 29 intersections; no project name, vendor, value or year; page and award linked by scope and city | n/a | n/a | CAD 136,500 / 29 = CAD 4,706.90/intersection (derived) (upper bound; award includes preliminary design) | derived upper bound | [City page](https://getinvolvedlethbridge.ca/in-service-intersection-safety-reviews), accessed 2026-11-24 |
| City of North Bay | Road safety strategy, 2023-06-06, CIMA Canada; more than 830 lane-km, more than 150 km sidewalk, 55 signalized intersections; RFP includes countermeasures and action plan | CAD 166,610 + HST | CAD 166,610 + HST | CAD 166,610 / 830 = CAD 200.73/lane-km (derived) (830 is a floor; fee also covers 150 km sidewalk, 55 signals, countermeasures and an action plan) | contract award, 2023 | [Council report PDF](https://northbay.ca/media/fbalpk45/road-safety-strategy-council-resolution-award-of-contract.pdf), accessed 2026-11-24; [RFP PDF](https://northbay.ca/media/0zrh15et/road-safety-strategy-request-for-proposals.pdf), accessed 2026-11-24 (scope) |
| City of Winnipeg | Pembina Highway Overpass road safety audit, 2024-08-21 | CAD 20,475 + GST | CAD 20,475 + GST | Single audit; no further split | contract award (single source), 2024 | [City report PDF](https://dmis.winnipeg.ca/DownloadMeetingDocument/790896/03.%20RIS%203471%20-%20Pembina%20Hwy%20Overpass%20at%20Abinojii%20Mikanah.pdf), accessed 2026-11-24 |
| City of Winnipeg | Traffic staging road safety audit, 2025-07-10 | CAD 25,200 + MRST/GST | CAD 25,200 + tax | Single audit; no further split | contract award (single source), 2025 | [City report PDF](https://dmis.winnipeg.ca/DownloadMeetingDocument/790896/03.%20RIS%203471%20-%20Pembina%20Hwy%20Overpass%20at%20Abinojii%20Mikanah.pdf), accessed 2026-11-24 |

Both Winnipeg items are single-source assignments: the low end of an audit, not a competitive study price.

### 1.2 Mobile LiDAR and road asset inventories

| Buyer | What was bought | Price as published | CAD | Unit price (arithmetic) | Basis and date | Source (URL, accessed) |
|---|---|---|---|---|---|---|
| City of Toronto | Automated road condition + ROW asset data, 2017-08-17, Fugro Roadware; Stantec bid 2,153,307; renewals 639,623 / 658,812 net | 1,294,386.45 net yr 1; 1,462,657 incl. taxes | 1,294,386 net yr 1 | Network size not stated | contract award (bid result), 2017 | [Toronto PDF](https://www.toronto.ca/legdocs/mmis/2017/ba/bgrd/backgroundfile-106112.pdf), accessed 2026-11-24 |
| Municipality of Lakeshore | 2024 roads needs study, awarded 2024-04-08; Step 1 StreetScan CAD 159,260.50; Step 2 engineering/reporting CAD 84,359.04; printed total CAD 243,619.55; 543.76 centreline km in 2025 RNS (533 km planning figure) | Step 1 159,260.50; Step 2 84,359.04; total 243,619.55 (incl. HST) | CAD 243,619.55 total | 159,260.50 / 543.76 = CAD 292.89/km (derived) (scan-only); 243,619.55 / 543.76 = CAD 448.03/km (derived) (all-in) | contract award, 2024 | [2025 RNS PDF](https://media-003-ca.cdn.govstack.com/lakeshore-018-ca/media/2iabu2kq/lakeshore-2025-road-needs-study-rns.pdf), accessed 2026-11-24 (543.76 km); [2024 award report](https://pub-lakeshore.escribemeetings.com/filestream.ashx?DocumentId=12580), accessed 2026-11-24 (403 on re-fetch; values read in 2026-11-24 discovery pass; procurement method unverified) |
| City of Timmins | Roads needs study 2024; 406 paved lane-km; bid range CAD 56,015–197,500 + HST | CAD 121,273.80 + HST | CAD 121,273.80 + HST | 121,273.80 / 406 = CAD 298.70/lane-km (derived) (all-in; also 92.3 km surface-treated, 180 km sidewalks) | contract award, 2024 | [Timmins document](https://timmins.civicweb.net/document/159924/), accessed 2026-11-24 |
| City of Leduc | LiDAR + RGBI capture, awarded 2025-07-25, Wooding Geospatial Solutions | CAD 42,000 | CAD 42,000 | No network size | contract award, 2025 | [Leduc tender](https://leduc.bidsandtenders.ca/Module/Tenders/en/Tender/Detail/46ac54e7-e9e7-4824-b9d2-a098d9428ab3), accessed 2026-11-24 |

Lakeshore shows why the scan-only, all-in per-km and per-lane-km rates differ. Printed Step 1+2 sum to 243,619.54, one cent below printed total 243,619.55. 2024 award report returned 403; procurement method unverified.

### 1.3 Network screening and collision studies

| Buyer | What was bought | Price as published | CAD | Unit price (arithmetic) | Basis and date | Source (URL, accessed) |
|---|---|---|---|---|---|---|
| City of North Bay | See §1.1; award is a road safety strategy, not a screening-only price | 166,610 + HST | 166,610 + HST | n/a | contract award, 2023 | [Council report PDF](https://northbay.ca/media/fbalpk45/road-safety-strategy-council-resolution-award-of-contract.pdf), accessed 2026-11-24 |
| City of Halifax | Data Collision Analysis, 2026-05-21, CIMA Canada; 60-month term | CAD 233,215 | CAD 233,215 | 233,215 / 60 = CAD 3,886.92/month (derived) (even spend) | contract award, 2026 | [Halifax tender](https://halifax.bidsandtenders.ca/Module/Tenders/en/Tender/Detail/d3fbc799-23a2-48dc-8cee-e82a84649a64), accessed 2026-11-24 |
| Transport Canada | SMART INTERSECTION DATA COLLECTION, 2022-12-28, MicroTraffic; 2023-01-03 to 2023-03-31 | CAD 167,240 | CAD 167,240 | context (federal); video data collection, not a municipal study | contract award, federal, 2022 | [CanadaBuys notice](https://canadabuys.canada.ca/en/tender-opportunities/award-notice/pw-22-01010216-1022496), accessed 2026-11-24 |
| Manitoba Transportation and Infrastructure | LiDAR services, 2025-08-15, Eagle Mapping | CAD 436,408.50 | CAD 436,408.50 | context (provincial); contracting organisation Manitoba Transportation and Infrastructure | contract award, provincial, 2025 | [CanadaBuys notice](https://canadabuys.canada.ca/en/tender-opportunities/award-notice/mx-443655211269), accessed 2026-11-24 |
| City of Larkspur, California | Corridor mobility and safety study, 2024-08-07, Parametrix | USD 86,890 | USD 86,890 | context (US); keep USD | contract award, US, 2024 | [Larkspur staff report](http://www.larkspur.ca.gov/DocumentCenter/View/19861/46-Magnolia-Corridor-Mobility-and-Safety-Contract-Award-to-Parametrix), accessed 2026-11-24 |

No Canadian municipal screening-only award with a published value was found (see §1.5).

### 1.4 Budgets, not contract values

| Buyer | What was bought | Price as published | CAD | Unit price (arithmetic) | Basis and date | Source (URL, accessed) |
|---|---|---|---|---|---|---|
| Town of Tecumseh | School safety zones review, 2025-08-12; 12 sites; WSP awarded; fee not stated | CAD 180,000 budget | CAD 180,000 (budget) | No per-site price; fee unknown | budget estimate, 2025 | [Tecumseh report](https://tecumseh-pub.escribemeetings.com/filestream.ashx?DocumentId=59632), accessed 2026-11-24 |
| City of Cambridge | Road safety audits, in progress | CAD 120,000 budget | CAD 120,000 (budget) | n/a | budget estimate, in progress, page accessed 2026-11-24 | [Cambridge projects](https://services.cambridge.ca/CapitalProjects/Projects.aspx), accessed 2026-11-24 |
| City of Cambridge | Road safety review and action plan 2025 | CAD 200,000 budget | CAD 200,000 (budget) | n/a | budget estimate | [Cambridge projects](https://services.cambridge.ca/CapitalProjects/Projects.aspx), accessed 2026-11-24 |
| City of Lethbridge | Capital improvement program project 554, 2024 | CAD 250,000 capital budget | CAD 250,000 (capital budget) | The CIP PDF supports only this budget | budget estimate, 2024 | [Lethbridge CIP PDF](https://www.lethbridge.ca/media/5wjnzjuo/2022-2031-capital-improvement-program.pdf), accessed 2026-11-24 |

These are appropriations, so they show what councils set aside, not what a vendor was paid. Do not put them in §1.1 or §1.3. The CIP PDF supports only the CAD 250,000 budget; the separate Parsons Inc. award of CAD 136,500 is a contract award in §1.1, sourced to the GovMarket mirror.

### 1.5 Prices that are not public

- No award for Coquitlam, Surrey, Vancouver or Richmond in the sources listed. Only Coquitlam's construction tender page was checked. [Coquitlam page](https://www.coquitlam.ca/bids.aspx?bidID=604), accessed 2026-11-24.
- Mississauga mobile LiDAR RFP: no awarded vendor. [Mississauga tender](https://mississauga.bidsandtenders.ca/Module/Tenders/en/Tender/Detail/92593e30-9884-45cf-b4df-6e19726aa62a), accessed 2026-11-24.
- Chilliwack and Montréal tender notices: no value. [Chilliwack notice](https://canadabuys.canada.ca/en/tender-opportunities/tender-notice/bc218567), accessed 2026-11-24; [Montréal notice](https://seao.gouv.qc.ca/avis-resultat-recherche/consulter?ItemId=b594a80c-5aa9-4136-9cdd-ae9f06bc2909), accessed 2026-11-24.
- Bunt & Associates (Okotoks network screening, Vernon in-service reviews): no value. [Bunt services](https://www.bunteng.com/services/safety/), accessed 2026-11-24.
- ICBC Road Improvement Program funded municipal road safety audits in BC; no price. [ICBC report](https://assets.ctfassets.net/nnc41duedoho/5UfVauuGm5UlAQ53xWWK2f/1ee1d0f5a2e25a92d2d1ba11e0cb6e12/prog-report-rs22a.pdf), accessed 2026-11-24.
- No Canadian municipal screening-only study with a published award value. North Bay is a strategy; Halifax is a collision-data system.
- Parksville and Jakarto / Saint-Hyacinthe twin: no value. [Parksville article](https://pqbnews.com/2023/04/05/ride-van-conducting-parksville-streets-pavement-assessment/), accessed 2026-11-24; [Jakarto blog](https://www.jakarto.com/en/blog/the-city-of-saint-hyacinthe-embraces-digital-twin-technology-for-a-long-terms), accessed 2026-11-24.
- Cyvl, Vialytics, Michelin, MicroTraffic, Brisk/Transoft: no list price (see §2). iRAP: accreditation and training fees only (see §2.3).
- No source prices a defined set of intersections. Lethbridge: award notice gives no count; City page (updated 2025-05-01) lists 29, no project, vendor, value or year; linked by scope and city. CAD 4,706.90/intersection is a derived upper bound. North Bay gives 55 signals but prices a strategy, not intersection reviews ([RFP](https://northbay.ca/media/0zrh15et/road-safety-strategy-request-for-proposals.pdf), accessed 2026-11-24).

A documented absence is a finding; it is not filled with an estimate.

## 2. Comparable firms and products

Every firm below sells by quote or project unless a fee table says otherwise.

### 2.1 Video conflict analytics

| Firm | Offer | Pricing model | Public price | Twin vs it | Source (URL, accessed) |
|---|---|---|---|---|---|
| Miovision (MicroTraffic) | Video conflict analysis at intersections | Project-based study; no list price | No public list price. Grant 2020: 10 intersections; City $12,500 + Aviva $37,500 (75/25). LiveWire 2020-08-13: $5,000/intersection, $50,000/city. Label 2020 grant-funded cost-share rate, not quote/list/market. Keep "$". | Twin adds metric 3D geometry + sight distance; lacks video conflict detection + crash correlation | [Miovision press release](https://miovision.com/press-release/miovision-acquires-microtraffic/), accessed 2026-11-24; [Toronto motion MM24.33](https://www.toronto.ca/legdocs/mmis/2020/mm/bgrd/backgroundfile-157141.pdf), accessed 2026-11-24; [LiveWire Calgary](https://livewirecalgary.com/2020/08/13/predictive-video-traffic-data-reducing-calgary-road-conflicts/), accessed 2026-11-24 |
| Transoft Solutions (Brisk Synergies) | BriskLUMINA = temporary-camera conflict analysis; BriskVANTAGE = continuous live monitoring; 2020 release: surrogate safety/near-miss. Current naming unconfirmed; current page lists VERALYTIX. Transoft owns Brisk. | Quote-based; no public price | No public price. | Twin adds metric 3D geometry + sight distance; lacks video conflict detection + crash correlation | [Transoft acquisition release](https://www.transoftsolutions.com/news/transoft-solutions-acquires-brisk-synergies-to-leverage-machine-learning-and-vision-analytics-for-safer-cities/), accessed 2026-11-24; [Transoft safety page](https://www.transoftsolutions.com/transportation-safety-operations/), accessed 2026-11-24 |

Acquisition closed 2023-02-28 for MicroTraffic/Miovision; 2020-01-13 for Brisk/Transoft.

### 2.2 Mobile asset inventory and pavement condition

- **Cyvl**: vehicle-mounted sensors + software for pavement, sidewalks/ramps, markings, MUTCD signs, right-of-way assets; capital planning + pavement condition. Quote-based; no price. [Cyvl](https://www.cyvl.com/), accessed 2026-11-24.
- **Vialytics**: drive-based road documentation, pavement condition, asset inventory, work orders. Pricing factors: network miles, road type, Essentials/Pro/Enterprise modules. No numeric prices. [Vialytics pricing](https://www.vialytics.com/packages-and-pricing), accessed 2026-11-24.
- **RoadBotics (successor)**: roadbotics.com now leads to Michelin Mobility Intelligence "Road Assessments". Pavement condition rating from imagery. Quote-based; no public price. No acquisition date/terms/rating scale unless a fetched source gives them. [Michelin road assessments](https://mobilityintelligence.michelin.com/us/road-assessments/), accessed 2026-11-24.
- **StreetScan (Canadian comparable)**: mobile LiDAR road-needs study; no list price. Observed: ≈CAD 292.89/centreline km scan-only and ≈CAD 448.03/centreline km all-in at Lakeshore ([2025 RNS](https://media-003-ca.cdn.govstack.com/lakeshore-018-ca/media/2iabu2kq/lakeshore-2025-road-needs-study-rns.pdf), accessed 2026-11-24); ≈CAD 298.70/paved lane-km at Timmins ([Timmins doc](https://timmins.civicweb.net/document/159924/), accessed 2026-11-24). 2024 procurement unverified (403). See §1.2.
- **Twin comparison** ([spec](../../design/twin-v1-spec.md) goals/non-goals; [ADR 0002](../../decisions/0002-digital-twin.md); [ADR 0003](../../decisions/0003-risk-engine.md)): adds 3D geometry, sight distance, drawings; lacks pavement condition ratings, asset-management workflow, city-wide coverage.

### 2.3 Network assessment frameworks

- **iRAP**: 1–5 star ratings of road infrastructure ([irap.org/what-we-do](https://irap.org/what-we-do/), accessed 2026-11-24). Assessments delivered by accredited suppliers at project quotes; no assessment price published.
- **Accreditation fees** (USD, per person/system; [irap.org/accreditation](https://irap.org/accreditation/), accessed 2026-11-24): practitioners USD 300 high-income / USD 150 otherwise (1-year renewal); inspection system USD 9,750 (3-year); AiRAP USD 9,600 (≤10 attributes) / USD 14,400 (>10); AiRAP-enabled inspection system USD 13,550 / USD 15,950.
- **Training fees** (USD; [irap.org/training](https://irap.org/training/), accessed 2026-11-24): Star Rating Essentials USD 300; SR4D USD 200; coding courses USD 100. Page also lists other USD 100 courses and some free ones; quote only the three named.
- **RAP licence** ([irap.org/accreditation](https://irap.org/accreditation/), accessed 2026-11-24): no RAP-licence fee is published. Do not call licence or assessments free. Accreditation and training fee tables are published.
- **Twin comparison** ([spec](../../design/twin-v1-spec.md) goals/non-goals; [ADR 0003](../../decisions/0003-risk-engine.md)): adds measured 3D geometry + sight distance; lacks network-wide star ratings + crash-cost modelling.

### 2.4 Measured 3D twins

- **Jakarto**: mobile mapping (LiDAR + 360°) of Saint-Hyacinthe, 425 km, annual re-capture, asset inventories. Multi-year city contract; no price. Closest comparable. [Jakarto blog](https://www.jakarto.com/en/blog/the-city-of-saint-hyacinthe-embraces-digital-twin-technology-for-a-long-terms), accessed 2026-11-24.
- **This repo's twin**: see §3 ([spec](../../design/twin-v1-spec.md)). Defensible difference: stated metric error + sight-distance output, not city-wide inventory.
- **Twin comparison** ([spec](../../design/twin-v1-spec.md) goals/non-goals; [ADR 0002](../../decisions/0002-digital-twin.md)): adds auditable P50/P95 accuracy + sight distance; lacks city-wide coverage + asset-management platform.

## 3. What a measured 3D twin adds and lacks

Every bullet links to a repo file and section: [docs/design/twin-v1-spec.md](../../design/twin-v1-spec.md) (goals/non-goals, R1, R7, R12), [ADR 0002](../../decisions/0002-digital-twin.md), [ADR 0003](../../decisions/0003-risk-engine.md), or [CONTEXT.md](../../../CONTEXT.md). Vocabulary: **Feature** entry under "The twin" in [CONTEXT.md](../../../CONTEXT.md).

Adds:

- Georeferenced point cloud, one CRS (EPSG:32619), ground/non-ground split. ([spec](../../design/twin-v1-spec.md) §2 goal 1; §4 stage 1)
- 3D lane markings, crosswalks, curb lines from lidar. ([spec](../../design/twin-v1-spec.md) §2 goal 1; §4 stage 5)
- True-colour 5 cm orthoimage and RGB points; unobserved ground transparent. ([spec](../../design/twin-v1-spec.md) §2 goal 5a; §4 stage 6)
- Sight distance in 3D, AASHTO Case B, per leg and access-point exit; "indeterminate" when coverage or height fails. ([spec](../../design/twin-v1-spec.md) §2 goal 3; §4 stage 8)
- Plan-view accuracy P50/P95 per element and facility, with coverage. ([spec](../../design/twin-v1-spec.md) §2 goal 4; §4 stage 9)
- Vertical profile per direction, descriptive only. ([spec](../../design/twin-v1-spec.md) §2 goal 2; R1)
- DXF and PDF plan/profile drawings. ([spec](../../design/twin-v1-spec.md) §2 goal 5; §4 stage 10)
- Stated target: 20 cm or better on lane and curb edges. ([ADR 0002](../../decisions/0002-digital-twin.md) decision 4)

Lacks:

- No video conflict analytics or near-miss detection. ([spec](../../design/twin-v1-spec.md) §2 non-goals)
- No network-wide crash history, trends or police crash data. ([spec](../../design/twin-v1-spec.md) §2 non-goals)
- No pavement condition rating (IRI/PCI) or distress detection. ([spec](../../design/twin-v1-spec.md) §2 non-goals)
- No signs, signals, poles, sidewalks or twin-derived access points in v1. ([spec](../../design/twin-v1-spec.md) §2 non-goals)
- No asset-management work orders or capital planning. ([spec](../../design/twin-v1-spec.md) §2 non-goals)
- No city-wide or province-wide coverage (v1: one Boston area, nuScenes mini, CC BY-NC-SA 4.0, non-commercial research demo). ([spec](../../design/twin-v1-spec.md) §2 non-goals)
- No independent height reference; absolute georeference error unknown; profile descriptive. ([spec](../../design/twin-v1-spec.md) §2 non-goals)
- No Gaussian splatting or interactive viewer. ([spec](../../design/twin-v1-spec.md) §2 non-goals)

A paid pilot needs a non-nuScenes data source and a legal review of the Topcon patent (spec R7 and R12). Scope evidence, not legal advice.

## 4. What the evidence supports for a pilot price

| Finding | Evidence | Status |
|---|---|---|
| Two public awards: CAD 136,500 (2024, Lethbridge) and CAD 166,610 + HST (2023, North Bay) | Lethbridge 136,500 (2024, third-party mirror); North Bay 166,610 + HST (2023) | Two public awards; different scopes; not a band. |
| Lethbridge's 29 listed intersections → derived CAD 4,706.90/intersection upper bound | 136,500 / 29; City page updated 2025-05-01; award includes preliminary design | Derived upper bound; not a quote. |
| Lakeshore scan-only rate CAD 292.89/centreline km | Lakeshore 159,260.50 / 543.76 | One award; not a general rate. |
| Lakeshore all-in rate CAD 448.03/centreline km | Lakeshore 243,619.55 / 543.76 | One award; not a general rate. |
| Timmins all-in rate CAD 298.70/paved lane-km | Timmins 121,273.80 / 406 | One award; different unit/scope. |
| Toronto 2017 automated collection award CAD 1,294,386 net year 1 | Toronto 1,294,386 net, year 1 | One 2017 award; different scope. |
| A price for a defined set of intersections | Lethbridge derived upper bound; North Bay prices a strategy | No source prices a defined set. |
| A competitor's assessment or product list price | Vendor pages publish factors or quote models; iRAP publishes accreditation/training fees only | Documented absence |
| The twin is a measurement product | [Spec goals and non-goals](../../design/twin-v1-spec.md); firm pages | Inferred |
| v1 cannot be sold as-is | nuScenes licence; [spec R7](../../design/twin-v1-spec.md); [spec R12](../../design/twin-v1-spec.md) | Proven by spec and dataset licence |
| Lower Mainland prices | No award for the four cities in the sources listed | Documented absence |

What a pilot can be compared to. Compare per study, per centreline km and per paved lane-km. Do not merge per-km and per-lane-km. A per-intersection figure exists only for Lethbridge, a derived upper bound, not a quote.

What the twin must not claim. No conflict analytics, crash prediction, pavement condition, asset workflow or city-wide coverage. Position as measured geometry for sight-distance and audit checks. Review findings and the collision-risk engine ([ADR 0003](../../decisions/0003-risk-engine.md)) are separate, not priced.

What a paid pilot needs. A non-nuScenes data source and a legal review of the Topcon patent; the demo is non-commercial. Vancouver 2022 airborne lidar is named in [ADR 0002](../../decisions/0002-digital-twin.md) (decision 11) as the lidar-only v1.1 source.

## Limits and not verified

- Lethbridge: third-party mirror; original not re-fetched; mirror's BC province field unused. City page (updated 2025-05-01) lists 29 intersections; no project name, vendor, value or year; linked by scope and city.
- Lakeshore 2024 award report returned 403; procurement method unverified. 2025 RNS gives 543.76 centreline km; award's 533 km was a planning figure. Printed Step 1+2 sum 243,619.54, one cent below printed total.
- Toronto network size not in excerpt; no per-km. Halifax monthly figure derived under even-spend assumption.
- Toronto motion and LiveWire Calgary (2020-08-13) use $ with no stated currency.
- Vendor pages point-in-time; access dates in every row. No contact, quote, login or form used.
- Omitted unconfirmed facts: current Brisk naming, RoadBotics acquisition date, iRAP RAP-licence fee.
- No exchange rate applied; USD items stay USD. Bot-blocking 403/406 acceptable only for sources read this run.
