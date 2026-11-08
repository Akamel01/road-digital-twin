"""Import the nuScenes devkit map API on matplotlib 3.11.

nuscenes-devkit 1.1.9 calls plt.style.use('seaborn-whitegrid') at import, a style name matplotlib
removed in 3.8. Patch the old name to its replacement, then import.
"""


def nuscenes_map_class():
    """Return NuScenesMap, after restoring the style name the devkit expects."""
    import matplotlib.style as mpl_style

    if "seaborn-whitegrid" not in mpl_style.library:
        mpl_style.library["seaborn-whitegrid"] = mpl_style.library[
            "seaborn-v0_8-whitegrid"
        ]

    from nuscenes.map_expansion.map_api import NuScenesMap

    return NuScenesMap
