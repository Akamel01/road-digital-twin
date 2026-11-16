import time

import numpy as np

from twin import height_raster

# --- reference (pre-vectorization) implementation for R2 equivalence check ---
_OLD_CELL_M = 0.25
_OLD_WINDOW_HALF_CELLS = 12
_OLD_N_ROAD = 25


def _old_lattice_index(x: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    ix = np.floor(x / _OLD_CELL_M).astype(np.int64)
    iy = np.floor(y / _OLD_CELL_M).astype(np.int64)
    return ix, iy


def _old_bin_points_to_25cm_means(
    x: np.ndarray, y: np.ndarray, z: np.ndarray
) -> dict[tuple[int, int], float]:
    if len(x) == 0:
        return {}
    ix, iy = _old_lattice_index(x.astype(np.float64), y.astype(np.float64))
    zf = z.astype(np.float64)
    keys = np.column_stack([ix, iy])
    uniq, inv = np.unique(keys, axis=0, return_inverse=True)
    sums = np.bincount(inv, weights=zf, minlength=len(uniq))
    counts = np.bincount(inv, minlength=len(uniq))
    means: dict[tuple[int, int], float] = {}
    for k, s, c in zip(uniq.tolist(), sums.tolist(), counts.tolist()):
        if c >= 1:
            means[(int(k[0]), int(k[1]))] = float(s / c)
    return means


def _old_compute_height_above_road(
    drive_points: list[tuple[np.ndarray, np.ndarray, np.ndarray]],
) -> dict[tuple[int, int], float]:
    if not drive_points:
        return {}
    drive_means = [_old_bin_points_to_25cm_means(x, y, z) for x, y, z in drive_points]
    all_cells: set[tuple[int, int]] = set()
    for dm in drive_means:
        all_cells.update(dm.keys())
    if not all_cells:
        return {}
    h_map: dict[tuple[int, int], float] = {}
    for cell in all_cells:
        deltas: list[float] = []
        for dm in drive_means:
            if cell not in dm:
                continue
            mean_d = dm[cell]
            cx, cy = cell
            pop: list[float] = []
            for dx in range(-_OLD_WINDOW_HALF_CELLS, _OLD_WINDOW_HALF_CELLS + 1):
                for dy in range(-_OLD_WINDOW_HALF_CELLS, _OLD_WINDOW_HALF_CELLS + 1):
                    nk = (cx + dx, cy + dy)
                    if nk in dm:
                        pop.append(dm[nk])
            if len(pop) < _OLD_N_ROAD:
                continue
            road_d = float(np.percentile(np.asarray(pop, dtype=np.float64), 10, method="linear"))
            deltas.append(mean_d - road_d)
        if not deltas:
            continue
        h_map[cell] = float(np.mean(np.asarray(deltas, dtype=np.float64)))
    return h_map
# --- end reference ---


def _as_dict(h) -> dict[tuple[int, int], float]:
    if isinstance(h, dict):
        return h
    ny, nx = h.h.shape
    out: dict[tuple[int, int], float] = {}
    for yy in range(ny):
        for xx in range(nx):
            v = h.h[yy, xx]
            if np.isfinite(v):
                out[(h.ix0 + xx, h.iy0 + yy)] = float(v)
    return out


def test_ac4_curb_like_step_15cm():
    """AC4: flat road z=0.0, raised strip z=0.15. Road-side cells far from boundary -> ~0.0.
    High-side cells 0.5-2.0m from boundary -> ~0.15 (window includes road cells)."""
    xs = []
    ys = []
    zs = []
    for x in np.arange(5.0, 50.0, 0.1):
        for y in np.arange(5.0, 55.0, 0.1):
            xs.append(x)
            ys.append(y)
            zs.append(0.0)
    for x in np.arange(50.0, 95.0, 0.1):
        for y in np.arange(5.0, 55.0, 0.1):
            xs.append(x)
            ys.append(y)
            zs.append(0.15)
    pts = (np.array(xs, dtype=np.float64), np.array(ys, dtype=np.float64), np.array(zs, dtype=np.float64))
    hmap = height_raster.compute_height_above_road([pts])

    for cx in [30.0, 40.0, 45.0]:
        ix = int(np.floor(cx / height_raster.CELL_M))
        for iy in [24, 40, 80]:
            v = hmap.value(ix, iy)
            assert v is not None, f"expected road cell ({ix},{iy}) defined"
            assert abs(v - 0.0) <= 0.02, f"road cell ({ix},{iy}) v={v}"

    for cx in [50.75, 51.25, 51.75]:
        ix = int(np.floor(cx / height_raster.CELL_M))
        for iy in [24, 40, 80]:
            v = hmap.value(ix, iy)
            assert v is not None, f"expected high cell ({ix},{iy}) defined"
            assert abs(v - 0.15) <= 0.02, f"high cell ({ix},{iy}) v={v}"


def test_empty_no_data_transparent():
    hmap = height_raster.compute_height_above_road([])
    rgba = height_raster.render_height_rgba(hmap, x0=0.0, y0=0.0, cell=0.25, side=8)
    assert rgba.shape == (8, 8, 4)
    assert np.all(rgba[..., 3] == 0)


def test_clamp_low_and_high():
    hmap = height_raster.HeightField(np.array([[-1.0]], dtype=np.float64), 0, 0)
    rgba = height_raster.render_height_rgba(hmap, x0=0.0, y0=0.0, cell=0.25, side=4)
    assert tuple(rgba[3, 0, :3].tolist()) == (0x0F, 0x14, 0x33)
    assert int(rgba[3, 0, 3]) == 255

    hmap2 = height_raster.HeightField(np.array([[0.3]], dtype=np.float64), 0, 0)
    rgba2 = height_raster.render_height_rgba(hmap2, x0=0.0, y0=0.0, cell=0.25, side=4)
    assert tuple(rgba2[3, 0, :3].tolist()) == (0xFF, 0xFF, 0xFF)
    assert int(rgba2[3, 0, 3]) == 255


def test_multi_drive_shifted_z_invariance():
    rng = np.random.default_rng(1)
    xr = rng.uniform(10.0, 49.9, size=6000)
    yr = rng.uniform(0.0, 60.0, size=6000)
    zr = np.full(6000, 0.0, dtype=np.float64)
    xh = rng.uniform(50.0, 89.9, size=6000)
    yh = rng.uniform(0.0, 60.0, size=6000)
    zh = np.full(6000, 0.15, dtype=np.float64)
    x = np.concatenate([xr, xh])
    y = np.concatenate([yr, yh])
    z = np.concatenate([zr, zh])

    h1 = height_raster.compute_height_above_road([(x, y, z)])
    h2 = height_raster.compute_height_above_road([(x, y, z), (x, y, z + 5.0)])
    d1 = _as_dict(h1)
    d2 = _as_dict(h2)
    keys = set(d1.keys()) & set(d2.keys())
    assert len(keys) > 100
    for k in list(keys)[:200]:
        assert abs(d1[k] - d2[k]) <= 0.02


def test_registration_orientation_mapping():
    x0, y0, cell, side = 10.0, 20.0, 0.5, 10
    x = 10.8
    y = 20.3
    col = int(np.floor((x - x0) / cell))
    row = int(side - 1 - np.floor((y - y0) / cell))
    ix = int(np.floor(x / height_raster.CELL_M))
    iy = int(np.floor(y / height_raster.CELL_M))
    hmap = height_raster.HeightField(np.array([[0.1]], dtype=np.float64), ix, iy)
    rgba = height_raster.render_height_rgba(hmap, x0=x0, y0=y0, cell=cell, side=side)
    assert int(rgba[row, col, 3]) == 255


def test_vectorized_matches_reference_small_random():
    # Fully-defined dense lattice (one sample per 25cm cell over padded area) so road windows
    # contain all defined cells in both implementations and semantics align; compare to old dict impl.
    rng = np.random.default_rng(7)
    ix0, ix1 = 0, 159
    iy0, iy1 = 0, 159
    ixs = np.arange(ix0, ix1 + 1)
    iys = np.arange(iy0, iy1 + 1)
    gix, giy = np.meshgrid(ixs, iys)
    xx = (gix + 0.5) * height_raster.CELL_M
    yy = (giy + 0.5) * height_raster.CELL_M
    base = np.zeros_like(xx, dtype=np.float64)
    mask = (xx > 12.0) & (xx < 18.0) & (yy > 12.0) & (yy < 18.0)
    base[mask] = 0.12
    drives = []
    for _ in range(2):
        z = base + rng.normal(0.0, 0.01, size=base.shape)
        drives.append((xx.ravel(), yy.ravel(), z.ravel()))
    ref = _old_compute_height_above_road(drives)
    new = _as_dict(height_raster.compute_height_above_road(drives))
    h = height_raster.WINDOW_HALF_CELLS
    compared = 0
    for k, rv in ref.items():
        ix, iy = k
        if not (ix0 + h <= ix <= ix1 - h and iy0 + h <= iy <= iy1 - h):
            continue
        assert k in new, k
        assert abs(rv - new[k]) <= 1e-9, (k, rv, new[k])
        compared += 1
    assert compared > 5000


def test_timing_two_drives_one_million_points():
    rng = np.random.default_rng(11)
    drives = []
    for _ in range(2):
        x = rng.uniform(0.0, 200.0, size=1_000_000)
        y = rng.uniform(0.0, 200.0, size=1_000_000)
        z = rng.normal(0.0, 0.05, size=1_000_000)
        drives.append((x, y, z))
    t0 = time.perf_counter()
    hmap = height_raster.compute_height_above_road(drives)
    dt = time.perf_counter() - t0
    assert hmap.h.size > 0
    assert dt < 20.0, f"compute_height_above_road took {dt:.2f}s >= 20s"
