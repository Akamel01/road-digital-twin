import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.itest

ROOT = Path(os.environ.get("NUSCENES_ROOT", "/data/nuscenes"))


def test_facilities_from_nuscenes_mini_map():
    if not (ROOT / "v1.0-mini").is_dir():
        pytest.skip(f"nuScenes mini not found at {ROOT} (default /data/nuscenes)")
    from twin.contracts import IsdParams
    from twin.devkit_compat import nuscenes_map_class
    from twin.facilities import from_nuscenes_map, intersections, isd_required_m

    NuScenesMap = nuscenes_map_class()
    nusc_map = NuScenesMap(dataroot=str(ROOT), map_name="boston-seaport")
    x0, y0 = 300.0, 1100.0  # arbitrary patch inside the map
    view = from_nuscenes_map(nusc_map, (x0, y0, x0 + 200, y0 + 200))
    p = IsdParams()
    facs = intersections(view, isd_required_m(p), p.eye_setback_m)
    for f in facs:
        assert f["id"].startswith("I-") and len(f["id"]) == 6
        assert len(f["legs"]) == len(f["eye_points"])
