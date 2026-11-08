import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.itest

ROOT = Path(os.environ.get("NUSCENES_ROOT", "/data/nuscenes"))


def test_nuscenes_mini_loads_with_ten_scenes():
    if not (ROOT / "v1.0-mini").is_dir():
        pytest.skip(
            f"nuScenes mini not found at {ROOT} (default /data/nuscenes); "
            "run scripts/get_nuscenes_mini.sh"
        )
    from nuscenes.nuscenes import NuScenes

    nusc = NuScenes("v1.0-mini", dataroot=str(ROOT), verbose=False)
    assert len(nusc.scene) == 10
