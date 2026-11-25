# Capture-rig costs: a low-cost rig on the operator's own car, and which sensor combinations are good enough

A process note on what a low-cost road-capture rig on the operator's own car costs, and which sensor combinations are good enough for the road digital twin. Prices are list or observed retail, converted at one CAD (Canadian dollars) rate, with tax, duty and shipping excluded unless stated. No procurement recommendation is made and no pass/fail threshold is set in v1. Every fact carries an inline source and access date; every price carries currency, type and date. Sources are vendor pages, government sites, standards bodies and the repo's own research notes.

## 1. Full rig: bill of materials (low / middle / high)

### 1.1 Low: measured twin, minimal (under CAD 4,000)

| Item | Model / spec | Price (CAD) | Price basis and date | Source (URL, accessed) |
|---|---|---|---|---|
| Camera | Insta360 X5 360° camera, Standard Bundle | 589.00 | Retail sale (Black Friday), sale ends 2026-12-03 | https://www.visions.ca/insta360-x5-360-action-camera-cinsaaha-x501 , accessed 2026-11-24 |
| LiDAR (light detection and ranging) | Livox Mid-360 (905 nm, 200 kpts/s, 360°×59°, 40 m @10%, 70 m @80%, built-in IMU (inertial measurement unit) ICM-40609, PTP (Precision Time Protocol) v2/GPS sync) | 1,406.73 | USD 979 vendor official price, published 2026-03-11; observed retailer prices USD 1,263-1,406; not a Canadian retail quote | https://www.livoxtech.com/showcase/22 , accessed 2026-11-24 |
| GNSS (global navigation satellite system) | Emlid Reach M2 multi-band RTK (real-time kinematic) module | 1,076.24 | Vendor list, 2026-11-24 | https://store.emlid.com/collections/all , accessed 2026-11-24 |
| GNSS antenna | Emlid multi-band helical antenna | not priced | Searched the Emlid store collection; no primary Emlid store stock-keeping unit verified in this pass | https://store.emlid.com/collections/all , accessed 2026-11-24 |
| Time sync | Software timestamps (NTP) + Livox PTPv2; no extra hardware (GPS time via M2 PPS (pulse per second)) | 0 | n/a, no extra hardware | https://www.usrobotstore.com/products/livox-mid-360-lidar , accessed 2026-11-24 |
| Logger | Operator's existing laptop | 0 | Assumption: reused | n/a |
| Storage | 1 TB NVMe SSD (added to laptop) | 114.95 | Labelled estimate, typical retail, 2026-11-24 | labelled estimate, no vendor quote |
| Power | 12 V fused splitter + 12 V to USB-C PD car adapter (65 W) | 57.48 | Labelled estimate, typical retail, 2026-11-24 | labelled estimate, no vendor quote |
| Mounts | Suction-cup LiDAR base + camera suction mount + safety tether | 86.21 | Labelled estimate, typical retail, 2026-11-24 | labelled estimate, no vendor quote |
| **Total** | excl. tax, duty, shipping | **3,331 + antenna (lower bound)** | sum of rows at 1.4369, checked 2026-11-24 | see 1.4 |

If a primary Emlid store SKU for the helical antenna is found, add its verified price; until then the low total is 3,331 + antenna (lower bound).

The low rig assumes the operator already has a laptop and a car; if no laptop is available, add a Jetson Orin Nano Super Developer Kit at USD 399, CAD 573.32 (NVIDIA, https://developer.nvidia.com/embedded/faq , accessed 2026-11-24), giving roughly CAD 4,262.

### 1.2 Middle: balanced first build (about CAD 12,000)

| Item | Model / spec | Price (CAD) | Price basis and date | Source (URL, accessed) |
|---|---|---|---|---|
| Cameras | 2× Insta360 X5, Standard Bundle | 1,178.00 | Retail sale, ends 2026-12-03 | https://www.visions.ca/insta360-x5-360-action-camera-cinsaaha-x501 , accessed 2026-11-24 |
| LiDAR | Hesai XT32 (32 ch, 120 m, 640 kpts/s, 360°×31°, ±1 cm, zero blind spot) | 5,385.50 | Retail listing, 2026-08 | https://lidarseek.com/product/hesai-xt32 , accessed 2026-11-24 |
| GNSS | Emlid Reach RS2+ multi-band RTK receiver (184 ch, 7 mm+1 ppm RTK, built-in LTE modem, LoRa radio, 22 h battery) | 3,878.19 | Vendor list, 2026-11-24 | https://store.emlid.com/products/reach-rs2-plus , accessed 2026-11-24 |
| Time sync | PTPv2 from Hesai (Ethernet) + GNSS PPS into logger; no extra hardware | 0 | Vendor spec, no extra hardware | https://store.kartaview.org/products/hesai-xt32 , accessed 2026-11-24 |
| Logger | Jetson Orin Nano Super Developer Kit (8 GB, 67 TOPS) | 573.32 | Vendor list (post July-2026 price rise) | https://developer.nvidia.com/embedded/faq , accessed 2026-11-24 |
| Storage | 2 TB NVMe SSD | 215.53 | Labelled estimate, typical retail, 2026-11-24 | labelled estimate, no vendor quote |
| Power | 12 V to 19 V DC-DC (150 W) + fused distribution block + cabling | 172.43 | Labelled estimate, typical retail, 2026-11-24 | labelled estimate, no vendor quote |
| Mounts | Roof rack + LiDAR plate + camera mounts + safety tethers | 359.23 | Labelled estimate, typical retail, 2026-11-24 | labelled estimate, no vendor quote |
| **Total** | excl. tax, duty, shipping | **11,762** | sum of rows at 1.4369, checked 2026-11-24 | see 1.4 |

### 1.3 High: survey-grade-ish on the operator's own car (about CAD 18,000-21,000)

| Item | Model / spec | Price (CAD) | Price basis and date | Source (URL, accessed) |
|---|---|---|---|---|
| Cameras | 6× action cameras (Insta360 Ace Pro 2 or GoPro) for full surround | 3,362.26 | Vendor list (Ace Pro 2, store shows USD 389.99) | https://store.insta360.com/consumer , accessed 2026-11-24 |
| LiDAR option A (new): Hesai XT32 | Hesai XT32 (32 ch, 120 m, 640 kpts/s, 360°×31°, ±1 cm, zero blind spot) | 5,385.50 | Retail listing, 2026-08 (USD 3,748) | https://lidarseek.com/product/hesai-xt32 , accessed 2026-11-24 |
| LiDAR option B (used): Ouster OS1-128 | Used Ouster OS1-128-U (128 ch, 120 m, 2.62 Mpts/s) | 2,514.58 | eBay listing (used, "fully operational"); new listing USD 11,785 | https://www.ebay.com/itm/356384649975 , accessed 2026-11-24 |
| GNSS | Emlid Reach RS4 all-band RTK receiver (tilt compensation) | 5,602.47 | Vendor list, 2026-11-24 | https://store.emlid.com/collections/all , accessed 2026-11-24 |
| Time sync | Hardware PPS from GNSS into logger + camera GPIO trigger board (e.g., Arduino/Teensy) | 114.95 | Labelled estimate, typical retail, 2026-11-24 | labelled estimate, no vendor quote |
| Logger | Jetson AGX Orin Developer Kit (64 GB) | 5,027.71 | Vendor list (post July-2026 price rise) | https://developer.nvidia.com/embedded/faq , accessed 2026-11-24 |
| Storage | 4 TB NVMe SSD | 431.07 | Labelled estimate, typical retail, 2026-11-24 | labelled estimate, no vendor quote |
| Power | 12 V marine-grade DC distribution, 200 W, fusing, cabling | 431.07 | Labelled estimate, typical retail, 2026-11-24 | labelled estimate, no vendor quote |
| Mounts | Roof rack + machined aluminium LiDAR plate + 6 camera mounts + safety tethers | 718.45 | Labelled estimate, typical retail, 2026-11-24 | labelled estimate, no vendor quote |
| **Total (new LiDAR)** | excl. tax, duty, shipping | **21,073** | sum of rows at 1.4369, checked 2026-11-24 | see 1.4 |
| **Total (used LiDAR)** | excl. tax, duty, shipping | **18,203** | sum of rows at 1.4369, checked 2026-11-24 | see 1.4 |

Ouster OS1 spec for the used alternative: 128 beams, 120 m range, 2.62 Mpts/s, 360°×45°, ±3 cm at 20 m, 5 mm precision (Ouster datasheet referenced in the eBay listing https://www.ebay.com/itm/356384649975 , accessed 2026-11-24; listing states "Ouster OS1-128 Lidar Sensor brand new" USD 11,785; used listing USD 1,750 "fully operational").

### 1.4 Notes: laptop, conversion, time sync, GNSS and INS

Currency conversion uses one rate: Bank of Canada daily average USD/CAD = 1.4369, observation date 2026-11-23 (nearest business day to 2026-11-24), source https://www.bankofcanada.ca/valet/observations/FXUSDCAD/json?recent=5 , accessed 2026-11-24. All CAD figures are USD price times 1.4369 unless a CAD retail price is quoted directly. Taxes, duty, shipping and cables beyond those listed are excluded unless stated. All sources were accessed on 2026-11-24.

Mounts, power, storage and sync-hardware costs are labelled estimates, not vendor quotes; no quote requests were made. The low rig reuses the operator's laptop and car; the Jetson Orin Nano Super Developer Kit at USD 399 (CAD 573.32) replaces the laptop if none is available.

Time sync per tier: low tier uses software timestamps (NTP) plus Livox PTPv2 with GPS time via M2 PPS, no extra hardware; middle tier uses PTPv2 from the Hesai over Ethernet plus GNSS PPS into the logger, no extra hardware; high tier uses hardware PPS from GNSS into the logger plus a camera GPIO trigger board (labelled estimate, CAD 114.95). Multi-camera synchronisation for 4-6 action cameras is not priced (no hardware trigger or multi-cam sync box included in the low or middle estimates). Wherever sync hardware is not priced, the note says not priced rather than inventing a figure.

GNSS and INS: all three builds use RTK GNSS receivers (Emlid Reach M2, RS2+, RS4). The Livox Mid-360 and the Reach RS4 include inertial measurement units but neither is a navigation-grade inertial navigation system. v1's align stage uses KISS-ICP, LiDAR-only odometry carrying relative z, pitch and roll, not absolute height (docs/research/kiss-icp-fit.md:9-13). A true GNSS/INS (VectorNav VN-300, Septentrio AsteRx SBi3, u-blox ZED-F9R as examples) is a High-tier upgrade, price not verified in this pass.

No claim is made that the receivers lack inertial measurement units, and KISS-ICP is not mislabelled as inertial-aided odometry.

The receiver line-up is listed at https://store.emlid.com/collections/all , accessed 2026-11-24; the Mid-360 specification is at https://www.usrobotstore.com/products/livox-mid-360-lidar , accessed 2026-11-24; KISS-ICP's limits are at docs/research/kiss-icp-fit.md:9-13.

## 2. Variants and what each loses

Yardstick from the twin (v1 spec, docs/design/twin-v1-spec.md:51,98,180,321,367): 3D lane markings and crosswalks extracted from LiDAR; curb lines from height steps; 5 cm orthoimage plus RGB points from the six cameras (colour stage); ground surface with height_valid flag; plan accuracy P50/P95 vs HD map; ISD per leg. No pass/fail threshold is set in v1. Reconstruction pass bar from map #415: road-surface depth error against held-out LiDAR <= 5 cm p95.

| Variant | Metric scale | Height accuracy | Colour / 5 cm orthoimage | Sign reading | Coverage / density |
|---|---|---|---|---|---|
| Cameras only (surround camera + phone GPS or RTK GNSS) | No metric scale from cameras alone. Monocular structure-from-motion gives scale only up to an unknown factor unless a known baseline or GNSS is used; with RTK GNSS, scale is anchored by the trajectory. (published on another rig (RoMe, EMIE-MAP, Urban Radiance Fields)) | Poor/unknown. EMIE-MAP reports elevation error with and without LiDAR supervision; KITTI and Urban Radiance Fields report depth error. No number published for a surround camera on a car. (published on another rig (EMIE-MAP, Urban Radiance Fields)) | Possible (cameras are the colour authority per ADR 0006 Q1) but no depth for occlusion; depth must come from structure-from-motion, which is sparse on roads. (published on another rig (RoMe)) | Good in principle (cameras see signs), but no published sign-reading accuracy for this rig; signs are out of v1 scope anyway. (not measured on this rig) | Very sparse on flat road (few features); depends on texture. (not measured on this rig) |
| LiDAR only on the roof | Full metric scale from LiDAR (time-of-flight). (not measured on this rig) | Good relative consistency; height_valid from sweep agreement. Absolute height not recovered (KISS-ICP keeps relative z; spec section 6 Align). Survey-grade scanners claim cm-level absolute accuracy with a base station and DMI (distance measurement instrument); not this rig. (not measured on this rig; published on another rig (survey-grade scanners)) | None. No colour stage possible; orthoimage not produced. Points have intensity only. (not measured on this rig) | None. LiDAR intensity does not read text. (not measured on this rig) | High density at road surface near nadir; Livox Mid-360 and Hesai XT32 publish point rates and blind zones. (published on another rig (Livox, Hesai specs)) |
| One roof LiDAR + cameras at car corners | Full metric scale (LiDAR authority, ADR 0006 Q1). (not measured on this rig) | Same as LiDAR only plus camera poses refined against LiDAR edges; colour QA measures edge offset. Refinement improved P50 more than P95 on the nuScenes Boston drive (ADR 0007 D12). (measured on the twin's nuScenes Boston drive) | Full colour stage possible: centimetre-class orthoimage plus RGB points, with unobserved cells left transparent. Edge offset P50/P95 reported in colour/qa.json. (measured on the twin's nuScenes Boston drive) | Signs visible in images; can be projected onto LiDAR geometry, but no published accuracy for sign inventory on this rig (signs are v1.1 non-goal). (not measured on this rig) | LiDAR density as LiDAR only plus camera texture; cameras fill appearance gaps. (not measured on this rig) |

Camera-only numbers come from RoMe (arXiv 2306.11368, https://arxiv.org/abs/2306.11368 , accessed 2026-11-24), EMIE-MAP (arXiv 2403.11789, https://arxiv.org/abs/2403.11789 , accessed 2026-11-24) and Urban Radiance Fields (arXiv 2111.14643, https://arxiv.org/abs/2111.14643 , accessed 2026-11-24). The P50 0.043 to 0.027 m and P95 0.132 to 0.123 m figures are measured on the nuScenes Boston drive 20261115-183953-1017f9, labelled as measured on that drive, not on this rig. The roughly 5,700 pts/m² figure is derived (pts/s divided by speed times swath), not vendor-published for a road surface. No Leica/RIEGL 1-3 cm number is used without a vendor datasheet URL; the qualitative sentence carries a source or no number.

What each variant loses, in one line:
- Cameras only: loses metric scale, height accuracy and the 5 cm orthoimage's geometry; gains appearance and signs. Not usable for the twin's stated error without LiDAR supervision.
- LiDAR only: loses colour and sign reading entirely; keeps geometry and scale.
- One roof LiDAR plus corner cameras: loses nothing structural; cost and complexity are the price, and colour edge accuracy is limited by LiDAR ground-height error and ego-pose inconsistency (ADR 0007 D12), not camera pose.

Capture density and practical facts: Livox Mid-360 200,000 pts/s, 10 Hz frame, 0.1 m blind zone, 40 m at 10% / 70 m at 80% reflectivity; points per m² at 10 m/s (36 km/h) is about 5,700 per pass in the swath, in practice far lower at road centre due to grazing angle and the 59° vertical FoV (https://www.usrobotstore.com/products/livox-mid-360-lidar , accessed 2026-11-24). Hesai XT32 640,000 pts/s single return, 32 ch, 120 m, ±1 cm, zero blind spot (0.05 m min), about 3 times the Mid-360 density (https://lidarseek.com/product/hesai-xt32 , accessed 2026-11-24). Ouster OS1-128 2.62 Mpts/s, 128 beams, highest density of the three; new price USD 11,785 (eBay listing) is too costly new; used listings USD 1,750-2,633 (https://www.ebay.com/itm/356384649975 , accessed 2026-11-24).

Minimum useful range for a road surface: Livox 0.1 m blind zone means curb-adjacent points are captured; Ouster/Hesai zero blind spot (0.05 m) is better for curb faces. Ground points closer than 1 m are dropped by the devkit multisweep loader (min_distance 1.0 m), relevant if reusing nuScenes-style loading (docs/research/kiss-icp-fit.md:48). Twin v1 keeps each drive separate and shows the best-covered drive per facility; fusion is v1.1 (docs/design/twin-v1-spec.md:42,135).

Multiple passes fill gaps (covered_by grows) and move elements from observed to confirmed (decision 0004 section 3). Height QA compares sweeps; more passes improve height_valid confidence but do not create absolute height (spec R1: no independent height reference). Motion blur is <= 9 cm (avg) / <= 20 cm (worst) at 4.4 m/s with 20 ms exposure; pitch error grows with range squared (docs/research/camera-ground-projection.md). Hence max_range_m 12 m default and nearest-first ranking.

## 3. NTRIP (Networked Transport of RTCM via Internet Protocol) and RTK in Metro Vancouver

### 3.1 Free live corrections

BC Active Control System (BCACS): 20 (or 21 per the Canadian Geodetic Reference System Committee) permanent GNSS stations across BC; BCACS base stations provide data to allow users to correct coordinates from single receivers, making positions accurate to less than 1 metre (https://www2.gov.bc.ca/gov/content/data/geographic-data-services/geo-spatial-referencing/bcacs , last updated 2026-06-09, accessed 2026-11-24). Post-mission (RINEX) data is available by subscription or on a pay-per-download basis through GeoBC; access requires a BCeID (same source, accessed 2026-11-24). Access to the BCACS system post-mission data is provided through FTP download. No free live NTRIP caster is offered by BCACS (https://www2.gov.bc.ca/gov/content/data/geographic-data-services/geo-spatial-referencing/bcacs , last updated 2026-06-09, accessed 2026-11-24).

Metro Vancouver GNSS (MVRD RTN (real-time network)): real-time network available through annual or monthly subscriptions; One-Year Subscription CAD 3,300 inclusive of GST/PST; One-Month Subscription CAD 340 per month inclusive of GST/PST (other subscribers; local government users billed under Bylaw No. 1226, 2015) (https://metrovancouver.org/about-us/Documents/global-navigation-satellite-system-subscription-agreement.pdf , accessed 2026-11-24). The Data Service is available within the boundaries of Metro Vancouver (same source, accessed 2026-11-24). Non-exclusive, non-transferable, revocable, single concurrent user per licence (https://metrovancouver.org/about-us/Documents/global-navigation-satellite-system-subscription-agreement.pdf , accessed 2026-11-24).

CRD RTN: real-time GNSS service over the Capital Regional District; access is by subscription (CRD) (https://cgrsc.ca/resources/geodetic-control-networks/provincial-networks/ , accessed 2026-11-24). Federal: NRCan lists real-time networks as private GNSS reference networks that have signed a compliance agreement with NRCan; the free federal option is CSRS-PPP (post-processing only). NRCan operates CACS stations but no free public real-time NTRIP caster is published for Metro Vancouver (https://scansupply.net/guides/rtk-correction-subscription-cost/ , accessed 2026-11-24).

Community casters: RTK2go (free global community NTRIP caster). BC free stations listed by KUON GEO: 5 stations, including RichmondBC (community base listed by KUON GEO) (rtk2go.com, RTCM 3.2 MSM4, GPS+GLO+GAL+BDS). Other BC stations are in North Cowichan, Dawson Creek and Revelstoke; none nearer to Coquitlam/Surrey/Vancouver/Richmond than RichmondBC (https://kuongeo.com/stations/region/CAN-british-columbia , accessed 2026-11-24). IGS free global service and Earthscope (non-commercial) are available but low station density; RTK only works up to 35-50 km baseline (https://www.ardusimple.com/rtk-correction-services-and-ntrip-casters-in-canada/ , accessed 2026-11-24).

### 3.2 Paid services

| Service | Kind | Coverage | Price (CAD) | Price basis and date | Source (URL, accessed) |
|---|---|---|---|---|---|
| Metro Vancouver RTN | Live RTK subscription | Within Metro Vancouver; the four target cities require the coverage map, not read in this pass | 340/month | List price, CAD inclusive of GST/PST, 2026-11-24 | https://metrovancouver.org/about-us/Documents/global-navigation-satellite-system-subscription-agreement.pdf , accessed 2026-11-24 |
| RTKdata | Live RTK subscription | Canada (NAD83(CSRS)); Canadian coverage thins out above roughly 55 degrees north | 57/month (575/year) | List price, USD 40/month or USD 400/year converted at 1.4369 | https://rtkdata.com/ca/ , accessed 2026-11-24 |
| Swift Navigation Skylark | Live RTK (Nx RTK) | Canada listed as covered country; site must be confirmed on Skylark's coverage map (not read in this pass) | 99/month (1,004/year) | List price, USD 69/month or USD 699/year converted at 1.4369 | https://www.swiftnav.com/products/skylark/nx-rtk , accessed 2026-11-24 |
| Can-Net (Trimble) | Live RTK subscription | 300+ stations Canada; Metro Vancouver covered (network) | quote only (about 200/month, 2,000-2,400/year) | Dealer quote, not a published list price | https://www.can-net.ca/ , accessed 2026-11-24 |
| HxGN SmartNet (Leica) | Live RTK subscription | 150+ stations; 8 Canadian provinces incl. BC | quote only (about 3,449/year) | Example US state-level, converted; dealer quote | https://hxgnsmartnet.com/how-to-buy , accessed 2026-11-24 |
| Trimble RTX (CenterPoint) | PPP (satellite/IP) | Global including Canada; 2 cm H, convergence <1 min FAST / <3 min | quote only (about 2,263/year) | Dealer listing, converted | https://positioningservices.trimble.com/en/products/rtx , accessed 2026-11-24 |
| Point One (Polaris) | True RTK / Virtual RTK (SSR, 3-7 cm) | True RTK: listed regions US, UK, EU, KOR, AUS, NZ, JP; not Canada. Virtual RTK: US contiguous only; not Canada | 122/month (1,078/year) True RTK; 57/month (503/year) Virtual RTK | List price, USD, converted at 1.4369; not a live-RTK option for Metro Vancouver | https://pointonenav.com/pricing/ , accessed 2026-11-24 |
| u-blox PointPerfect Flex | PPP-RTK (SPARTN/RTCM over NTRIP) | Canada partially covered | 22/month | List price, USD 15/month (SparkFun rate) converted at 1.4369 | https://support.thingstream.io/hc/en-gb/articles/7862862342300-Does-PointPerfect-Flex-cover-my-region-Is-there-a-coverage-map , accessed 2026-11-24 |
| Topcon TopNET Live | Live RTK subscription | Canada (via Brandt/GeoShack) | not published (quote) | Quote only; no published rate | https://geoshack.com/rent-plus-equipment-rental/ , accessed 2026-11-24 |

Point One explicitly does not list Canada as a True RTK region, so it is not a live-RTK option for Metro Vancouver (https://pointonenav.com/pricing/ , accessed 2026-11-24). Metro Vancouver's own RTN is a real-time service covering the region at CAD 340/month for other subscribers (https://metrovancouver.org/about-us/Documents/global-navigation-satellite-system-subscription-agreement.pdf , accessed 2026-11-24).

### 3.3 Post-processing (PPP, precise point positioning)

NRCan CSRS (Canadian Spatial Reference System)-PPP: free. Static and kinematic modes; NAD83(CSRS) or ITRF. Accuracy by product line: Ultra-rapid about 15 cm (GPS+GLONASS, available about 90 min after hour); Rapid about 5 cm (GPS+GLONASS+Galileo, 17-18 h after day); Final about 2 cm (12-15 days after week). NRCan states up to millimetre-level accuracies for long observation sessions (24+ hours) in static mode, but an accuracy of a few centimetres can typically be achieved in an hour (https://docs.emlid.com/reachrs/tutorials/post-processing-workflow/nrcan-workflow/ , accessed 2026-11-24; https://webapp.csrs-scrs.nrcan-rncan.gc.ca/geod/tools-outils/ppp-info.php , accessed 2026-11-24; https://webapp.csrs-scrs.nrcan-rncan.gc.ca/geod/tools-outils/sample_doc_files/NRCan_CSRS-PPP-v3_Tutorial_EN.pdf , accessed 2026-11-24).

CSRS-PPP v5 (from 2025-05-14) adds Galileo PPP-AR for E1/E5a data collected from 2022-11-27; improved accuracies, especially for shorter datasets (up to 40-60% for sessions up to 1 hour) (https://webapp.csrs-scrs.nrcan-rncan.gc.ca/geod/tools-outils/ppp-info.php , accessed 2026-11-24). BCACS post-mission RINEX data: hourly files, province-wide, accurate to less than 1 metre for single-receiver correction; available by subscription or pay-per-download (https://www2.gov.bc.ca/gov/content/data/geographic-data-services/geo-spatial-referencing/bcacs , accessed 2026-11-24). Quebec geodetic network: free post-processing only, no real-time (https://www.ardusimple.com/rtk-correction-services-and-ntrip-casters-in-canada/ , accessed 2026-11-24).

### 3.4 Own base station

A minimal base requires a multi-band GNSS receiver, survey antenna, and either a radio link or an NTRIP caster. Practical range: RTK works up to 35-50 km baseline from the base; accuracy degrades with distance (https://www.ardusimple.com/rtk-correction-services-and-ntrip-casters-in-canada/ , accessed 2026-11-24).

A nearby free base (RichmondBC on RTK2go) is the only Lower Mainland option; the nearest other BC RTK2go station is in North Cowichan (https://kuongeo.com/stations/region/CAN-british-columbia , accessed 2026-11-24).

A second receiver for an own base is not priced in this pass; a local base is preferable because accuracy degrades with distance over the 35-50 km baseline.

### 3.5 Answer: is a paid subscription needed?

No, not for a 2-5 cm road twin, if the work can be post-processed. Free CSRS-PPP (Rapid/Final products) delivers about 5 cm / about 2 cm after 17-18 h / 12-15 days, which meets 2-5 cm provided each drive is logged to RINEX and post-processed (https://webapp.csrs-scrs.nrcan-rncan.gc.ca/geod/tools-outils/ppp-info.php , accessed 2026-11-24; https://docs.emlid.com/reachrs/tutorials/post-processing-workflow/nrcan-workflow/ , accessed 2026-11-24). Live RTK is needed only for real-time stakeout or same-day turnaround; for capture drives, logging raw GNSS and post-processing avoids a subscription entirely.

If same-day or live positioning is required, the cheapest credible live option is RTKdata at about CAD 57/month or Metro Vancouver's RTN at CAD 340/month for the region. A single nearby free base (RichmondBC on RTK2go) can deliver live cm-level corrections for drives near that point, but its uptime and quality are community-maintained and it is not a survey-grade service (https://www.ardusimple.com/rtk-correction-services-and-ntrip-casters-in-canada/ , https://kuongeo.com/stations/region/CAN-british-columbia , https://webapp.csrs-scrs.nrcan-rncan.gc.ca/geod/tools-outils/ppp-info.php , https://metrovancouver.org/about-us/Documents/global-navigation-satellite-system-subscription-agreement.pdf , accessed 2026-11-24).

## 4. Buy, return or rent in BC and Canada

### 4.1 Retailer return windows and restocking fees

| Retailer | Return window | Restocking fee on opened gear | Conditions as stated | Source (URL, accessed) |
|---|---|---|---|---|
| Best Buy Canada | 30 days from in-store purchase or online delivery (15 days for carrier-plan cellular) | 15% restocking fee on opened action cameras, camcorders, DSLR/mirrorless, point-and-shoot, camera drones, lenses/flashes, projectors | Like-new, original packaging | https://www.bestbuy.ca/en-ca/help/returns-and-exchanges/best-buy-return-and-exchange-policies , accessed 2026-11-24 |
| Amazon.ca | 30 days of delivery (15 days Apple brand new; 7/90/180/365 exceptions) | No general restocking fee; 100% on opened software/video games and opened collectibles; damage fee up to 50% | Original/unused condition | https://www.amazon.ca/gp/help/customer/display.html?nodeId=GKM69DUUYKQWKWX7 , accessed 2026-11-24 |
| Vistek | 14 days | 10% minimum (up to 15% at Vistek's discretion) on opened/used items; DJI 10% if opened but unregistered; many items final sale (hard drives, headphones, software, etc.) | As-new unopened | https://www.vistek.ca/about/returns , accessed 2026-11-24 |

Retailer policies for Henry's, London Drugs, Memory Express, Canada Computers, B&H and Adorama (Canada shipping) were not read in this pass and are marked not verified.

### 4.2 Rental

| Provider | What you can rent | Day rate (CAD) | Week rate (CAD) | Minimum term | Price basis and date | Source (URL, accessed) |
|---|---|---|---|---|---|---|
| Vistek | Insta360 X5 bundle | 80 first day, 60 additional day, 80 weekend | 240 | none stated | List price, CAD, 2026-11-24 | https://www.vistek.ca/rentals/details/101465-C/insta360-x5-camera-bundle , accessed 2026-11-24 |
| Gearbase Camera Rentals (Vancouver, BC) | Insta360 X5 | 75 | not listed | none stated | List price, CAD, 2026-11-24 | https://camerarentalsvancouver.com/ , accessed 2026-11-24 |
| Cansel | Trimble Network Rover GPS bundle | 182.14 | not listed | 3 days | List price, CAD, 2026-11-24 | https://www.cansel.ca/rental-leasing/equipment-rental-packages , accessed 2026-11-24 |
| Cansel | Trimble X9 scanner bundle | 328.57 | not listed | 3 days | List price, CAD, 2026-11-24 | https://www.cansel.ca/rental-leasing/equipment-rental-packages , accessed 2026-11-24 |
| Cansel | Trimble Base and Rover RTK system | 328.57 | not listed | none stated | List price, CAD, 2026-11-24 | https://www.cansel.ca/rental-leasing/equipment-rental-packages , accessed 2026-11-24 |

Vistek rental locations: Calgary, Edmonton, Mississauga, Ottawa, Toronto; no Vancouver store listed. No deposit for account holders; deposit otherwise (https://www.vistek.ca/rentals/policies , accessed 2026-11-24). Leo's Camera Supply (Vancouver) is listed on Yelp as closed as of October 2026; rental list historical only (https://www.yelp.ca/biz/leos-camera-supply-vancouver , accessed 2026-11-24).

Beau Photo, The Camera Store (Calgary), Benchmark Instruments, Frontier Precision and Leica dealers were not sourced in this pass. Cansel also lists Spectra base and rover RTK at 182.14/day and FARO scanner package at 328.57/day (7-day minimum); Rental Protection Plan +10% of daily rate (https://www.cansel.ca/rental-leasing/equipment-rental-packages , accessed 2026-11-24).

GeoShack (Topcon dealer) rentals are quote-based; no published day rate; Rent+ is a 2-year lease, not short-term daily rental (https://geoshack.com/rent-plus-equipment-rental/ , accessed 2026-11-24). Trimble MX90 mobile mapping system is listed by Cansel as a rental package but no day rate published; quote only (https://www.cansel.ca/rental-leasing/equipment-rental-packages , accessed 2026-11-24).

### 4.3 Used market

Used Ouster/Livox/Hesai and GNSS/INS units trade primarily on eBay (sold listings), plus Canadian dealers (Cansel, GeoShack/Brandt) and forums (for example r/robotics, r/surveying). No verified sold-price data was collected in this pass; label any figure from these channels as a market report with date, not a list price. Public datasets are not a purchase route; nuScenes mini is CC BY-NC-SA 4.0 (non-commercial) and is not a priced source (docs/design/twin-v1-spec.md:42).

## 5. BC legal and practical limits

### 5.1 Cargo, projection and roof height

Motor Vehicle Act Regulations (MVAR, BC Reg 26/58), s. 4.20(1): a vehicle on a highway must not carry a load or have an integral part of the vehicle which projects more than 1 m beyond the front wheels or the front bumper of the vehicle unless, during the time specified in section 4.01, the extreme tip of the projection is illuminated with a lamp capable of displaying only white light visible from the front and sides of the vehicle, and at any time other than that specified in section 4.01, a red flag or cloth is attached to the extreme tip of the projection. s. 4.20(2): rear projection beyond 1.2 m requires a red lamp/flag (https://www.bclaws.gov.bc.ca/civix/document/id/complete/statreg/26_58_01 , accessed 2026-11-24).

MVAR s. 19.02(3)(b): no person shall drive a vehicle or combination of vehicles so loaded that the load extends more than 1 m beyond the front wheels thereof, or, if equipped with a front bumper, more than 1 m beyond the front bumper, without a permit. s. 19.02(3)(c)-(e): load must not extend more than 4.5 m behind the centre of the last axle, more than 185 cm beyond the back of the vehicle, or beyond the sides of the vehicle (https://www.bclaws.gov.bc.ca/civix/document/id/complete/statreg/26_58_06 , accessed 2026-11-24).

MVAR s. 35.04: vehicles must be equipped and cargo must be contained, immobilized or secured so that it cannot leak, spill, blow off, fall from, fall through or otherwise be dislodged from the vehicle, or shift on or within the vehicle in a manner that affects the stability or manoeuvrability of the vehicle (https://www.bclaws.gov.bc.ca/civix/document/id/complete/statreg/26_58_11 , accessed 2026-11-24).

MVAR s. 35.03(4): a person must not drive or operate on a highway a vehicle, other than a commercial vehicle or business vehicle, carrying cargo if the manner in which the vehicle is equipped or its cargo secured contravenes any of sections 35.04 to 35.07 (https://www.bclaws.gov.bc.ca/civix/document/id/complete/statreg/26_58_11 , accessed 2026-11-24). MVAR s. 35.09(3)(a)-(d): a vehicle must not be loaded so as to obscure the driver's view ahead or to the right or left side, interfere with the free movement of the driver's arms or legs, obstruct access to emergency equipment, or interfere with the safe operation of the vehicle in any other manner (https://www.bclaws.gov.bc.ca/civix/document/id/complete/statreg/26_58_11 , accessed 2026-11-24).

Commercial Transport Regulations (BC Reg 30/78), s. 7.05(1): a person must not, without a permit, drive or operate a vehicle having a height in excess of 4.15 m (https://www.bclaws.gov.bc.ca/civix/document/id/crbc/crbc/30_78 , accessed 2026-11-24). s. 7.05(0.1): height measured from the highest point of the vehicle, including its load, to the road surface directly below that point. 

DriveSmartBC confirms vehicle height includes all permanently or temporarily attached cargo and accessories, so roof-mounted gear counts toward the 4.15 m limit (https://www.bclaws.gov.bc.ca/civix/document/id/crbc/crbc/30_78 and https://www.drivesmartbc.ca/bc-vehicle-dimensions-regulations , accessed 2026-11-24).

National Safety Code Standard 10 (Cargo Securement) is adopted into the MVAR (s. 35.02) but only applies to a vehicle transporting cargo on a highway and exceeding a licensed gross vehicle weight of 5,000 kg. So for a passenger car, NSC 10 does not apply; the MVAR cargo rules (s. 35.03-35.09) do (https://www.bclaws.gov.bc.ca/civix/document/id/complete/statreg/26_58_11 , s. 35.02(3), accessed 2026-11-24).

MVAR s. 4.27(2)(a)-(b): an internally illuminated roof sign is securely mounted on the roof of the vehicle, has no moving parts and does not overhang the roof of the vehicle, and does not increase the overall height of the vehicle by more than 50 cm, and the vehicle and sign together do not exceed 4.15 m in overall height. An analogous height discipline for roof-mounted equipment (https://www.bclaws.gov.bc.ca/civix/document/id/complete/statreg/26_58_01 , accessed 2026-11-24).

### 5.2 Insurance

Insurance Corporation of British Columbia (ICBC) extra equipment coverage: permanently attached equipment is covered up to CAD 5,000 under Autoplan; sound and communication equipment that is permanently attached or attached by shuttle mount up to CAD 1,000; a rack carrier that is not permanently attached up to CAD 1,000 for one only. Equipment must be permanently attached to the vehicle, or shuttle-mounted and communication equipment; excluded items include equipment, features or modifications that would not be approved by MVA Regulations, Canadian Motor Vehicle Safety Standards, or Transport Canada (https://legearpelling.com/icbc-doc-extra-equipment/ quoting the ICBC Autoplan Extra Equipment procedure, and https://mdp.partners.icbc.com/topic/d647b944-618b-4ca9-b922-9eab80f70069 , accessed 2026-11-24).

ICBC equipment theft: coverage applies to permanently attached equipment (for example stereo, speakers, snow tires) under Comprehensive/Specified Perils; if the stolen equipment was not permanently attached (fixed to the vehicle) it may not be covered. Receipts/photos required (https://icbc.com/claims/repair-replace/auto-equipment-theft , accessed 2026-11-24).

Practical implication for a capture rig: a suction/magnetic-mounted LiDAR or camera that is removable without tools is not permanently attached and is at risk of not being covered; permanently bolted/racked gear falls under the CAD 5,000 other permanently attached equipment limit, and a claim requires receipts. This is an inference from the ICBC wording above; no ICBC page specifically addresses roof-mounted capture rigs (same ICBC pages, accessed 2026-11-24).

### 5.3 Other practical limits

Bridge/garage clearance: the 4.15 m height limit above (Commercial Transport Regs s. 7.05) is the relevant ceiling; a posted low-clearance sign overrides it (https://www.bclaws.gov.bc.ca/civix/document/id/crbc/crbc/30_78 and https://www.bclaws.gov.bc.ca/civix/document/id/complete/statreg/26_58_11 , accessed 2026-11-24).

Suction/magnetic mount limits, rain/temperature/vibration operating limits: not sourced in this pass; omitted.

### 5.4 Privacy (out of scope)

Privacy law (PIPA and FOIPPA) is out of scope here; ticket #478 covers it.

## Closing table: option, total cost range (CAD), good enough for

v1 sets no pass/fail threshold; each range is a sum or spread of the prices cited in the Option cell's section at 1.4369, all checked 2026-11-24; derived rows show their arithmetic.

| Option | Total cost range (CAD) | Good enough for |
|---|---|---|
| Cameras only | 1,924 + antenna (lower bound) (derived: 3,330.61 − 1,406.73 = 1,923.88, rounded; mount bundle retained, upper bound; laptop reused) | appearance, colour and signs only |
| LiDAR only | 2,742 + antenna (lower bound) (derived: 3,330.61 − 589.00 = 2,741.61, rounded) | scale, height and geometry, no colour or sign |
| Low | 3,331 + antenna (lower bound) | measured twin, relative height only, colour optional |
| Middle | 11,762 | adds the colour stage |
| High | 18,203–21,073 (derived: 21,073 new LiDAR; 18,203 = 21,073 minus 5,385.50 XT32 plus 2,514.58 used Ouster) | six-camera surround and 120 m LiDAR, still relative height, no true INS |

The 5 cm road-surface depth bar is map #415's (<=5 cm p95 against held-out LiDAR), not a v1 criterion.
