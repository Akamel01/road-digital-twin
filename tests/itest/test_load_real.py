import json
import os
from pathlib import Path

import numpy as np
import pytest

pytestmark = pytest.mark.itest

ROOT = Path(os.environ.get("NUSCENES_ROOT", "/data/nuscenes"))


def test_load_first_scene_of_mini(tmp_path):
    if not (ROOT / "v1.0-mini").is_dir():
        pytest.skip(f"nuScenes mini not found at {ROOT} (default /data/nuscenes)")
    from nuscenes.nuscenes import NuScenes

    from twin.stages.load import (
        MAP_ORIGIN_LATLON,
        OUTPUT_FILES,
        DevkitSource,
        assemble,
        name_facilities,
        run_crs,
        write_outputs,
    )

    nusc = NuScenes("v1.0-mini", dataroot=str(ROOT), verbose=False)
    scene_token = nusc.scene[0]["token"]
    scene = assemble(DevkitSource(str(ROOT)), scene_token, run_crs(MAP_ORIGIN_LATLON))
    write_outputs(tmp_path, scene, name_facilities(scene.facilities, None))

    assert all((tmp_path / f).is_file() for f in OUTPUT_FILES)
    assert len(scene.sweeps) > 0
    with np.load(tmp_path / "points.npz") as f:
        assert len(f["x"]) > 0
        # Boston seaport in UTM 19N: easting near 330000, northing near 4.69e6.
        assert 320_000 < float(np.median(f["x"])) < 340_000
        assert 4_680_000 < float(np.median(f["y"])) < 4_700_000
    boxes = json.loads((tmp_path / "boxes.json").read_text())
    assert len(boxes["sweeps"]) == len(scene.sweeps)
