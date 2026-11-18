# ADR 0008 — Label tool persistence

Status: accepted (ticket #324).

## Decisions

- Page lives at `<store>/labels/<site>/tool.html`; route `GET /api/r/labels/{site}/tool`; served only to loopback peers/Host, otherwise 404. No static mount; site deletion removes the page.
- Generator is `twin/labeltool.py` + `twin labels tool`, template via `importlib.resources`; no `scripts/` entry point.
- Widen `LabelFeature.type` with `double_line`, `ladder`, `continental`, `transverse`; keep raw tool string in `source_marking_type`.
- `SiteMeta.control`/`notes`; `PUT /api/w/labels/{site}` replaces both; allowed on frozen sites; no version bump.
- Page loads/saves surfaces through the labels API; only `origin="operator"` features with a mapped raw type and LineString/Polygon geometry are editable; everything else is carried through unchanged; localStorage only for supports/devices.
- Window is two-branch: fits (with `FIT_TOL_M=0.1`) -> origin `(minx, maxy)`; else centre on the union. Fixed 1600x1500 @ 5 cm.
- Areas root is explicit: `--areas PATH`, default `<store>/areas`; an area build path is also accepted; `resolve_area()` is the single resolver.
- D16: an existing site that resolves zero runs is a hard error (exit 2); only a genuinely new site may render the blank-but-usable page.
