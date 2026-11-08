import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.itest

ROOT = Path(os.environ.get("NUSCENES_ROOT", "/data/nuscenes"))


def test_scan_scenes_on_real_mini():
    if (
        not (ROOT / "v1.0-mini").is_dir()
        or not (ROOT / "maps" / "expansion" / "boston-seaport.json").is_file()
    ):
        pytest.skip(f"nuScenes mini with map expansion not found at {ROOT}")
    from twin.select import scan_scenes

    rows = scan_scenes(ROOT)
    assert rows
    for row in rows:
        assert row["keyframes"] > 0
        assert row["density"] >= 0
        assert row["contrast"] >= 0
        assert isinstance(row["go"], bool)
