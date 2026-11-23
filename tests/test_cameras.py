"""posed_cameras: a synthetic load/align folder through the public interface."""

import json

import numpy as np

from twin.cameras import PosedCamera, camera_count, posed_cameras

K = [[100.0, 0, 50], [0, 100.0, 40], [0, 0, 1]]
EXT = {"translation": [1.0, 0.0, 2.0], "rotation_wxyz": [1.0, 0.0, 0.0, 0.0]}


def _ego(x: float) -> list[list[float]]:
    m = np.eye(4)
    m[0, 3] = x
    return m.tolist()


def _folders(tmp_path, cam_times):
    load, align = tmp_path / "1_load", tmp_path / "3_align"
    load.mkdir()
    align.mkdir()
    # two sweeps, 1 s apart, ego moves 10 m in x
    (align / "poses.json").write_text(
        json.dumps({"poses": [{"timestamp_us": 1_000_000, "matrix": _ego(0.0)}, {"timestamp_us": 2_000_000, "matrix": _ego(10.0)}]})
    )
    cams = [
        {"channel": f"CAM_{i}", "timestamp_us": t, "image": f"s/{i}.jpg", "intrinsics": K, "extrinsics": EXT}
        for i, t in enumerate(cam_times)
    ]
    (load / "cameras.json").write_text(json.dumps({"cameras": cams}))
    return load, align


def test_span_rule_drops_cameras_outside_sweeps(tmp_path):
    load, align = _folders(tmp_path, [500_000, 1_000_000, 1_500_000, 2_000_000, 2_500_000])
    got = posed_cameras(load, align)
    assert [c.t_us for c in got] == [1_000_000, 1_500_000, 2_000_000]
    assert [c.channel for c in got] == ["CAM_1", "CAM_2", "CAM_3"]
    assert camera_count(load) == 5


def test_interpolates_and_composes_extrinsic(tmp_path):
    load, align = _folders(tmp_path, [1_500_000])
    (cam,) = posed_cameras(load, align)
    assert isinstance(cam, PosedCamera)
    assert cam.image == "s/0.jpg"
    np.testing.assert_allclose(cam.K, K)
    # ego at the midpoint (x=5) @ extrinsic (+1, 0, +2)
    np.testing.assert_allclose(cam.c2w[:3, 3], [6.0, 0.0, 2.0])
    np.testing.assert_allclose(cam.c2w[:3, :3], np.eye(3), atol=1e-12)


def test_correction_left_multiplies(tmp_path):
    load, align = _folders(tmp_path, [1_250_000, 1_750_000])
    c = np.eye(4)
    th = 0.3
    c[:2, :2] = [[np.cos(th), -np.sin(th)], [np.sin(th), np.cos(th)]]
    c[:3, 3] = [100.0, -20.0, 3.0]
    plain = posed_cameras(load, align)
    corrected = posed_cameras(load, align, correction=c)
    for a, b in zip(plain, corrected, strict=True):
        np.testing.assert_allclose(b.c2w, c @ a.c2w, atol=1e-9)
