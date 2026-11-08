"""devkit_compat: the NuScenesMap import works on matplotlib 3.11 (no dataset needed)."""

import matplotlib.style as mpl_style

from twin.devkit_compat import nuscenes_map_class


def test_nuscenes_map_imports_after_style_shim():
    cls = nuscenes_map_class()
    assert cls.__name__ == "NuScenesMap"
    assert "seaborn-whitegrid" in mpl_style.library
