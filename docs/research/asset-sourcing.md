# 3D model sourcing and licences: vehicles and street furniture (issue #504)

Research note for issue #504. No models downloaded. Licence claims come from the source pages named in each row; where a page did not state a value, the cell says so.

## Compatibility rule for a CC BY-NC-SA 4.0 demo

The demo is licensed CC BY-NC-SA 4.0 (nuScenes-derived content, non-commercial).

| Asset licence | Usable in demo? | Conditions |
|---|---|---|
| CC0 1.0 | Yes | None required. Credit optional. |
| CC BY 4.0 | Yes | Credit the author, link the licence, note changes. |
| CC BY-SA 4.0 | Yes | Demo must carry BY-NC-SA 4.0 (ShareAlike is compatible). |
| CC BY-NC 4.0 / BY-NC-SA 4.0 | Yes | Demo is non-commercial, so allowed. |
| CC BY-ND 4.0 | No (avoid) | No adaptation. Format conversion or retopology counts as adaptation. |
| "Royalty free", custom, or "no AI" terms | Avoid | Extra restrictions the CC terms do not carry. Check text before any use. |

Source for the NC and SA terms: https://creativecommons.org/licenses/by-nc-sa/4.0/ (NonCommercial and ShareAlike clauses, attribution requirements).

## Cars (sedan, SUV, pickup, van)

No realistic, North-American, CC0 car set was found. Candidates are low-poly, and the realistic CC-BY scans are too heavy.

| Source | URL | Licence | Attribution text | Format | Polycount | Demo-compatible? |
|---|---|---|---|---|---|---|
| Kenney Car Kit | https://kenney.nl/assets/car-kit (itch: https://kenney-assets.itch.io/car-kit) | CC0 1.0 (page: "Creative Commons CC0") | Not required. Suggested: "Car Kit by Kenney (kenney.nl)". | glTF, FBX, OBJ per itch listing. GLB not confirmed in the download. | Not published. Check on download. 45 files. | Yes |
| Quaternius Lowpoly Cars | https://quaternius.itch.io/lowpoly-cars | CC0 1.0 (linked from page) | Not required. Suggested: "Lowpoly Cars by Quaternius (quaternius.com)". | FBX, OBJ, Blend (per page). No GLB listed. | Not published. | Yes. Cop SUV is Patreon-only, so skip it. |
| CGTrader free low-poly vehicles pack | https://www.cgtrader.com/free-3d-models/car/car/free-low-poly-vehicles-pack | CC0 (per listing snippet, not fetched) | Not required. Verify on page. | Not verified | Not verified. Low-poly. Contains sedan, pickup, SUV per listing. | Yes if licence confirmed on page |
| Sketchfab CC-BY vehicles (e.g. brown sedan photogrammetry scan) | https://sketchfab.com/3d-models/brown-sedan-free-raw-scan-7356fa53585a4ec286311f4ba95ab68b | CC BY (per search snippet). Also carries a "NoAI" restriction. | Author name + CC BY 4.0 link | GLB via Sketchfab download | 2.5M triangles | No. Too heavy for web viewer, and NoAI term conflicts with CC. |
| Sketchfab "Vehicle topology kit" | https://sketchfab.com/3d-models/vehicle-topology-kit-cc0-c13e54a5c560400cb343f2284e9961e4 | CC0 (per title) | Not required | Not verified | Base mesh | Not useful as a finished car (base topology only) |

Top recommendation for cars: Kenney Car Kit (CC0, explicit licence page). Confirm which of its files are sedan, SUV, pickup and van, and measure triangles, before use. Quaternius is the second option. Neither is a realistic match, so keep them as placeholders and flag as such in the demo.

## Traffic signals (US mast arm)

| Source | URL | Licence | Attribution text | Format | Polycount | Demo-compatible? |
|---|---|---|---|---|---|---|
| Kenney City Kit (Roads) v2.1 | https://kenney.nl/assets/city-kit-roads | CC0 1.0 (page) | Not required | Not listed on page | Not published. Page notes "road signs and traffic lights" (v2.1). No mast arm confirmed. | Yes |
| Sketchfab "Traffic lights street assets vol 02" (author Alt, @whisper.alt) | https://sketchfab.com/3d-models/traffic-lights-street-assets-vol-02-ab3efdd259a54d4aba5f878eacbe3f20 | CC BY 4.0 (page) | "Traffic lights street assets vol 02 by Alt (@whisper.alt), CC BY 4.0, via Sketchfab" | Sketchfab download (formats not listed) | 3.9k triangles total; auto signal 2.6k, pedestrian 1.3k | Yes with credit. Tags say "korean", so not US style. |
| Sketchfab "California Modern Traffic Signal Mast Arms Set" (Signalrenders) | https://sketchfab.com/Signalrenders | Not checked (page not fetched) | Not checked | Not checked | Not checked | Unknown. Check page. |
| CGTrader mast-arm listings | https://www.cgtrader.com/3d-models/exterior/street-exterior/standard-horizontal-mast-arm-traffic-light-3d-model | "Royalty Free License (no AI)" per search snippet | n/a | n/a | n/a | No. Not CC; extra AI term. |

Top recommendation: Kenney City Kit (Roads) for signal heads as a CC0 base. Build the US mast arm procedurally in Blender (simple cylinder and box geometry), or use the Signalrenders set if its licence page confirms CC BY or CC0.

## Sign posts and US signs

| Source | URL | Licence | Attribution text | Format | Polycount | Demo-compatible? |
|---|---|---|---|---|---|---|
| MUTCD sign artwork (2D) | https://download.osmand.net/wiki/Category:PD_MUTCD (mirror of Wikimedia Commons PD-MUTCD category) | Public domain (US government MUTCD; Commons template PD-USGov-MUTCD) | Not required | SVG (2D) | n/a | Yes. Use as textures on generated 3D sign boards. |
| FHWA WFLHD CAD cell library "signs.cel" | https://webarchive.library.unt.edu/web/20130215101215/http:/www.wfl.fhwa.dot.gov/resources/cadd/cells/signs | Not stated in snippet. Archived 2013 copy. | Verify | CAD cells, not 3D | n/a | Unknown. Verify licence on current FHWA site. |
| CGTrader US road sign packs (R-series etc.) | https://www.cgtrader.com/3d-models/exterior/landscape/road-sign-us-r10-series-traffic-signal | Royalty-free/extended licence | n/a | 3D | Not checked | No |

Top recommendation: generate sign boards and posts procedurally in Blender or Three.js geometry, with MUTCD public-domain 2D artwork as the face texture. This avoids a licence search for each sign. No free public-domain 3D sign set was found.

## Fire hydrants

| Source | URL | Licence | Attribution text | Format | Polycount | Demo-compatible? |
|---|---|---|---|---|---|---|
| OpenGameArt "Low Poly Fire Hydrant" | https://opengameart.org/content/low-poly-fire-hydrant | CC0 (page) | Not required | .blend only. Convert to glTF/GLB. | Not checked | Yes |
| Meshy community hydrant models | https://www.meshy.ai/tags/firehydrant | CC0 per Meshy ToS for community uploads (per page) | Not required | GLB listed. Free tier formats may be STL/OBJ/FBX only. | Not checked | Conditional. Check each model's licence and that GLB downloads on free tier. |
| itch "Retopped Fire Hydrant scan" (duhgless) | https://duhgless.itch.io/retopped-fire-hydrant | Not stated in snippet | Verify | GLB 25 MB | Not checked | Unknown. Check page. |

Top recommendation: OpenGameArt low-poly hydrant (CC0). Convert from .blend and decimate.

## Utility and light poles

| Source | URL | Licence | Attribution text | Format | Polycount | Demo-compatible? |
|---|---|---|---|---|---|---|
| Kenney City Kit (Suburban) | https://kenney.nl/assets/city-kit-suburban | CC0 1.0 (page) | Not required | Not listed | Not published. Pole models not confirmed. | Yes, if poles are in the files |
| Kenney City Kit (Roads) | https://kenney.nl/assets/city-kit-roads | CC0 1.0 (page) | Not required | Not listed | Not published. Traffic-light and sign posts likely cover light poles. Verify. | Yes |

Top recommendation: Kenney City Kit (Roads). Check the file list for street-light and pole models. If missing, model a cylinder pole procedurally.

## Benches and trash bins

| Source | URL | Licence | Attribution text | Format | Polycount | Demo-compatible? |
|---|---|---|---|---|---|---|
| Kenney City Kit (Roads) v2.2 | https://kenney.nl/assets/city-kit-roads | CC0 1.0 | Not required | Not listed | Page names a "dumpster" prop (v2.2). No bench or bin confirmed. | Yes for dumpster-like bins. Verify. |
| Kenney City Kit (Suburban) | https://kenney.nl/assets/city-kit-suburban | CC0 1.0 | Not required | Not listed | Benches and bins not confirmed | Verify file list |
| CGTrader street-furniture listings | https://www.cgtrader.com/3d-models/exterior/street-exterior/street-assets-1 | Royalty-free or custom (per listing family) | n/a | n/a | n/a | No |

Top recommendation: check Kenney City Kit file lists for bench and bin models. If absent, model both procedurally (box and cylinder geometry), which is quick at low detail.

## Gaps and risks

- Realistic North-American car models with CC0 or CC-BY licences were not found in searches. Expect low-poly placeholders.
- Several results were "NoAI" or custom "royalty free" licences. These conflict with CC terms and should be excluded.
- Polycount is not published for most Kenney and Quaternius models. Measure after download, before adding to the viewer.
- Licence checks above use search snippets for several sources (CGTrader, Signalrenders, itch hydrant). Those rows need a page visit before use.
- Format conversion to glTF/GLB is needed for several sources (.blend, FBX, OBJ). Format change is treated as adaptation under CC terms: fine for CC0, BY, SA, NC; not for ND.

## Sources

- Kenney Car Kit: https://kenney.nl/assets/car-kit
- Kenney Car Kit (itch, formats): https://kenney-assets.itch.io/car-kit
- Kenney City Kit (Roads): https://kenney.nl/assets/city-kit-roads
- Kenney City Kit (Suburban): https://kenney.nl/assets/city-kit-suburban
- Quaternius Lowpoly Cars: https://quaternius.itch.io/lowpoly-cars
- Poly Haven licence: https://polyhaven.com/license
- Sketchfab, Alt traffic lights: https://sketchfab.com/3d-models/traffic-lights-street-assets-vol-02-ab3efdd259a54d4aba5f878eacbe3f20
- CC BY-NC-SA 4.0 deed: https://creativecommons.org/licenses/by-nc-sa/4.0/
- MUTCD public-domain category (mirror): https://download.osmand.net/wiki/Category:PD_MUTCD
- OpenGameArt low-poly hydrant: https://opengameart.org/content/low-poly-fire-hydrant
- Meshy hydrant tag: https://www.meshy.ai/tags/firehydrant
