# ADR 0008 — Label tool persistence

Status: accepted (ticket #324; area build sources added for #339).

## Decisions

- Page lives at `<store>/labels/<site>/tool.html`; route `GET /api/r/labels/{site}/tool`; served only to loopback peers/Host, otherwise 404. No static mount; site deletion removes the page.
- Generator is `twin/labeltool.py` + `twin labels tool`, template via `importlib.resources`; no `scripts/` entry point.
- Widen `LabelFeature.type` with `double_line`, `ladder`, `continental`, `transverse`; keep raw tool string in `source_marking_type`.
- `SiteMeta.control`/`notes`; `PUT /api/w/labels/{site}` replaces both; allowed on frozen sites; no version bump.
- Page loads/saves surfaces through the labels API; only `origin="operator"` features with a mapped raw type and LineString/Polygon geometry are editable; everything else is carried through unchanged; localStorage only for supports/devices.
- Window is two-branch: fits (with `FIT_TOL_M=0.1`) -> origin `(minx, maxy)`; else centre on the union. Fixed 1600x1500 @ 5 cm.
- Areas root is explicit: `--areas PATH`, default `<store>/areas`; an area build path is also accepted; `resolve_area()` is the single resolver.
- D16: an existing site that resolves zero runs **and has no usable area build** (no `<area>-twin/4_ground/ground.laz`) is a hard error (exit 2); an existing site with a usable area build falls back to the area source; only a genuinely new site may render the blank-but-usable page.

## Addendum (#339) — area build as a label source

- Store runs take precedence; the area source is used only when `runs_for_area` returns `[]`.
- Area source paths: intensity/Height from `<area>-twin/4_ground/ground.laz`; camera frames from `<area>-merged/drives/<scene>/`; the map-frame correction `T[:3,3] += centre − R@centre` (centre = polygon centroid) is applied once, to uncorrected `3_align/poses.json`.
- Area window: `window_for(..., centre=True)` centres the window on the polygon bounds; the union (polygon ∪ labels) still decides fit/size; labels outside the polygon can fall outside the window.
- >80×75 m sites show the fixed 80×75 m window centred on the polygon bounds with the neutral sentence `Site larger than 80×75 m: showing the 80×75 m centred on the extent.`.
- Ortho and Combined backgrounds are disabled for area builds (no `6_colour` orthoimage); `no_imagery` stays `False`.
