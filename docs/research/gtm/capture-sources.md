# Capture sources for Coquitlam, Surrey, Vancouver and Richmond

Issue #472 (part of #485). Researched 2026-11-24. All web sources accessed 2026-11-24.

Rechecked pages carry 2026-11-25 access dates. The question is which sources other than an own rig can supply commercial-use data for Coquitlam, Surrey, Vancouver and Richmond. These feed an in-service road safety review; the commercial licence is the gating fact. Method: desk research of primary sources; no vendor contacted, no quote requested. Not legal advice. “Fit for a paid pilot” means the licence supports a paid deliverable, coverage is adequate, and no rig is needed.

**Bottom line:** Summarising §1–§5: open aerial/ortho data cover terrain in all four cities, including Coquitlam 2024/2025 imagery and the Metro Vancouver Richmond-area ortho 2025, but no municipal street-level imagery was found; street-level capture is the gap. Surrey has point signs and polyline curbs under OGL – Surrey; Vancouver has wayfinding signage only, not traffic signs; Coquitlam and Richmond have no curb or sign inventory, so coverage outside Surrey is partial. Bee's subsidised membership is US/Puerto Rico only and Bee LTE (Global) is separate, so a BC programme via Bee is unavailable; Hivemapper sells map data globally. Mapillary's terms explicitly address commercial use, but CC-BY-SA makes a closed paid deliverable conditional on attribution, share-alike and legal review. Panoramax depends on the instance; OSM-FR is unsuitable for a closed paid derivative without legal review. No service reviewed gives an unconditional commercial green light for a closed paid audit.

## 1. Municipal open data

No municipal mobile light detection and ranging (LiDAR) dataset or service was found for any of the four cities searched (accessed 2026-11-24): [Coquitlam](https://data.coquitlam.ca/), [Surrey](https://www.surrey.ca/services-payments/online-services/open-data), [Vancouver](https://opendata.vancouver.ca/) and [Richmond](https://www.richmond.ca/city-hall/strategies/sale.htm). Where a page does not state the acquisition method, the data is treated as aerial/terrain.

No City of Richmond open-data portal publishing geospatial data was found (accessed 2026-11-24): the [sale page](https://www.richmond.ca/city-hall/strategies/sale.htm), [Transparent Richmond report](https://richmondstandard.com/breaking-news/2020/02/20/city-launches-transparent-richmond-platform) and [public REST directory](https://corportal1.richmond.ca/server/rest/services). “Transparent Richmond” is financial/performance; the Interactive Map is a viewer. City geographic information system (GIS) layers are CAD 131.00 first / CAD 70.00 additional, price date not stated, licence unverified ([sale page](https://www.richmond.ca/city-hall/strategies/sale.htm), accessed 2026-11-24).

### Coquitlam

**LiDAR (mobile and aerial)** — No city-run mobile LiDAR was found on the [portal](https://data.coquitlam.ca/) (accessed 2026-11-24). [Metro Vancouver Coquitlam LiDAR 2022](https://open-data-portal-metrovancouver.hub.arcgis.com/datasets/metrovancouver::coquitlam-area-classified-lidar-2022): 2022, Riegl VQ-1560ii, Quality Level 3 (QL3), ~54.92 GB; density and method not stated, so treated as aerial/terrain. Open Government Licence – Metro Vancouver (OGL – Metro Vancouver), commercial + attribution ([licence](https://open-data-portal-metrovancouver.hub.arcgis.com/pages/Open%20Government%20Licence), accessed 2026-11-24). [Coquitlam River topobathymetric LiDAR 2023](https://data.coquitlam.ca/datasets/Coquitlam::coquitlam-river-topobathymetric-lidar) is LAS 1.4 river-bed survey data, not road data, under Open Government Licence – Coquitlam (OGL – Coquitlam), commercial + attribution ([licence](https://coquitlam.ca/894/Open-Government-Licence), accessed 2026-11-24).

**Orthophotos** — The portal carries [Imagery 2025](https://data.coquitlam.ca/datasets/Coquitlam::city-of-coquitlam-imagery-2025), a [2026 imagery service](https://geodata.coquitlam.ca/arcgis/rest/services/CachedServices/Imagery_2026/MapServer) titled “Coquitlam Orthophotos 2024”, and [2016 MrSID imagery](https://data.coquitlam.ca/documents/Coquitlam::city-of-coquitlam-imagery-2016) as historical (accessed 2026-11-24). Resolution not stated. Licence not stated on the imagery page; the [portal licence](https://coquitlam.ca/894/Open-Government-Licence) permits commercial + attribution for portal data, but application to the imagery service is unverified (accessed 2026-11-24).

**Street-level imagery** — None found on the [city portal](https://data.coquitlam.ca/) (accessed 2026-11-24).

**Curb and sign inventories** — None found on the [city portal](https://data.coquitlam.ca/) (accessed 2026-11-24); the [roads layer](https://data.coquitlam.ca/datasets/Coquitlam::roads) is not an inventory.

**Commercial-use verdict:** OGL – Coquitlam data may be used commercially with attribution where stated ([licence](https://coquitlam.ca/894/Open-Government-Licence), accessed 2026-11-24). The city publishes 2024/2025 imagery, but resolution and imagery-page licence are unverified; municipal street-level imagery, curb inventory and sign inventory were not found.

### Surrey

**LiDAR (mobile and aerial)** — [Bulk page](https://www.surrey.ca/services-payments/online-services/open-data/bulk-data): Raw LiDAR 2022 (LAS), 2022 elevation grid and hillshade (unverified; page unreachable 2026-11-25). Method and density not stated, so treated as aerial/terrain. OGL – Surrey, commercial + attribution ([licence](https://opendata-surrey.hub.arcgis.com/pages/55089a19491a4fe59a41e059fd8af708), accessed 2026-11-24). Free data; requester supplies an external universal serial bus (USB) 3.0 drive of at least 1 TB and pays courier; about one week turnaround stated (accessed 2026-11-24). Coverage not stated.

**Orthophotos** — The [bulk inventory](https://www.surrey.ca/services-payments/online-services/open-data/bulk-data) includes Orthophoto 2022 (unverified; page unreachable 2026-11-25). Resolution not stated. OGL – Surrey, commercial + attribution, same drive and courier condition ([licence](https://opendata-surrey.hub.arcgis.com/pages/55089a19491a4fe59a41e059fd8af708), accessed 2026-11-24).

**Street-level imagery** — None found on the [portal](https://www.surrey.ca/services-payments/online-services/open-data) (accessed 2026-11-24).

**Curb and sign inventories** — [Sign Locations](https://opendata-surrey.hub.arcgis.com/datasets/surrey::sign-locations) uses point geometry and sign/plate codes; [Curbs](https://opendata-surrey.hub.arcgis.com/datasets/surrey::curbs) uses polyline geometry, curb type (barrier, extruded, rollover, pavement edge) and material. Both are OGL – Surrey, commercial + attribution ([licence](https://opendata-surrey.hub.arcgis.com/pages/55089a19491a4fe59a41e059fd8af708), accessed 2026-11-24). Feature count not shown; last-update date not shown; resolution not applicable. REST layers: [signs](https://gisservices.surrey.ca/arcgis/rest/services/OpenData/MapServer/114), [curbs](https://gisservices.surrey.ca/arcgis/rest/services/OpenData/MapServer/123) (accessed 2026-11-24).

**Commercial-use verdict:** OGL – Surrey allows commercial + attribution ([licence](https://opendata-surrey.hub.arcgis.com/pages/55089a19491a4fe59a41e059fd8af708), accessed 2026-11-24). Both inventories are published; counts and dates not shown; municipal street-level imagery was not found; aerial coverage and resolution not stated; bulk LiDAR delivery is on physical media.

### Vancouver

**LiDAR (mobile and aerial)** — [LiDAR 2022](https://opendata.vancouver.ca/explore/dataset/lidar-2022) is aerial, captured 2022-09-07 to 2022-09-09, 134 km², ~49 points/m², 0.081 m vertical accuracy at 95%, 181 tiles (accessed 2026-11-24). OGL – Vancouver, commercial + attribution ([licence](https://opendata.vancouver.ca/pages/licence), accessed 2026-11-24).

**Orthophotos** — [Orthophoto imagery 2022](https://opendata.vancouver.ca/explore/dataset/orthophoto-imagery-2022) is 7.5 cm, captured 2022-06-06 to 2022-07-01, covering the City, University of British Columbia (UBC), University Endowment Lands (UEL), parts of Richmond and Vancouver International Airport (YVR) (accessed 2026-11-24). OGL – Vancouver, commercial + attribution ([licence](https://opendata.vancouver.ca/pages/licence), accessed 2026-11-24).

**Street-level imagery** — None found on the [portal](https://opendata.vancouver.ca/) (accessed 2026-11-24).

**Curb and sign inventories** — A traffic-sign inventory was not found on the [portal](https://opendata.vancouver.ca/) (accessed 2026-11-24). [Wayfinding map stands](https://opendata.vancouver.ca/explore/dataset/wayfinding-map-stands) lists 216 records, modified 2020-11-19, and is wayfinding only (accessed 2026-11-25). OGL – Vancouver, commercial + attribution ([licence](https://opendata.vancouver.ca/pages/licence), accessed 2026-11-24); resolution not applicable. A curb inventory was not found.

**Commercial-use verdict:** OGL – Vancouver allows commercial + attribution ([licence](https://opendata.vancouver.ca/pages/licence), accessed 2026-11-24). The 2022 LiDAR and 7.5 cm ortho are the highest-resolution open municipal data in this review ([LiDAR](https://opendata.vancouver.ca/explore/dataset/lidar-2022), [ortho](https://opendata.vancouver.ca/explore/dataset/orthophoto-imagery-2022), accessed 2026-11-24); the sign inventory covers wayfinding only, a curb inventory was not found, and municipal street-level imagery was not found.

### Richmond

**LiDAR (mobile and aerial)** — [Metro Vancouver Richmond LiDAR 2022](https://open-data-portal-metrovancouver.hub.arcgis.com/content/e8f531b04e7d432b8deff7e825c657d0): 2022, Riegl VQ-1560ii, QL3, ~16.29 GB; density and method not stated, so treated as aerial/terrain (accessed 2026-11-24). OGL – Metro Vancouver, commercial + attribution ([licence](https://open-data-portal-metrovancouver.hub.arcgis.com/pages/Open%20Government%20Licence), accessed 2026-11-24).

**Orthophotos** — [Richmond Area Ortho Imagery 2025](https://open-data-portal-metrovancouver.hub.arcgis.com/datasets/metrovancouver::richmond-area-area-ortho-imagery-2025) is 2025 under OGL – Metro Vancouver, commercial + attribution; resolution not shown ([licence](https://open-data-portal-metrovancouver.hub.arcgis.com/pages/Open%20Government%20Licence), accessed 2026-11-24). Vancouver's [orthophoto 2022](https://opendata.vancouver.ca/explore/dataset/orthophoto-imagery-2022) covers parts of Richmond: 2022, 7.5 cm, partial, OGL – Vancouver, commercial + attribution ([licence](https://opendata.vancouver.ca/pages/licence), accessed 2026-11-24).

**Street-level imagery** — None found on the [city pages](https://www.richmond.ca/city-hall/strategies/sale.htm) and [REST directory](https://corportal1.richmond.ca/server/rest/services) searched (accessed 2026-11-24).

**Curb and sign inventories** — A curb inventory and a traffic-sign inventory were not found (accessed 2026-11-24). The [REST directory](https://corportal1.richmond.ca/server/rest/services) exposes AirPhotoSpring2025, AirPhotoSpring2026, AirPhotoFall2024 and a SignShop folder; terms and licence unverified, so not licensed open data (accessed 2026-11-24).

**Commercial-use verdict:** Regional LiDAR, Metro Vancouver ortho 2025 and partial Vancouver ortho are commercial under OGL with attribution ([Metro Vancouver licence](https://open-data-portal-metrovancouver.hub.arcgis.com/pages/Open%20Government%20Licence), [Vancouver licence](https://opendata.vancouver.ca/pages/licence), accessed 2026-11-24). Richmond's own GIS layers are billed and REST terms unverified ([sale page](https://www.richmond.ca/city-hall/strategies/sale.htm), accessed 2026-11-24); a curb or traffic-sign inventory was not found, and municipal street-level imagery was not found.

## 2. Provincial and regional data

### LidarBC

The BC programme is CAD 38M over six years, acquisition 2023–2027, publication through 2029 ([programme](https://lidar.gov.bc.ca/), [news release](https://news.gov.bc.ca/releases/2023WLRS0054-001554), accessed 2026-11-24). Products are airborne only: classified point clouds in LASzip (LAZ), digital elevation models (DEM), digital surface models (DSM), canopy height models (CHM) and forestry products; no aerial imagery or street-level data ([programme](https://lidar.gov.bc.ca/), accessed 2026-11-24). Open Government Licence – British Columbia (OGL – BC), commercial use with “attribution as required by the OGL – BC”; free ([information](https://lidar.gov.bc.ca/pages/information), accessed 2026-11-24). Coverage is partial; completeness for the four cities is unverified on the [availability map](https://lidar.gov.bc.ca/) (accessed 2026-11-24). Verdict: useful aerial/terrain source; not street-level.

### Metro Vancouver

The [portal](https://open-data-portal-metrovancouver.hub.arcgis.com/) publishes aerial imagery and classified point clouds, including Coquitlam and Richmond 2022 LiDAR (accessed 2026-11-24). OGL – Metro Vancouver, commercial + attribution; free download ([licence](https://open-data-portal-metrovancouver.hub.arcgis.com/pages/Open%20Government%20Licence), accessed 2026-11-24). Municipal street-level imagery was not found on the portal pages searched (accessed 2026-11-24). Verdict: regional aerial/terrain source; not street-level.

### TransLink

The [TransLink Open API](https://developer.translink.ca/) is an application programming interface (API) for General Transit Feed Specification (GTFS) static and real-time transit data only; registration and identification are required, and commercial use is under [TransLink's terms](https://developer.translink.ca/) (accessed 2026-11-24). Imagery or LiDAR not found (accessed 2026-11-24). Verdict: commercial under TransLink terms; not capture.

## 3. Mobile-mapping vendors active in BC

No vendor on the pages reviewed published a BC price list; the capture vendors below are quote-only as of 2026-11-24, and NavVis uses personalized pricing. Licence and price are contract terms; no public terms were found on vendor pages.

| Vendor | BC presence or evidence | Service or data | Public price (type + date) | Source |
|---|---|---|---|---|
| McElhanney | BC-active: 130 km Chilliwack mobile LiDAR drive in 2022 | Mobile laser scanning | Quote only (accessed 2026-11-24) | [page](https://www.mcelhanney.com/lidar), [project](https://www.mcelhanney.com/project/tmep_wiremapping) (accessed 2026-11-24) |
| GeoScan | BC-active: Vancouver, Victoria, Kelowna offices | LiDAR/mobile mapping, vehicle or unmanned aerial vehicle (UAV) | Quote only (accessed 2026-11-24) | [page](https://www.geoscan.ca/services/lidar-services-and-mobile-mapping) (accessed 2026-11-24) |
| Planview Utility Services | BC-active: LiDAR fleet; municipal/utility customers | Mobile LiDAR, 360° view, street imagery | Quote only (accessed 2026-11-24) | [page](https://planview.ca/lidar-mobile-mapping/) (accessed 2026-11-24) |
| Convex Geomatics | BC-active: serves BC | Vehicle mobile LiDAR and 360° panoramic imaging | Quote only (accessed 2026-11-24) | [page](https://convexgeomatics.com/services/mobile-lidar-survey) (accessed 2026-11-24) |
| Applus+ Canada | BC presence unverified | Mobile LiDAR, vehicle, drone or handheld | Quote only (accessed 2026-11-24) | [page](https://www.applus.com/ca/en/what-we-do/sub-service-sheet/mobile-lidar-for-reality-capture) (accessed 2026-11-24) |
| Kiwa T2 | BC presence unverified | LiDAR/mobile mapping for municipalities and utilities | Quote only (accessed 2026-11-24) | [page](https://www.kiwa.com/ca/en-ca/services/consulting-and-engineering/lidar-and-mobile-mapping) (accessed 2026-11-24) |
| NavVis | Tooling, not a capture service | CLX, MLX, VLX scanners; IVION software | Personalized price (accessed 2026-11-24) | [page](https://www.navvis.com/en/pricing) (accessed 2026-11-24) |

Technical fit is plausible; licence and price are unknown until a quote.

## 4. Fleet partnerships

### Fleets already driving the four cities

Courier: [FedEx OnSite](https://local.fedex.com/en-ca/bc/vancouver/yhcfp) names Vancouver; other three cities not covered on that page. Delivery: [DoorDash Vancouver](https://www.doordash.com/en/food-delivery/vancouver-bc-restaurants/delivery) names Vancouver; other three not covered. Ride-hail: [Uber Vancouver](https://www.uber.com/global/en/r/cities/vancouver-bc-ca) names Vancouver; other three not covered. Utility: [BC Hydro service area map](https://www.bchydro.com/content/dam/BCHydro/customer-portal/documents/corporate/safety/bchydro-service-area-map.pdf) names all four. Car-share: [Evo](https://evo.ca/) names Vancouver and Surrey; Coquitlam and Richmond not covered (accessed 2026-11-25).

No published mapping-data programme was found on the companies' own service or press pages linked here (accessed 2026-11-24); search scope: service-area, press, and partnership pages.

### Programmes that pay drivers to carry sensors

| Programme | Hardware | How the driver is paid | Data licence | Coverage in Metro Vancouver |
|---|---|---|---|---|
| Hivemapper / Bee Maps | Bee dashcam: 12.3 MP/30 Hz, 800p stereo (13 cm), global navigation satellite system (GNSS) L1/L5, six-axis inertial measurement unit (IMU), 64 GB, up to 10 h at 4 Mbps ([Bee](https://beemaps.com/bee), accessed 2026-11-25) | Paid in USD Coin (USDC) weekly via Circle Wallet on Base against road-km goals; earlier HONEY; since August 2026 discretionary company-budget rewards, no published rate ([rewards](https://beemaps.com/docs/camera/get-started-with-the-bee/rewards), accessed 2026-11-24) | Sold as commercial map products; data price not public ([driving](https://docs.hivemapper.com/contribute/driving), accessed 2026-11-24) | Unverified: density not published ([Bee](https://beemaps.com/bee), accessed 2026-11-25) |
| Mapillary | Own phone or optional 360 camera ([help](https://help.mapillary.com/hc/en-us/articles/115001770409), accessed 2026-11-24) | Not paid directly ([terms](https://www.mapillary.com/legal/terms), accessed 2026-11-25) | Creative Commons Attribution-ShareAlike 4.0 (CC-BY-SA 4.0); broad commercial grant ([help](https://help.mapillary.com/hc/en-us/articles/115001770409), accessed 2026-11-24) | Unverified: density not published ([terms](https://www.mapillary.com/legal/terms), accessed 2026-11-25) |
| Nexar | Connected dashcam; hardware from US$159.95 ([fleet](https://www.getnexar.com/fleet-solutions), accessed 2026-11-25) | Drivers/fleets buy hardware and subscription; not paid by Nexar ([fleet](https://www.getnexar.com/fleet-solutions), accessed 2026-11-25) | Sells data products; data price not public ([fleet](https://www.getnexar.com/fleet-solutions), accessed 2026-11-25) | Unverified: Canada/BC coverage ([fleet](https://www.getnexar.com/fleet-solutions), accessed 2026-11-25) |

Bee Membership requires a 24-month contract and is “Available only in the U.S. and Puerto Rico.” ([Bee](https://beemaps.com/bee), accessed 2026-11-25). Bee LTE (Global) is separate and map data is sold globally, so a BC capture programme through Bee Membership is not available ([Bee](https://beemaps.com/bee), [driving](https://docs.hivemapper.com/contribute/driving), accessed 2026-11-25 and 2026-11-24). The current Bee page states US$19/month; US$589 upfront is a reported list price from 2025-10-06 and may be stale ([Bee](https://beemaps.com/bee), [Blockworks report](https://blockworks.com/news/hivemapper-raise-bee-dashcams), accessed 2026-11-25 and 2026-11-24). Nexar reports 94% of US roads and 50+ countries; hardware from US$159.95 and subscription from US$14.99/month/vehicle, USD as published; no CAD conversion given ([fleet](https://www.getnexar.com/fleet-solutions), accessed 2026-11-25). No other paid mapping programme with a public rate was found (accessed 2026-11-25); Uber/Lyft–Nexar reports do not show driver payment, and the proposed Flock–Nexar automatic licence plate recognition (ALPR) partnership was never executed ([report](https://decrypt.co/375149/flock-cameras-uber-drivers-nationwide-plate-scanning-fleet), accessed 2026-11-25).

## 5. Street-imagery licences

### Google Street View

Google Maps End User Additional Terms were last modified 2026-01-27. The clause says users may not “use Google Maps to create or augment any other mapping-related dataset (including a mapping or navigation dataset, business listings database, mailing list, or telemarketing list) for use in a service that is a substitute for, or a substantially similar service to, Google Maps” ([terms](https://www.google.com/help/terms_maps), [policies](https://developers.google.com/maps/documentation/streetview/policies), accessed 2026-11-25). **Paid-audit verdict: Not allowed** — the clause blocks extraction, storage and derivative use.

### Mapillary

Mapillary Terms of Service are effective 2024-02-15. Section 12 states: “You may use the Mapillary Services only for the following commercial purposes: (i) improvement, training, and development of products, services, maps, studies, platforms, websites, applications, software, algorithms, datasets, solutions, or technologies; and (ii) in the provision of services for or on behalf of one or more of your clients.” ([terms](https://www.mapillary.com/legal/terms), accessed 2026-11-25). Imagery is CC-BY-SA 4.0 ([help](https://help.mapillary.com/hc/en-us/articles/115001770409), accessed 2026-11-24). **Paid-audit verdict: Conditional** — attribution and share-alike require legal review for a closed paid deliverable.

### Bing Streetside

Microsoft Maps End User Terms were last updated 2021-11-01. Section 3(b) states: “You may not modify, copy, distribute, transmit, display, perform, reproduce, publish, license, create derivative works from, sublicense, transfer, assign, rent, sell, or otherwise convey any information, software, products, or services obtained from Bing Maps Services without the prior written approval from Microsoft.” ([terms](https://www.microsoft.com/en-us/maps/bing-maps/product/enduserterms), accessed 2026-11-25). A Microsoft Q&A answer dated 2025-02-28 is supporting context only, not the licence ([Q&A](https://learn.microsoft.com/en-us/answers/questions/2344821), accessed 2026-11-24). **Paid-audit verdict: Conditional** — prior written approval is required.

### Cyclomedia

The General Terms dated 2025-03-01 state: “The licence is limited to the internal use of the Data and/or the Data Insights by the Client for the purposes set out in the Agreement.” Section 23.3 adds that “the Client must submit the intended purposes of use to Cyclomedia in writing for approval.” ([2025 terms](https://cdn.prod.website-files.com/69bd3518dd960ca00ae76dcc/69e0cf680bac25abc7141699_General_Terms_and_Conditions_Cyclomedia_Technology_B.V._20250301.pdf), accessed 2026-11-25). The 2021-01-01 terms used §24.2/§24.3 (unverified; page unreachable 2026-11-25). **Paid-audit verdict: Conditional** — internal use is the default and other purposes require written approval.

### Panoramax

Terms vary by instance. OSM-FR uses CC-BY-SA 4.0 for pictures; derived data may be under Licence Ouverte 2.0, CC-BY 4.0 or Open Database Licence (ODbL) 1.0 ([OSM-FR terms](https://panoramax.openstreetmap.fr/terms-of-service), accessed 2026-11-24; unverified; page unreachable 2026-11-25). The federation docs say the licence is meant to “avoid the creation of closed data, derivated database, artwork or picture” ([docs](https://docs.panoramax.fr/federated-catalog), accessed 2026-11-25). **Paid-audit verdict: Conditional** — instance terms apply; OSM-FR is not suitable for a closed paid derivative without legal review. Metro Vancouver coverage was not assessed.

These are licence readings, not legal advice; counsel should review before a paid launch.

## 6. What this means for a paid pilot

- **Aerial/terrain base is available.** Vancouver: 2022 LiDAR, 7.5 cm ortho. Surrey: 2022 LiDAR/ortho on physical media. Coquitlam: 2024/2025 imagery. Richmond: Metro Vancouver ortho 2025, partial Vancouver 2022 ortho ([Vancouver LiDAR](https://opendata.vancouver.ca/explore/dataset/lidar-2022), [ortho](https://opendata.vancouver.ca/explore/dataset/orthophoto-imagery-2022), [Surrey bulk](https://www.surrey.ca/services-payments/online-services/open-data/bulk-data), [Coquitlam imagery](https://data.coquitlam.ca/datasets/Coquitlam::city-of-coquitlam-imagery-2025), [Richmond ortho](https://open-data-portal-metrovancouver.hub.arcgis.com/datasets/metrovancouver::richmond-area-area-ortho-imagery-2025), accessed 2026-11-24). OGL with commercial attribution applies to Coquitlam where stated, Surrey, Vancouver, Metro Vancouver and LidarBC ([licence](https://coquitlam.ca/894/Open-Government-Licence), [licence](https://opendata-surrey.hub.arcgis.com/pages/55089a19491a4fe59a41e059fd8af708), [licence](https://opendata.vancouver.ca/pages/licence), [licence](https://open-data-portal-metrovancouver.hub.arcgis.com/pages/Open%20Government%20Licence), accessed 2026-11-24). Coquitlam imagery licence, Richmond billed GIS layers and TransLink were not verified as capture sources ([TransLink](https://developer.translink.ca/), accessed 2026-11-24).
- **Street-level is the gap; curb and sign coverage is uneven.** No municipal street-level imagery was found in the four cities ([Coquitlam](https://data.coquitlam.ca/), [Surrey](https://www.surrey.ca/services-payments/online-services/open-data), [Vancouver](https://opendata.vancouver.ca/), [Richmond](https://www.richmond.ca/city-hall/strategies/sale.htm), accessed 2026-11-24). Surrey has point signs and polyline curbs under OGL – Surrey; Vancouver has wayfinding signs only; Coquitlam and Richmond have no curb or sign inventory searched ([signs](https://opendata-surrey.hub.arcgis.com/datasets/surrey::sign-locations), [curbs](https://opendata-surrey.hub.arcgis.com/datasets/surrey::curbs), [wayfinding](https://opendata.vancouver.ca/explore/dataset/wayfinding-map-stands), accessed 2026-11-24 and 2026-11-25). A paid pilot needs paid capture, a vendor service, or Mapillary with conditions ([terms](https://www.mapillary.com/legal/terms), accessed 2026-11-25). No public BC price found on pages reviewed; budget “quote only” ([vendor](https://convexgeomatics.com/services/mobile-lidar-survey), accessed 2026-11-24).
- **Imagery licences decide the rest.** Google `Not allowed` ([terms](https://www.google.com/help/terms_maps), accessed 2026-11-25); Bing `Conditional` approval ([terms](https://www.microsoft.com/en-us/maps/bing-maps/product/enduserterms), accessed 2026-11-25); Cyclomedia `Conditional` §23.2/§23.3 ([2025 terms](https://cdn.prod.website-files.com/69bd3518dd960ca00ae76dcc/69e0cf680bac25abc7141699_General_Terms_and_Conditions_Cyclomedia_Technology_B.V._20250301.pdf), accessed 2026-11-25); Panoramax `Conditional` instance terms ([docs](https://docs.panoramax.fr/federated-catalog), accessed 2026-11-25); Mapillary `Conditional` attribution/share-alike ([terms](https://www.mapillary.com/legal/terms), accessed 2026-11-25). No service reviewed gives an unconditional commercial green light for a closed paid audit.
- **Fleet imagery is supplemental, not a base.** Bee pays contributors, but Bee Membership is US/Puerto Rico only and Bee LTE (Global) is separate, so a BC programme via Bee is unavailable ([Bee](https://beemaps.com/bee), accessed 2026-11-25). Mapillary has no driver payment ([terms](https://www.mapillary.com/legal/terms), accessed 2026-11-25). Nexar drivers pay; BC coverage unverified ([fleet](https://www.getnexar.com/fleet-solutions), accessed 2026-11-25). None substitutes for planned curb and sign capture.
- **What a pilot can do without a rig.** Use open aerial/ortho for terrain ([Vancouver LiDAR](https://opendata.vancouver.ca/explore/dataset/lidar-2022), [Richmond ortho](https://open-data-portal-metrovancouver.hub.arcgis.com/datasets/metrovancouver::richmond-area-area-ortho-imagery-2025), accessed 2026-11-24); for missing curb, sign and street-level coverage, obtain a vendor quote or written data agreement ([McElhanney](https://www.mcelhanney.com/lidar), [Mapillary terms](https://www.mapillary.com/legal/terms), accessed 2026-11-24 and 2026-11-25). Record attribution strings for each OGL source ([OGL – BC](https://lidar.gov.bc.ca/pages/information), accessed 2026-11-24). Not legal advice.

## 7. Unknowns and limits

1. No municipal street-level imagery was found for the four cities or regional portals; no curb/sign inventory for Coquitlam or Richmond; Vancouver wayfinding only; Surrey both, count/date not shown on the fetched pages ([portals](https://data.coquitlam.ca/), [Surrey](https://opendata-surrey.hub.arcgis.com/datasets/surrey::sign-locations), [Vancouver](https://opendata.vancouver.ca/explore/dataset/wayfinding-map-stands), accessed 2026-11-24 and 2026-11-25).
2. LidarBC coverage completeness for the four cities is unverified; check the [availability map](https://lidar.gov.bc.ca/) (accessed 2026-11-24).
3. No Richmond geospatial open-data portal was found; GIS layers CAD 131 first / CAD 70 additional, price date not stated, licence unverified ([sale](https://www.richmond.ca/city-hall/strategies/sale.htm), [REST](https://corportal1.richmond.ca/server/rest/services), accessed 2026-11-24).
4. No BC vendor list price or public licence terms were found; capture vendors quote-only; NavVis personalized; no vendor contacted ([vendor](https://convexgeomatics.com/services/mobile-lidar-survey), [NavVis](https://www.navvis.com/en/pricing), accessed 2026-11-24).
5. Bee data pricing and density not public; Bee US/Puerto Rico only, LTE separate; Mapillary density not published; Panoramax coverage not assessed ([Bee](https://beemaps.com/bee), [Mapillary](https://www.mapillary.com/legal/terms), [Panoramax](https://docs.panoramax.fr/federated-catalog), accessed 2026-11-24 and 2026-11-25).
6. Nexar Canada/BC coverage unverified; USD list prices; data price not public ([fleet](https://www.getnexar.com/fleet-solutions), accessed 2026-11-25).
7. TransLink provides transit data only, not imagery or LiDAR ([Open API](https://developer.translink.ca/), accessed 2026-11-24).
8. Surrey bulk LiDAR needs a requester-supplied ≥1 TB USB 3.0 drive and courier; method and coverage not stated ([bulk](https://www.surrey.ca/services-payments/online-services/open-data/bulk-data), accessed 2026-11-24; unverified; page unreachable 2026-11-25).
9. Coquitlam LiDAR density, Coquitlam imagery resolution/licence, Surrey ortho resolution, Metro Vancouver ortho resolutions, Surrey counts/dates not stated; treat unstated methods as aerial/terrain ([sources](https://open-data-portal-metrovancouver.hub.arcgis.com/datasets/metrovancouver::coquitlam-area-classified-lidar-2022), [imagery](https://data.coquitlam.ca/datasets/Coquitlam::city-of-coquitlam-imagery-2025), [bulk](https://www.surrey.ca/services-payments/online-services/open-data/bulk-data), accessed 2026-11-24).
10. Mapillary share-alike and vendor contracts need legal review; this note is not legal advice ([terms](https://www.mapillary.com/legal/terms), accessed 2026-11-25).
11. No local courier/delivery/ride-hail/utility/car-share mapping programme was found on pages searched; a direct agreement is outside this ticket ([fleets](https://local.fedex.com/en-ca/bc/vancouver/yhcfp), [Evo](https://evo.ca/), accessed 2026-11-25).
12. Cyclomedia 2025 terms use §23.2 internal use and §23.3 written approval; 2021 used §24.2/§24.3 (unverified; page unreachable 2026-11-25) ([2025 terms](https://cdn.prod.website-files.com/69bd3518dd960ca00ae76dcc/69e0cf680bac25abc7141699_General_Terms_and_Conditions_Cyclomedia_Technology_B.V._20250301.pdf), accessed 2026-11-25).
13. Cyclomedia, Fugro and other search-result vendors were not verified as BC-active; they are not counted as capture options.
14. “No dataset found” means not found, not that no dataset exists; snapshot: public sources accessed 2026-11-24.

This note is a snapshot of public sources accessed 2026-11-24; prices, licences and coverage may change.

## Source comparison

All links in this table were accessed 2026-11-24; costs are list prices, quotes, or labelled approximate conversions. Fit: High = clear licence, coverage, no rig; Medium = plausible but unconfirmed; Low = limited/missing data; Conditional = attribution, share-alike or approval; Not usable = barred or not capture.

| Source | Coverage | Licence | Cost | Fit for a paid pilot |
|---|---|---|---|---|
| [Coquitlam open data](https://data.coquitlam.ca/) | Imagery 2024/2025; 2016 historical; street-level/curb/sign not found | OGL where stated; imagery unverified | Free (list; accessed 2026-11-24) | Medium |
| [Coquitlam LiDAR](https://open-data-portal-metrovancouver.hub.arcgis.com/datasets/metrovancouver::coquitlam-area-classified-lidar-2022) | Coquitlam, QL3; density not stated | OGL – MV | Free (list; accessed 2026-11-24) | Medium |
| [Surrey bulk LiDAR + ortho 2022](https://www.surrey.ca/services-payments/online-services/open-data/bulk-data) | Coverage/resolution/density not stated | OGL – Surrey | Free data; requester supplies an external ≥1 TB USB 3.0 drive and pays courier (list, accessed 2026-11-24) | Medium |
| [Surrey signs](https://opendata-surrey.hub.arcgis.com/datasets/surrey::sign-locations) | Point; sign/plate; count/date not shown | OGL – Surrey | Free (list; accessed 2026-11-24) | Medium |
| [Surrey curbs](https://opendata-surrey.hub.arcgis.com/datasets/surrey::curbs) | Polyline; type/material; count/date not shown | OGL – Surrey | Free (list; accessed 2026-11-24) | Medium |
| [Vancouver LiDAR](https://opendata.vancouver.ca/explore/dataset/lidar-2022) | 134 km²; ~49 points/m²; 0.081 m @95%; 181 tiles | OGL – Vancouver | Free (list; accessed 2026-11-24) | Medium |
| [Vancouver ortho](https://opendata.vancouver.ca/explore/dataset/orthophoto-imagery-2022) | 7.5 cm; City/UBC/UEL/parts Richmond/YVR | OGL – Vancouver | Free (list; accessed 2026-11-24) | Medium |
| [Richmond LiDAR](https://open-data-portal-metrovancouver.hub.arcgis.com/content/e8f531b04e7d432b8deff7e825c657d0) | 2022, QL3, ~16.29 GB; density not stated | OGL – MV | Free (list; accessed 2026-11-24) | Medium |
| [Richmond ortho 2025](https://open-data-portal-metrovancouver.hub.arcgis.com/datasets/metrovancouver::richmond-area-area-ortho-imagery-2025) | 2025; resolution not shown | OGL – MV | Free (list; accessed 2026-11-24) | Medium |
| [Vancouver ortho (partial Richmond)](https://opendata.vancouver.ca/explore/dataset/orthophoto-imagery-2022) | 2022, 7.5 cm, partial | OGL – Vancouver | Free (list; accessed 2026-11-24) | Medium |
| [Richmond city GIS + REST](https://www.richmond.ca/city-hall/strategies/sale.htm) | Billed layers; AirPhoto 2024–2026, SignShop; terms unverified | Unverified | CAD 131 first layer / CAD 70 each additional (list; price date not stated) | Low |
| [LidarBC](https://lidar.gov.bc.ca/) | Airborne, partial; completeness unverified | OGL – BC | Free (list; accessed 2026-11-24) | Medium |
| [Metro Vancouver portal](https://open-data-portal-metrovancouver.hub.arcgis.com/) | Aerial/point clouds; street-level not found | OGL – MV | Free (list; accessed 2026-11-24) | Medium |
| [TransLink API](https://developer.translink.ca/) | GTFS static/real-time; no imagery/LiDAR | TransLink terms; registration | Not priced; not capture (accessed 2026-11-24) | Not usable |
| [McElhanney](https://www.mcelhanney.com/lidar) | BC-active; 130 km Chilliwack 2022 | Contract; terms not found | Quote only (accessed 2026-11-24) | Medium |
| [GeoScan](https://www.geoscan.ca/services/lidar-services-and-mobile-mapping) | BC-active; Van/Vic/Kel offices | Contract; terms not found | Quote only (accessed 2026-11-24) | Medium |
| [Planview](https://planview.ca/lidar-mobile-mapping/) | BC-active; municipal/utility | Contract; terms not found | Quote only (accessed 2026-11-24) | Medium |
| [Convex](https://convexgeomatics.com/services/mobile-lidar-survey) | BC-active; serves BC | Contract; terms not found | Quote only (accessed 2026-11-24) | Medium |
| [Applus+](https://www.applus.com/ca/en/what-we-do/sub-service-sheet/mobile-lidar-for-reality-capture) | BC presence unverified | Contract; terms not found | Quote only (accessed 2026-11-24) | Medium |
| [Kiwa T2](https://www.kiwa.com/ca/en-ca/services/consulting-and-engineering/lidar-and-mobile-mapping) | BC presence unverified | Contract; terms not found | Quote only (accessed 2026-11-24) | Medium |
| [NavVis](https://www.navvis.com/en/pricing) | Tooling, not capture | Contract; terms not found | Personalized price (accessed 2026-11-24) | Medium |
| [Hivemapper/Bee](https://beemaps.com/bee) | Global map sales; density unverified; Bee US/PR only | Map products; price not public | US$19/month current (accessed 2026-11-25); US$589 upfront reported list, 2025-10-06 (USD; stale); data price not public | Low |
| [Mapillary](https://www.mapillary.com/legal/terms) | Global; density unverified | CC-BY-SA 4.0; ToS §12 | Free (list; accessed 2026-11-24) | Conditional |
| [Nexar](https://www.getnexar.com/fleet-solutions) | 94% US roads; 50+ countries; BC unverified | Data products; price not public | Hardware US$159.95, subscription US$14.99/month/vehicle (USD list, accessed 2026-11-25); data price not public | Low |
| [Google](https://www.google.com/help/terms_maps) | Global | Google End User Terms | Not priced; licence blocks use (accessed 2026-11-25) | Not usable |
| [Bing](https://www.microsoft.com/en-us/maps/bing-maps/product/enduserterms) | Global | Microsoft End User Terms §3(b) | Not priced; approval required (accessed 2026-11-25) | Conditional |
| [Cyclomedia](https://cdn.prod.website-files.com/69bd3518dd960ca00ae76dcc/69e0cf680bac25abc7141699_General_Terms_and_Conditions_Cyclomedia_Technology_B.V._20250301.pdf) | Coverage not stated | 2025 terms §23.2/§23.3 | Quote only (accessed 2026-11-25) | Conditional |
| [Panoramax](https://docs.panoramax.fr/federated-catalog) | Coverage not assessed; terms vary | OSM-FR CC-BY-SA 4.0; derivatives vary | Free (list; accessed 2026-11-24) | Conditional |
