# Label schema (audit set)

The audit set is hand-checked, frozen, versioned features used only to score (CONTEXT.md).
A labelled site is a directory `<store>/labels/<site>/` holding:

- `site.json` — a `SiteMeta` object.
- `labels.geojson` — a GeoJSON `FeatureCollection` whose features are `LabelFeature` objects.
- `labels.v{N}.geojson` — frozen snapshots taken on approve / new-version.

Contracts: `twin/contracts.py` (`SiteMeta`, `LabelFeature`); JSON Schemas `schemas/site_meta.schema.json`, `schemas/label_feature.schema.json`.

## `site.json` (`SiteMeta`)

| Field | Type | Notes |
|---|---|---|
| `id` | string | site id |
| `role` | `"dev"` or `"audit"` | dev site or audit site |
| `polygon` | object (GeoJSON geometry) | site polygon in EPSG:32619 |
| `version` | int (>=1) | bumped on approve / new-version |
| `approved_by` | string or null | approver |
| `approved_at` | string (ISO8601) or null | approval time |
| `crs` | `"EPSG:32619"` | fixed |
| `created_at` | string | ISO8601 creation time |
| `source_area` | string | area the site was drafted from |
| `frozen` | bool | true once approved |

## `labels.geojson` (`LabelFeature`)

Each feature is a GeoJSON Feature with `geometry` (2D or 3D, left as-is) and `properties`:

| Field | Type | Notes |
|---|---|---|
| `id` | string | feature id |
| `element` | `"marking"`, `"crosswalk"`, `"curb"`, `"curb_ramp"` | element type |
| `type` | string | marking: `solid_line`, `dashed_line`, `edge_line`, `stop_line`, `arrow`, `text`; crosswalk: `zebra`, `parallel`; curb: `curb`; curb_ramp: `curb_ramp` |
| `origin` | `"drafted"` or `"operator"` | see Origin below |
| `height_m` | number or null | curb height (curb) |
| ramp fields | number/string or null | exact names from `extract_ramps`: `kind`, `width_m`, `run_length_m`, `running_slope_pct`, `cross_slope_pct`, `flare_slope_pct`, `gutter_step_m`, `running_slope_status`, `cross_slope_status`, `flare_slope_status`, `gutter_step_status`, `status`, `nearest_crosswalk_m`, `crosswalk_id`, `n_points` |
| `source_feature_id` | string or null | provenance: source feature id |
| `source_file` | string or null | provenance: source file name |
| `source_marking_type` | string or null | provenance: source marking type |

Geometry is accepted as any dict (2D or 3D) and is not flattened.

### Origin

- `drafted`: machine-drafted from twin outputs (the `twin labels draft` command maps area-build features to labels).
- `operator`: human-corrected or approved by the operator.

## Examples

### Marking

```json
{
  "type": "Feature",
  "geometry": { "type": "LineString", "coordinates": [[0.0, 0.0, 0.0], [10.0, 0.0, 0.0]] },
  "properties": {
    "id": "marking-0001",
    "element": "marking",
    "type": "solid_line",
    "origin": "drafted",
    "source_feature_id": "m-0042",
    "source_file": "markings.geojson",
    "source_marking_type": "solid_line"
  }
}
```

### Crosswalk

```json
{
  "type": "Feature",
  "geometry": { "type": "Polygon", "coordinates": [[[0.0, 0.0], [5.0, 0.0], [5.0, 3.0], [0.0, 3.0], [0.0, 0.0]]] },
  "properties": {
    "id": "crosswalk-0001",
    "element": "crosswalk",
    "type": "zebra",
    "origin": "drafted",
    "source_feature_id": "cw-0007",
    "source_file": "crosswalks.geojson"
  }
}
```

### Curb

```json
{
  "type": "Feature",
  "geometry": { "type": "LineString", "coordinates": [[0.0, 0.0, 0.1], [10.0, 0.0, 0.1]] },
  "properties": {
    "id": "curb-0001",
    "element": "curb",
    "type": "curb",
    "origin": "operator",
    "height_m": 0.15,
    "source_feature_id": "c-0012",
    "source_file": "curbs.geojson"
  }
}
```

### Curb ramp

```json
{
  "type": "Feature",
  "geometry": { "type": "Point", "coordinates": [5.0, 1.5, 0.0] },
  "properties": {
    "id": "ramp-0001",
    "element": "curb_ramp",
    "type": "curb_ramp",
    "origin": "drafted",
    "kind": "curb_ramp",
    "width_m": 1.2,
    "run_length_m": 1.8,
    "running_slope_pct": 5.0,
    "cross_slope_pct": 1.2,
    "flare_slope_pct": 8.0,
    "gutter_step_m": 0.01,
    "running_slope_status": "ok",
    "cross_slope_status": "ok",
    "flare_slope_status": "ok",
    "gutter_step_status": "ok",
    "status": "ok",
    "nearest_crosswalk_m": 0.5,
    "crosswalk_id": "crosswalk-0001",
    "n_points": 42,
    "source_feature_id": "ramp-0001",
    "source_file": "ramps.geojson"
  }
}
```

## Consumer bridge

Label features feed the accuracy stage: `element`/`type` map to accuracy layers and `marking_type`:

- `marking` -> markings layer; `type` becomes `marking_type`.
- `crosswalk` -> crosswalks layer.
- `curb` -> curbs layer.
- `curb_ramp` -> ramps layer.
