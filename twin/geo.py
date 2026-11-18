"""UTM zone 19N (EPSG:32619) to WGS84 (EPSG:4326) helper."""

from pyproj import Transformer


def utm_to_latlon(x: float, y: float) -> tuple[float, float]:
    # Transformer constructed per call to avoid sharing across threads.
    transformer = Transformer.from_crs("EPSG:32619", "EPSG:4326", always_xy=True)
    lon, lat = transformer.transform(x, y)
    return (round(lat, 6), round(lon, 6))
