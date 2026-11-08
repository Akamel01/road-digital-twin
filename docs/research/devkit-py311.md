# Does nuscenes-devkit run on Python 3.11?

Answers [#4](https://github.com/Akamel01/road-digital-twin/issues/4) (part of #3, decides the Python version for T1 / spec R9).

## Answer

**Yes. Use Python 3.11; no pin to 3.10, no vendoring.** `nuscenes-devkit` 1.2.0 installs cleanly on CPython 3.11 and `nuscenes.map_expansion.map_api.NuScenesMap` imports (tested 2026-11-07). It uses Shapely 2.x (`Shapely~=2.0.3` resolves to 2.0.7).

Two catches:

1. **numpy is capped below 2.0** (`numpy<2.0.0`, resolves to 1.26.4). If the rest of our stack needs numpy 2, an override (`uv pip install --override` with `numpy>=2`) installs numpy 2.4.6 and the map API still imports. That is not upstream-supported, so treat it as a fallback.
2. **Map rendering via `descartes` is broken with Shapely 2.x** (upstream issue #1180, open). `descartes.PolygonPatch` raises `IndexError`. This affects only the `render_*` plotting helpers, not the geometry/query API (`get_records_in_patch`, `layers_on_point`, lane discretisation, and so on). If we need plots, the smallest fix is a small local patch helper, e.g. build a `matplotlib.path.Path` from `polygon.exterior.coords`. Don't vendor `map_api.py`.

## Evidence

### Package metadata (PyPI)

From <https://pypi.org/pypi/nuscenes-devkit/json>:

- Latest version **1.2.0**, uploaded 2025-08-28, single wheel `nuscenes_devkit-1.2.0-py3-none-any.whl` (pure Python, so there is no per-version binary to worry about).
- `requires_python: >=3.9`.
- Classifiers list only Python 3.9 and 3.12. 3.11 isn't listed, but it falls inside the supported range.
- `requires_dist` includes `numpy<2.0.0,>=1.22.0`, `Shapely~=2.0.3`, `descartes`, `matplotlib>=3.6.0`, `opencv-python-headless>=4.5.4.58`, `pycocotools>=2.0.1`.

### Source repo (GitHub, `master`)

- [`setup/setup.py`](https://github.com/nutonomy/nuscenes-devkit/blob/master/setup/setup.py): `version='1.2.0'`, `python_requires='>=3.9'`, classifiers 3.9 and 3.12.
- [`setup/requirements/requirements_base.txt`](https://github.com/nutonomy/nuscenes-devkit/blob/master/setup/requirements/requirements_base.txt): `numpy>=1.22.0,<2.0.0`, `Shapely~=2.0.3`.
- [`python-sdk/nuscenes/map_expansion/map_api.py`](https://github.com/nutonomy/nuscenes-devkit/blob/master/python-sdk/nuscenes/map_expansion/map_api.py) imports `descartes`, `cv2`, `matplotlib`, `shapely` (`affinity`, `Polygon`, `MultiPolygon`, ...) and handles map versions `< '1.3'` explicitly, so map expansion v1.3 is the current format.

### Open upstream issues

- [#1200 "Lift numpy<2.0 cap in requirements_base.txt"](https://github.com/nutonomy/nuscenes-devkit/issues/1200) (open, no maintainer reply). The cap came in with #1117 (Sep 2024) as a workaround for the NumPy 2 ABI break. The issue notes that all direct dependencies now ship numpy-2 wheels.
- [#1180 "descartes 1.1.0 and Shapely~=2.0.3 mismatch"](https://github.com/nutonomy/nuscenes-devkit/issues/1180) (open). `render_map_patch` fails with `IndexError: too many indices for array: array is 0-dimensional`. The only workarounds in the thread are hand-patching `descartes/patch.py` or going back to Python 3.9.
- Closed: [#870 "Shapely>=2.x Incompatibility"](https://github.com/nutonomy/nuscenes-devkit/issues/870), fixed by the move to `Shapely~=2.0.3`.

### Hands-on test (box, throwaway venv, deleted afterwards)

`uv venv -p 3.11` + `uv pip install nuscenes-devkit` on CPython **3.11.16**:

| package | resolved |
|---|---|
| nuscenes-devkit | 1.2.0 |
| numpy | 1.26.4 |
| shapely | 2.0.7 |
| descartes | 1.1.0 |
| matplotlib | 3.11.2 |
| opencv-python-headless | 4.11.0.86 |
| scipy | 1.17.1 |
| scikit-learn | 1.9.1 |
| pycocotools | 2.0.11 |

- `import nuscenes.map_expansion.map_api` → OK (`NuScenesMap` class loads).
- `descartes.PolygonPatch(shapely.geometry.box(0,0,1,1))` → `IndexError: too many indices for array: array is 0-dimensional, but 2 were indexed`, which confirms #1180 on 3.11.
- Second venv with `--override numpy>=2`: numpy 2.4.6 + shapely 2.0.7, and the map API import still succeeds.

Not tested: loading real map JSON (no nuScenes data on the box at test time). Import-level success plus pure-Python package code makes runtime breakage on 3.11 unlikely, but the T1 smoke test should load one map (e.g. `singapore-onenorth`) to close this out.
