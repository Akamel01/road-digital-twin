# Far buildings around site-a1 (issue #506)

Question: which source gives the far buildings in the ~150 m context ring around site-a1 (Boston Seaport, nuScenes `boston-seaport`), as 3D models for a non-commercial three.js / glTF web demo?

Scope: metadata and licence pages only. No dataset was downloaded. Where a primary page could not be fetched, that is stated.

## Recommendation

Use **OpenStreetMap building footprints with `height` / `building:levels` tags, extruded to LOD1 glTF**, for the v1 demo. Attribution is "© OpenStreetMap contributors" with an ODbL link.

Upgrade path: **BPDA Boston 3D City Model** textured OBJ tiles, once BPDA confirms in writing that non-commercial web reuse is allowed (its page states no licence).

Reject: Google Photorealistic 3D Tiles (terms prohibit export, derived 3D models and offline use). Reject MassGIS for heights (no statewide heights; the Boston heights product is from 2002).

## Candidates

### 1. OpenStreetMap buildings (ODbL)

- **Download:** Overpass API or Geofabrik Massachusetts extract (`massachusetts-latest.osm.pbf`). Metadata only was checked, the extract was not downloaded. Geofabrik URL not verified against the live site in this session.
- **Format:** OSM XML/PBF, polygon ways with tags. No textures.
- **LOD:** LOD1 (extruded footprint, height from `height` or `building:levels` x ~3 m). Roof shape only where tagged.
- **Coordinates:** WGS84 lat/lon. Reproject to the local frame.
- **Licence:** ODbL 1.0 for the data; documentation CC BY-SA 2.0 ([openstreetmap.org/copyright](https://www.openstreetmap.org/copyright)).
- **Attribution:** Display credit to OpenStreetMap and make clear the data is ODbL, with a link to the copyright page. Share-alike applies if a derived *database* is distributed. A rendered demo of extruded geometry is most likely a Produced Work (attribution only). This needs a check against the full ODbL legal code before publishing the glTF files as a download.
- **Seaport coverage:** Not verified. Heights are sparse in many urban areas and new Seaport towers may be missing or only partly tagged. Needs an Overpass count of tagged buildings in the ring before committing.
- **Vintage:** Continuously edited, so it reflects new construction, not 2018. Mixed-vintage risk runs the other way: buildings demolished after 2018 may still be present if not edited.
- **Alignment:** Footprints are digitised from imagery (typically 2–10 m horizontal accuracy in urban areas, to be checked per building). The nuScenes frame error is the dominant term (see below).

### 2. BPDA Boston 3D City Model (3D tiles, OBJ)

Source: [bostonplans.org 3D data download](https://www.bostonplans.org/3d-data-maps/3d-smart-model/3d-data-download), [about 3D](https://www.bostonplans.org/3d-data-maps/3d-smart-model/about-3d). **Both primary pages returned HTTP 403 to WebFetch in this session.** The facts below come from the cityschema catalog mirror, which is secondary. Re-check against the BPDA pages before relying on them.

- **Download:** Tile map at the BPDA GIS Lab page. Individual model collections per tile, plus a city-wide GeoJSON/CSV catalog. No single city-wide file (split by neighbourhood because of size).
- **Format:** Wavefront OBJ (per tile). A SketchUp version exists, but an older 2018 article says it needs SketchUp Pro. Do not use SketchUp.
- **LOD:** Not stated. Described as "detailed tiled terrain models" and bridge models. Building models appear to be textured meshes derived from photogrammetry or CyberCity 3D, so this is probably LOD2 or textured. Confirm from a sample tile's metadata.
- **Coordinates:** Massachusetts State Plane tile grid (per the catalog page). Needs conversion to EPSG:32619 for the local frame.
- **Licence:** Not stated on the BPDA pages reached via the mirror. **Unknown. Must be asked.**
- **Attribution:** Unknown. Use "City of Boston / BPDA" as a placeholder, and do not reuse without confirmation.
- **Vintage:** Base map is ortho imagery from March 2021. Building sources are 2011 planimetric data plus updates from BPDA Urban Design models, CyberCity 3D and LiDAR (per the catalog mirror; dates of the update not given). Likely includes some Seaport towers built after 2018, but not reliably the 2018 state.
- **Alignment:** Tile grid is a projected State Plane system, so the geometry is accurate in its own CRS. Error to the nuScenes frame comes from the georeference (below), plus any absolute error in BPDA's model (unknown, probably sub-metre to a few metres for a survey-based model).

### 3. MassGIS Building Structures (2D, statewide)

Source: [mass.gov MassGIS building structures](https://www.mass.gov/info-details/massgis-data-building-structures-2-d). **Page returned HTTP 403 to WebFetch.** Facts from search snippets.

- **Download:** MassGIS data portal (exact link not verified). ArcGIS FeatureServer exists for viewing.
- **Format:** Polygon layer `STRUCTURES_POLY` (shapefile/GDB expected, not verified).
- **LOD:** 2D roof outlines ("roofprints") for buildings over 150 sq ft. No attributes from creation. **No statewide heights.**
- **Heights:** Only a 2002 LiDAR Boston-area product has ground and building heights. Source: [MIT GIS Lab record](https://geodata.libraries.mit.edu/record/gismit:US_MA_BOSTONMET_G46BLDGHT_2002). Shapefile, issued 2002-04-07, licence not stated on the record. Harvard's copy of the same data is marked "Restricted", MIT's "Public". Coordinate system not stated on the page (FGDC XML linked, not read).
- **Coordinates:** MA State Plane (expected, to confirm in the FGDC file).
- **Licence:** Statewide layer under MassGIS open data terms (not read). 2002 height product: unclear.
- **Vintage:** 2002 heights are too old for Seaport. Most of Seaport was industrial or parking in 2002 and is now towers. Using 2002 heights would produce wrong buildings. Statewide footprints are recent (2025 imagery in parts), but need heights from elsewhere.
- **Verdict:** Good footprint source for a height-from-another-source join. Not a height source on its own.

### 4. Google Photorealistic 3D Tiles

Source: [Map Tiles API policies](https://developers.google.com/maps/documentation/tile/policies) (read in session).

- Caching and pre-fetching are only allowed where the Service Specific Terms expressly permit.
- Bulk download of map tiles is prohibited; so is scraping for use outside the Services.
- "Offline uses" are prohibited, and the API is for visualisation only.
- "Don't create content based on Google Maps Content" and "don't ... build 3D or terrain models" are prohibited.
- A Google FAQ treats reading and recording measurements (heights, distances) from the 3D imagery as derivative and prohibited.

**Verdict: unusable.** Exporting glTF from these tiles breaks the policy directly. Live viewing with an API key is the only permitted use, and that would not satisfy the "3D models for a demo" requirement.

### 5. Cesium OSM Buildings

Source: [Cesium OSM Buildings](https://cesium.com/platform/cesium-ion/content/cesium-osm-buildings/) and [Content usage and attribution guide](https://cesium.com/learn/ion/content-usage-and-attribution-guide/), via search snippets.

- Derived from OSM, served as 3D Tiles through Cesium ion. Attribution "© OpenStreetMap contributors" is required and is added automatically in Cesium software. Do not remove or obscure it.
- Needs an active Cesium ion account to use the asset.
- Cesium's terms cover the dataset separately (Global 3D Content terms). Full terms not read.
- **Verdict:** Viable only for live viewing in Cesium. Not a glTF export route. The OSM source option (1) gives the same data with control over LOD and export, so use that instead.

## Alignment to the nuScenes frame

Repo facts (from `docs/design/twin-v1-spec.md`, "Georeference"):

- The Boston map origin is from nuscenes-devkit `export_poses.py`. Its absolute accuracy is **unknown** (spec says "approximate").
- The local frame is a transverse Mercator centred on that origin, transformed to UTM 19N (EPSG:32619). Adding offsets directly to UTM is not used because it ignores about 1.3° of grid convergence at Boston (roughly 20 m per km).

External evidence:

- [BLOS-BEV (arXiv 2407.08526)](https://arxiv.org/pdf/2407.08526) found that aligning OSM data to nuScenes Boston maps needed an extra 1.35× scaling of the map origin beyond the standard EPSG:4326 → EPSG:3857 conversion. Singapore needed none. This suggests the Boston map frame is not a plain Web Mercator. Treat the origin as unreliable until checked.
- [HOLO (arXiv 2601.02730)](https://arxiv.org/pdf/2601.02730) describes the nuScenes frame as local ENU with a fixed regional origin, and notes that EPSG:3857 alignment needs manual scaling for Boston.

Estimated alignment error (estimate, not measured):

- Footprints or meshes in their own projected CRS: sub-metre internal accuracy for BPDA, a few metres for OSM footprints in urban areas.
- Frame error to nuScenes: dominated by the origin. If the origin is off by a few metres, and the 1.35× scale issue is not handled, error at the 150 m ring can reach tens of metres. Handled properly (tmerc on the devkit origin plus a check against the HD map), expect roughly 1–3 m at 150 m.
- **Validation:** match ring footprints against the nuScenes drivable area and road edges, and fit the origin offset/scale against a few visible corners before the demo.

## Data vintage vs nuScenes (2018 capture)

- nuScenes capture: 2018. Seaport changed heavily after 2018. Many buildings in the ring may not have existed at capture.
- BPDA base imagery: March 2021. Building models are later than 2018, so they include post-2018 towers.
- OSM: current edits. Post-2018 towers present if mapped. Demolished buildings may linger.
- For a demo of the current city, mixing post-2018 buildings with a 2018 road network is acceptable. Note it on the page.

## Open items (not verified in this session)

1. BPDA pages returned 403. Re-check the download page, the 3D model licence and LOD from a sample tile. Ask BPDA for written permission for non-commercial web use.
2. MassGIS download links and formats not confirmed.
3. OSM tag coverage in the 150 m ring not counted. Run an Overpass query before committing.
4. ODbL share-alike position on exported glTF not resolved; read the ODbL legal code.
5. nuScenes origin and scale not checked against the devkit source (only the third-party HOLO and BLOS-BEV papers and the repo spec were used).

## Sources

- BPDA 3D data download (403, not read): https://www.bostonplans.org/3d-data-maps/3d-smart-model/3d-data-download
- BPDA about 3D (403, not read): https://www.bostonplans.org/3d-data-maps/3d-smart-model/about-3d
- BPDA model catalog mirror: https://cityschema.github.io/repository-catalog/catalog/about.htm
- MassGIS building structures (403, not read): https://www.mass.gov/info-details/massgis-data-building-structures-2-d
- MIT GIS Lab Boston 2002 heights record: https://geodata.libraries.mit.edu/record/gismit:US_MA_BOSTONMET_G46BLDGHT_2002
- Google Map Tiles API policies: https://developers.google.com/maps/documentation/tile/policies
- OSM copyright / ODbL: https://www.openstreetmap.org/copyright
- Cesium OSM Buildings: https://cesium.com/platform/cesium-ion/content/cesium-osm-buildings/
- Cesium content usage and attribution: https://cesium.com/learn/ion/content-usage-and-attribution-guide/
- BLOS-BEV: https://arxiv.org/pdf/2407.08526
- HOLO: https://arxiv.org/pdf/2601.02730
- Repo: `docs/design/twin-v1-spec.md` (Georeference), `docs/data/nuscenes.md`
