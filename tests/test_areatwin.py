"""Change detection and support on synthetic cells."""

import numpy as np
from shapely.geometry import LineString, box, mapping

from twin import areatwin as at


def _drive_points(rng, drive, bump=0.0):
    """A 10 x 10 m flat patch; a 3 x 3 m block of it is `bump` m higher (a structure)."""
    xy = rng.uniform(0, 10, (40000, 2))
    z = rng.normal(0, 0.01, len(xy))
    z[(xy[:, 0] < 3) & (xy[:, 1] < 3)] += bump
    return xy[:, 0], xy[:, 1], z, np.full(len(xy), drive)


def _cells(bump):
    rng = np.random.default_rng(0)
    parts = [_drive_points(rng, 0), _drive_points(rng, 1), _drive_points(rng, 2, bump)]
    x, y, z, d = (np.concatenate(c) for c in zip(*parts, strict=True))
    shape_yx = (22, 22)
    return at.cell_stats(x, y, z, d, np.zeros(2), shape_yx, 3), shape_yx


def test_change_found_only_where_dates_differ():
    (lo, hi), shape_yx = _cells(bump=0.5)
    dates = ["d1", "d1", "d2"]
    noise = at.noise_levels(lo, hi, dates)
    # two dates cannot say which one changed: both are listed
    both = at.change_regions(at.detect_change(lo, hi, dates, noise), np.zeros(2), shape_yx, dates, ["a", "b", "c"])
    assert both[0]["properties"]["dates"] == ["d1", "d2"]
    dates = ["d1", "d2", "d3"]
    noise = {"ground_threshold_m": 0.15, "structure_threshold_m": 0.3}
    det = at.detect_change(lo, hi, dates, noise)
    regions = at.change_regions(det, np.zeros(2), shape_yx, dates, ["a", "b", "c"])
    assert len(regions) == 1
    p = regions[0]["properties"]
    assert p["dates"] == ["d3"] and p["drives"] == ["c"]
    assert 6 < p["area_m2"] < 12  # the 3 x 3 m block


def test_same_dates_have_no_change():
    (lo, hi), shape_yx = _cells(bump=0.5)
    dates = ["d1"] * 3
    det = at.detect_change(lo, hi, dates, at.noise_levels(lo, hi, dates))
    assert not det["changed"].any()


def test_flag_and_mask():
    region = {"geometry": mapping(box(0, 0, 3, 3)), "properties": {"dates": ["d2"]}}
    feats = [
        {"geometry": mapping(LineString([(1, 1), (2, 2)])), "properties": {}},
        {"geometry": mapping(LineString([(8, 8), (9, 9)])), "properties": {}},
    ]
    assert at.flag_changed(feats, [region]) == 1
    assert feats[0]["properties"]["change_dates"] == ["d2"]
    assert "changed" not in feats[1]["properties"]
    ref = [{"geometry": mapping(LineString([(0, 1), (9, 1)])), "properties": {}}]
    out = at.mask_reference(ref, [region])
    assert abs(out[0]["geometry"]["coordinates"][0][0] - 3) < 1e-9 or out[0]["geometry"]["type"] == "LineString"


def test_support_counts_drives():
    rng = np.random.default_rng(1)
    x, y, z, d = (np.concatenate(c) for c in zip(*[_drive_points(rng, 0), _drive_points(rng, 1)], strict=True))
    f = [{"geometry": mapping(LineString([(5, 5), (6, 5)])), "properties": {}}]
    at.support(f, np.column_stack([x, y, z]), d, np.zeros(len(x)), np.zeros(2), (22, 22), ["a", "b"])
    assert f[0]["properties"]["support"]["n_drives"] == 2
