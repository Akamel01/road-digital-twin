"""Street names for facilities from OpenStreetMap (decision 40, ODbL).

One Overpass query per bbox, cached on disk with its query date. A cache hit never touches the
network. Naming takes facility dicts as `twin.facilities` returns them (GeoJSON geometry, EPSG:32619).
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime
from math import inf
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from pyproj import Transformer
from shapely.geometry import LineString, shape

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
USER_AGENT = "road-digital-twin/0.1 (+https://github.com/Akamel01/road-digital-twin)"
TIMEOUT_S = 60
NAME_RANGE_M = 15.0
LICENCE = "ODbL"

_TO_UTM = Transformer.from_crs("EPSG:4326", "EPSG:32619", always_xy=True)

Street = tuple[str, LineString]


def to_utm(lon: float, lat: float) -> tuple[float, float]:
    return _TO_UTM.transform(lon, lat)


def _query(bbox: tuple[float, float, float, float]) -> str:
    """bbox = (west, south, east, north) in WGS84. Overpass wants (south, west, north, east)."""
    w, s, e, n = bbox
    return (
        f'[out:json][timeout:60];\nway["highway"]["name"]({s},{w},{n},{e});\nout geom;'
    )


def _request(query: str) -> Request:
    return Request(
        OVERPASS_URL,
        data=urlencode({"data": query}).encode(),
        headers={"User-Agent": USER_AGENT},
    )


def _post(query: str) -> dict:
    with urlopen(_request(query), timeout=TIMEOUT_S) as resp:
        return json.load(resp)


def _cache_path(bbox: tuple[float, float, float, float], cache_dir: Path) -> Path:
    key = hashlib.sha1(json.dumps(list(bbox)).encode()).hexdigest()[:12]
    return cache_dir / f"overpass-{key}.json"


def _streets_from(raw: dict) -> list[Street]:
    streets = []
    for el in raw.get("elements", []):
        name = el.get("tags", {}).get("name")
        geom = el.get("geometry") or []
        if not name or len(geom) < 2:
            continue
        streets.append((name, LineString([to_utm(p["lon"], p["lat"]) for p in geom])))
    return streets


def fetch_streets(
    bbox_wgs84: tuple[float, float, float, float], cache_dir: str | Path
) -> tuple[list[Street], date]:
    """Streets in the bbox as (name, LineString in EPSG:32619), and the Overpass query date.

    A cache miss makes one request and writes the raw response with its date. A hit reads the file only.
    Network errors propagate; the caller falls back to facility IDs.
    """
    path = _cache_path(bbox_wgs84, Path(cache_dir))
    if path.exists():
        cached = json.loads(path.read_text())
        return _streets_from(cached["overpass"]), date.fromisoformat(
            cached["query_date"]
        )
    raw = _post(_query(bbox_wgs84))
    query_date = datetime.now(UTC).date()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"query_date": query_date.isoformat(), "overpass": raw}))
    return _streets_from(raw), query_date


def osm_names_meta(query_date: date) -> dict:
    """The manifest's data.osm_names entry."""
    return {"overpass_query_date": query_date, "licence": LICENCE}


def _nearest_names(geom, streets: list[Street]) -> list[str]:
    """Distinct street names within NAME_RANGE_M of geom, nearest first (ties by name)."""
    best: dict[str, float] = {}
    for name, line in streets:
        d = geom.distance(line)
        if d <= NAME_RANGE_M and d < best.get(name, inf):
            best[name] = d
    return sorted(best, key=lambda n: (best[n], n))


def name_facility(facility: dict, streets: list[Street]) -> str | None:
    """Intersection: two nearest streets joined " & ". Segment: nearest street to the centreline
    midpoint. Access point: "Access to <nearest street>". None when nothing is within range.

    Input keys: `core` (GeoJSON) for intersections and access points, `centreline` (GeoJSON
    LineString) for segments.
    """
    kind = facility["type"]
    if kind == "intersection":
        names = _nearest_names(shape(facility["core"]), streets)[:2]
        return " & ".join(sorted(names)) if names else None
    if kind == "segment":
        mid = shape(facility["centreline"]).interpolate(0.5, normalized=True)
        names = _nearest_names(mid, streets)
        return names[0] if names else None
    if kind == "access_point":
        names = _nearest_names(shape(facility["core"]), streets)
        return f"Access to {names[0]}" if names else None
    raise ValueError(f"unknown facility type: {kind!r}")
