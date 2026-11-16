import numpy as np

from twin import height_raster


def test_ac4_curb_like_step_15cm():
    """AC4: flat road z=0.0, raised strip z=0.15. Road-side cells far from boundary -> ~0.0.
    High-side cells 0.5-2.0m from boundary -> ~0.15 (window includes road cells)."""
    # Deterministic dense sampling over a region that spans boundary x=50.0
    xs = []
    ys = []
    zs = []
    # Road: x in [5, 50) step 0.1, y in [5, 55] step 0.1
    for x in np.arange(5.0, 50.0, 0.1):
        for y in np.arange(5.0, 55.0, 0.1):
            xs.append(x)
            ys.append(y)
            zs.append(0.0)
    # Raised: x in [50, 95) step 0.1, y in [5, 55] step 0.1
    for x in np.arange(50.0, 95.0, 0.1):
        for y in np.arange(5.0, 55.0, 0.1):
            xs.append(x)
            ys.append(y)
            zs.append(0.15)
    pts = (np.array(xs, dtype=np.float64), np.array(ys, dtype=np.float64), np.array(zs, dtype=np.float64))
    hmap = height_raster.compute_height_above_road([pts])

    # Road-side deep inside: x_center <= 47.0 => ix <= 187 (e.g. 30,40,45)
    for cx in [30.0, 40.0, 45.0]:
        ix = int(np.floor(cx / height_raster.CELL_M))
        for iy in [24, 40, 80]:  # y centers 6.125,10.125,20.125 etc in [5,55]
            v = hmap.get((ix, iy))
            assert v is not None, f"expected road cell ({ix},{iy}) defined"
            assert abs(v - 0.0) <= 0.02, f"road cell ({ix},{iy}) v={v}"

    # High-side 0.5-2.0m from boundary: x_center in [50.5,52.0] => ix 202..207
    for cx in [50.75, 51.25, 51.75]:
        ix = int(np.floor(cx / height_raster.CELL_M))
        for iy in [24, 40, 80]:
            v = hmap.get((ix, iy))
            assert v is not None, f"expected high cell ({ix},{iy}) defined"
            assert abs(v - 0.15) <= 0.02, f"high cell ({ix},{iy}) v={v}"


def test_empty_no_data_transparent():
    hmap = height_raster.compute_height_above_road([])
    rgba = height_raster.render_height_rgba(hmap, x0=0.0, y0=0.0, cell=0.25, side=8)
    assert rgba.shape == (8, 8, 4)
    assert np.all(rgba[..., 3] == 0)


def test_clamp_low_and_high():
    hmap = {(0, 0): -1.0}
    rgba = height_raster.render_height_rgba(hmap, x0=0.0, y0=0.0, cell=0.25, side=4)
    assert tuple(rgba[3, 0, :3].tolist()) == (0x0F, 0x14, 0x33)
    assert int(rgba[3, 0, 3]) == 255

    hmap2 = {(0, 0): 0.3}
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
    keys = set(h1.keys()) & set(h2.keys())
    assert len(keys) > 100
    for k in list(keys)[:200]:
        assert abs(h1[k] - h2[k]) <= 0.02


def test_registration_orientation_mapping():
    x0, y0, cell, side = 10.0, 20.0, 0.5, 10
    x = 10.8
    y = 20.3
    col = int(np.floor((x - x0) / cell))
    row = int(side - 1 - np.floor((y - y0) / cell))
    ix = int(np.floor(x / height_raster.CELL_M))
    iy = int(np.floor(y / height_raster.CELL_M))
    hmap = {(ix, iy): 0.1}
    rgba = height_raster.render_height_rgba(hmap, x0=x0, y0=y0, cell=cell, side=side)
    assert int(rgba[row, col, 3]) == 255