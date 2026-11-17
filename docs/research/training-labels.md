# Training labels for a surface-feature model (research only)

Research note for issue #295 (part of #293). Question: which labelled data can train a surface-feature model for the showcase area without touching the audit set. No code change.

Date of survey: 2026-11-17. Showcase area (boston-seaport, EPSG:32619, x 332112-332668, y 4689895-4690292) must be **held out of any training patch**.

## 1. nuScenes map expansion (counted on the box, /data/nuscenes, v1.0-trainval)

Counts are map records per location from `maps/expansion/<location>.json`. Showcase-area exclusion is not applied: nuScenes map coordinates are local metres per map, so the held-out patch must be cut at training time. Treat the boston-seaport column as an upper bound.

| Feature | boston-seaport | singapore-onenorth | singapore-hollandvillage | singapore-queenstown | Total |
|---|---|---|---|---|---|
| ped_crossing | 340 | 120 | 28 | 75 | 563 |
| lane_divider | 671 | 357 | 220 | 257 | 1505 |
| road_divider | 377 | 152 | 107 | 172 | 808 |
| stop_line | 775 | 451 | 300 | 437 | 1963 |
| walkway | 301 | 838 | 498 | 457 | 2094 |
| carpark_area | 275 | 39 | 0 | 40 | 354 |
| drivable_area (records) | 2 | 1 | 426 | 219 | 648 |
| drivable_area (polygons) | 70 | 7 | 426 | 219 | 722 |
| Scenes (scene.json via log.location) | 467 | 183 | 85 | 115 | 850 |

Notes:
- `drivable_area` records hold a list of `polygon_tokens`; Boston and one-north use few records with many polygons, Holland Village and Queenstown one polygon each. Use the polygon row for comparison.
- Non-Boston totals (training pool excluding Boston entirely): ped_crossing 223, lane_divider 834, road_divider 431, stop_line 1188, walkway 1793, carpark_area 79. Boston-seaport is the only US, right-hand-traffic map; Singapore is left-hand-traffic. Domain gap against the Boston showcase is real, so Boston patches outside the showcase box are the preferred training data and Singapore is secondary.
- Paint type exists only as a `segment_type` on lane_divider segments. Observed values: boston NIL 981, SINGLE_SOLID_WHITE 865, DOUBLE_DASHED_WHITE 509, SINGLE_SOLID_YELLOW 1 (yellow is essentially absent); Singapore adds DOUBLE_SOLID_WHITE and SINGLE_ZIGZAG_WHITE. `road_divider` carries no type.
- Licence: nuScenes Terms of Use (file `/data/nuscenes/LICENSE`, Motional, updated 2021-11-16): non-commercial use only.
- Map expansion size on the box: 47 MB (`maps/expansion`), 457 MB for `maps/`.

### What nuScenes cannot label
| Inventory element | nuScenes status |
|---|---|
| Curbs as such | No curb layer. `walkway` polygons and `drivable_area` boundaries give a proxy edge only (the walkway/road boundary is not guaranteed to be the curb face). |
| Paint types | Only lane_divider `segment_type` (white solid/dashed/double/zigzag, almost no yellow). No stop-bar, arrow, hatching, or bike-lane class. `stop_line` and `ped_crossing` are geometry-only. |
| Curb ramps | Not present. |
| Crosswalks | Yes: `ped_crossing` polygons, with `road_segment_token` link. No marking style (zebra vs ladder). |

## 2. Argoverse 2 (Sensor + map)

| Item | Finding | Source |
|---|---|---|
| Sensor dataset | 1,000 scenes, 4.2 h, about 15 s and 1 GB per log, 1 TB extracted. Cities: Miami 354, Pittsburgh 350, Washington D.C. 126, Detroit 117, Austin 31, Palo Alto 22. No compressed download size is published. | argoverse.github.io/user-guide/datasets/sensor.html |
| Download | `s5cmd --no-sign-request cp "s3://argoverse/datasets/av2/sensor/*" DIR`, no AWS account needed | argoverse.github.io/user-guide/getting_started.html |
| Map elements | Lane segments with 3D left/right boundary polylines and left/right paint marking types; pedestrian crossings (two 3D polyline edges forming a polygon); drivable area as 3D polygons (plus raster); ground-surface height raster at 0.3 m, Sensor dataset only, within 5 m of the drivable-area boundary | AV2 paper (arXiv 2301.00493, section on HD maps); `av2/map/map_api.py` |
| Paint types (`LaneMarkType`) | DASH_SOLID_YELLOW, DASH_SOLID_WHITE, DASHED_WHITE, DASHED_YELLOW, DOUBLE_SOLID_YELLOW, DOUBLE_SOLID_WHITE, DOUBLE_DASH_YELLOW, DOUBLE_DASH_WHITE, SOLID_YELLOW, SOLID_WHITE, SOLID_DASH_WHITE, SOLID_DASH_YELLOW, SOLID_BLUE, NONE, UNKNOWN. `LaneType`: VEHICLE, BIKE, BUS | `av2/map/lane_segment.py` |
| Curbs | Not annotated. The paper and map API never mention curbs; road edge is implicit in lane boundaries and drivable-area polygons. Ground-height raster could support curb-step detection but is not a label. | paper, map_api.py |
| Stop lines, walkways, ramps | Not annotated | map_api.py (no such layer) |
| Licence | Data and documentation: CC BY-NC-SA 4.0, non-commercial only, credit "(c) 2021 Argo AI, LLC". Code (av2-api): MIT. | argoverse.org/about.html |

Limit: AV2 is Miami, Pittsburgh, DC, Detroit, Austin, Palo Alto. It is the only surveyed source with rich paint types, but its marking type is attached to lane boundaries, not to painted stop bars or crosswalk styles.

## 3. OpenLane-V2

| Item | Finding | Source |
|---|---|---|
| Built on | nuScenes (subset_B) and Argoverse 2 (subset_A); user must accept both terms of use | OpenLane-V2 README |
| Map Element Bucket areas | category 1 = pedestrian crossing, category 2 = road boundary. SD map: road, cross_walk, side_walk | `data/README.md` |
| Lane segment lines | left/right lane lines with `line_type`: 0 none, 1 solid, 2 dash | `data/README.md` |
| Curbs | No curb class. `road_boundary` is the nearest thing (a drivable-area edge polyline); it is a derived boundary, not a curb face. | `data/README.md` |
| Paint types | Only none/solid/dash (colour and double lines lost) | `data/README.md` |
| Curb ramps | None | `data/README.md` |
| Download size | subset_A: images about 100 GB train, 21 GB val, 21 GB test; annotation info 8.8 GB; Map Element Bucket about 240 MB; SD Map about 7 MB. subset_B: images about 24 GB train, 5.0 GB val, 5.4 GB test; annotation info 7.7 GB. Sample about 300 MB | `data/README.md` |
| Licence | Dataset CC BY-NC-SA 4.0; code Apache 2.0 | README |

OpenLane-V2 adds no information beyond the nuScenes and AV2 maps it is derived from. Its value is a ready-made schema and a 240 MB map-only bucket for subset_A.

## 4. Recommended label source per element

| Element | Recommended source | Reason / gap |
|---|---|---|
| Marking types (paint) | AV2 `LaneMarkType` for type vocabulary and colour (solid/dashed/double, white/yellow); nuScenes `lane_divider.segment_type` on Boston for in-domain geometry | AV2 has the richest set but is not Boston. nuScenes Boston has almost no yellow. Stop bars, arrows, hatching: no source, must be hand-labelled on the showcase-adjacent area (outside the audit set). |
| Crosswalks | nuScenes `ped_crossing`, Boston first (340) then Singapore (223); AV2 pedestrian crossings as an extra US source | Polygons already exist in both. No zebra/ladder style. 340 Boston samples is enough for fine-tuning, not for from-scratch training. |
| Curbs | No public source. Derive weak labels from nuScenes `walkway` / `drivable_area` boundary edges and AV2 drivable-area polygon edges plus ground-height raster steps; hand-label a small curb set | None of nuScenes, AV2, OpenLane-V2 annotates curbs. Weak labels will be biased by polygon simplification; validate on a hand-labelled sample. |
| Curb ramps | None. Hand-label (or detect from the project's own surveys) outside the audit set | No surveyed dataset has a ramp class. |

Held-out rule: cut the boston-seaport showcase box (translate the EPSG:32619 box into nuScenes local coordinates via the map origin) plus a buffer from all nuScenes training patches; do not use any AV2 or OpenLane-V2 data from that area (none exists, those cities are elsewhere).

Licence consequence: all three sources are non-commercial (CC BY-NC-SA 4.0 or the nuScenes terms). Models trained on them carry share-alike and non-commercial risk; flag to the operator before any commercial use.
