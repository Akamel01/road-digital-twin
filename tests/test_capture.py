"""Posed Capture adapter: synthetic merged area -> recon-core capture."""

from __future__ import annotations

import json
import math
import os
from pathlib import Path

import numpy as np
import pytest

from twin.cameras import camera_count
from twin.capture import build_area_capture
from twin.cli import main
from twin.stages.load import quat_to_matrix
from twin.stages.zbuffer import matrix_to_quat


def _write_merged(base: Path, *, drive_values=None, n_drives=2) -> Path:
    merged = base / "areas" / "demo-merged"
    (merged / "drives").mkdir(parents=True)
    # two drives, simple points
    x = np.array([100.2, 101.4, 102.8, 103.0], dtype=float)
    y = np.array([200.1, 200.9, 201.2, 202.0], dtype=float)
    z = np.array([10.0, 10.5, 9.8, 11.0], dtype=float)
    drive = np.array(drive_values if drive_values is not None else [0, 0, 1, 1], dtype=np.int64)
    np.savez(merged / "merged.npz", x=x, y=y, z=z, intensity=np.ones_like(x), drive=drive)

    drives = []
    for i in range(n_drives):
        scene = f"scene-{i:04d}"
        drives.append({"scene": scene, "date": f"2018-05-0{i+1}", "scene_token": f"tok{i}"})
        ddir = merged / "drives" / scene
        (ddir / "1_load").mkdir(parents=True)
        (ddir / "3_align").mkdir(parents=True)
        # identity ego pose at two timestamps
        poses = {
            "crs": "EPSG:32619",
            "poses": [
                {"sweep": 0, "timestamp_us": 1000 + i * 100, "matrix": np.eye(4).tolist()},
                {"sweep": 1, "timestamp_us": 2000 + i * 100, "matrix": np.eye(4).tolist()},
            ],
        }
        (ddir / "3_align" / "poses.json").write_text(json.dumps(poses))
        rel = f"samples/CAM_FRONT/{scene}.jpg"
        cameras = {
            "cameras": [
                {
                    "channel": "CAM_FRONT",
                    "sample_token": f"s{i}",
                    "timestamp_us": 1000 + i * 100,
                    "image": rel,
                    "intrinsics": [[500.0, 0.0, 320.0], [0.0, 500.0, 240.0], [0.0, 0.0, 1.0]],
                    "extrinsics": {"translation": [0.0, 0.0, 1.0], "rotation_wxyz": [1.0, 0.0, 0.0, 0.0]},
                }
            ]
        }
        (ddir / "1_load" / "cameras.json").write_text(json.dumps(cameras))
        img = base / "nuscenes" / rel
        img.parent.mkdir(parents=True, exist_ok=True)
        img.write_bytes(b"")
    (merged / "drives.json").write_text(json.dumps(drives))
    return merged


def _write_area(base: Path, name="demo") -> None:
    areas = base / "areas"
    areas.mkdir(parents=True, exist_ok=True)
    (areas / f"{name}.json").write_text(json.dumps({"name": name, "polygon": {"type": "Polygon", "coordinates": [[[0,0],[1,0],[1,1],[0,0]]]}}))


SWEEP_A = 1_000_000
SWEEP_B = 2_000_000
CAM_TIMES = [500_000, 1_000_000, 1_500_000, 2_000_000, 2_500_000]
SYNTH_K = [[500.0, 0.0, 320.0], [0.0, 500.0, 240.0], [0.0, 0.0, 1.0]]
SYNTH_EXT = {"translation": [1.0, 0.0, 2.0], "rotation_wxyz": [1.0, 0.0, 0.0, 0.0]}


def _ego(x: float) -> list[list[float]]:
    m = np.eye(4)
    m[0, 3] = x
    return m.tolist()


def _write_one_drive_merged(base: Path, cam_times=CAM_TIMES) -> Path:
    merged = base / "areas" / "demo-merged"
    (merged / "drives").mkdir(parents=True)
    np.savez(
        merged / "merged.npz",
        x=np.array([100.0], dtype=float),
        y=np.array([200.0], dtype=float),
        z=np.array([10.0], dtype=float),
        intensity=np.ones(1),
        drive=np.array([0], dtype=np.int64),
    )
    scene = "scene-0000"
    (merged / "drives.json").write_text(
        json.dumps([{"scene": scene, "date": "2018-05-01", "scene_token": "tok0"}])
    )
    ddir = merged / "drives" / scene
    (ddir / "1_load").mkdir(parents=True)
    (ddir / "3_align").mkdir(parents=True)
    poses = {
        "crs": "EPSG:32619",
        "poses": [
            {"sweep": 0, "timestamp_us": SWEEP_A, "matrix": _ego(0.0)},
            {"sweep": 1, "timestamp_us": SWEEP_B, "matrix": _ego(10.0)},
        ],
    }
    (ddir / "3_align" / "poses.json").write_text(json.dumps(poses))
    cameras = {
        "cameras": [
            {
                "channel": "CAM_FRONT",
                "sample_token": f"s{i}",
                "timestamp_us": t,
                "image": f"samples/CAM_FRONT/{t}.jpg",
                "intrinsics": SYNTH_K,
                "extrinsics": SYNTH_EXT,
            }
            for i, t in enumerate(cam_times)
        ]
    }
    (ddir / "1_load" / "cameras.json").write_text(json.dumps(cameras))
    for t in cam_times:
        img = base / "nuscenes" / "samples" / "CAM_FRONT" / f"{t}.jpg"
        img.parent.mkdir(parents=True, exist_ok=True)
        img.write_bytes(b"")
    return merged


def test_capture_meta_and_local_coordinates(tmp_path):
    merged = _write_merged(tmp_path)
    out = tmp_path / "areas" / "demo-capture"
    build_area_capture(merged, out, "demo", dataroot=tmp_path / "nuscenes")

    meta = json.loads((out / "capture.json").read_text())
    assert meta["version"] == 1
    assert meta["epsg"] == 32619
    assert meta["units"] == "metres"
    assert meta["origin_offset"] == [100.0, 200.0, 0.0]
    assert meta["source"] == "area:demo"
    assert meta["data_licence"] == "CC BY-NC-SA"
    assert meta["name"] == "demo"
    assert "T" in meta["created"]
    assert meta["captures"] == ["scene-0000", "scene-0001"]

    from recon_core.capture import read_lidar

    lidar = read_lidar(out / "lidar.laz")
    with np.load(merged / "merged.npz") as f:
        abs_xyz = np.column_stack([f["x"], f["y"], f["z"]])
    np.testing.assert_allclose(lidar.xyz, abs_xyz - np.array([100.0, 200.0, 0.0]))


def test_capture_loads_through_core(tmp_path):
    merged = _write_merged(tmp_path)
    out = tmp_path / "areas" / "demo-capture"
    build_area_capture(merged, out, "demo", dataroot=tmp_path / "nuscenes")

    from recon_core.capture import load_capture

    cap = load_capture(out)
    assert cap.meta.epsg == 32619
    assert len(cap.colmap.images) > 0
    # Rewritten for #398, not deleted: bytes are never copied, every image is a link.
    for ext in ("*.jpg", "*.png", "*.JPG", "*.PNG"):
        for path in out.rglob(ext):
            assert path.is_symlink(), path
    linked = list(out.rglob("*.jpg"))
    assert len(linked) == len(cap.colmap.images)
    dataroot = (tmp_path / "nuscenes").resolve()
    for im in cap.colmap.images.values():
        scene, channel, _ = im.name.split("/")
        assert os.path.samefile(out / "images" / im.name, dataroot / "samples" / channel / f"{scene}.jpg")


def test_colmap_image_names_end_with_jpg(tmp_path):
    merged = _write_merged(tmp_path)
    out = tmp_path / "areas" / "demo-capture"
    build_area_capture(merged, out, "demo", dataroot=tmp_path / "nuscenes")

    from recon_core.capture import load_capture

    cap = load_capture(out)
    assert cap.colmap.images
    for img in cap.colmap.images.values():
        assert img.name.endswith(".jpg")


def test_lidar_capture_index_matches_drives(tmp_path):
    merged = _write_merged(tmp_path)
    out = tmp_path / "areas" / "demo-capture"
    build_area_capture(merged, out, "demo", dataroot=tmp_path / "nuscenes")

    from recon_core.capture import read_lidar

    lidar = read_lidar(out / "lidar.laz")
    with np.load(merged / "merged.npz") as f:
        drive = f["drive"].astype(np.int32)
    np.testing.assert_array_equal(lidar.capture_index, drive)


def test_camera_projection_round_trip(tmp_path):
    merged = _write_merged(tmp_path)
    out = tmp_path / "areas" / "demo-capture"
    build_area_capture(merged, out, "demo", dataroot=tmp_path / "nuscenes")

    from recon_core.capture import load_capture

    cap = load_capture(out)
    # identity ego pose, camera extrinsic translation [0,0,1], rotation identity.
    # Absolute camera center C=[0,0,1], origin_offset=[100,200,0] => local C=[-100,-200,1].
    # Local point [1,2,2] => camera coords [101,202,1].
    point_local = np.array([1.0, 2.0, 2.0])
    K = np.array([[500.0, 0.0, 320.0], [0.0, 500.0, 240.0], [0.0, 0.0, 1.0]])
    expected = K @ np.array([101.0, 202.0, 1.0])
    expected_uv = expected[:2] / expected[2]

    # Find the CAM_FRONT image for scene-0000
    img = next(i for i in cap.colmap.images.values() if i.name.startswith("scene-0000/CAM_FRONT/"))
    cam = cap.colmap.cameras[img.camera_id]
    if cam.model == "SIMPLE_PINHOLE":
        K2 = np.array([[cam.params[0], 0, cam.params[1]], [0, cam.params[0], cam.params[2]], [0, 0, 1]], dtype=float)
    else:
        assert cam.model == "PINHOLE"
        K2 = np.array([[cam.params[0], 0, cam.params[2]], [0, cam.params[1], cam.params[3]], [0, 0, 1]], dtype=float)
    np.testing.assert_allclose(K2, K)

    q = np.array(img.qvec, dtype=float)
    R = _qvec_to_R(q)
    t = np.array(img.tvec, dtype=float)
    p_cam = R @ point_local + t
    uv = (K2 @ p_cam)[:2] / p_cam[2]
    np.testing.assert_allclose(uv, expected_uv, atol=1e-6)


def _qvec_to_R(q):
    w, x, y, z = q / np.linalg.norm(q)
    return np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)],
            [2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)],
            [2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)],
        ],
        dtype=float,
    )


def test_bad_drive_index_rejected(tmp_path):
    merged = _write_merged(tmp_path, drive_values=[0, 1, 2, 1], n_drives=2)
    out = tmp_path / "areas" / "demo-capture"
    with pytest.raises(ValueError, match="drive index out of range"):
        build_area_capture(merged, out, "demo", dataroot=tmp_path / "nuscenes")
    assert not out.exists()


def test_capture_command_exit_codes(tmp_path, capsys, monkeypatch):
    # missing area/merged -> 2
    rc = main(["capture", "area", "demo", "--store", str(tmp_path / "store")])
    assert rc == 2

    base = tmp_path / "store"
    _write_merged(base)
    _write_area(base, "demo")
    monkeypatch.setenv("NUSCENES_ROOT", str(base / "nuscenes"))
    rc = main(["capture", "area", "demo", "--store", str(base)])
    assert rc == 0
    captured = capsys.readouterr()
    out_path = Path(captured.out.strip())
    assert out_path.name == "demo-capture"
    assert (out_path / "capture.json").is_file()
    assert len(list((out_path / "images").rglob("*.jpg"))) == 2


def test_capture_links_all_images_for_recon_core(tmp_path):
    """build_cameras(cap, out) is the consumer that failed on the box for #398."""
    merged = _write_merged(tmp_path)
    out = tmp_path / "areas" / "demo-capture"
    build_area_capture(merged, out, "demo", dataroot=tmp_path / "nuscenes")

    from recon_core.capture import load_capture
    from recon_core.nodes.splat import build_cameras

    cap = load_capture(out)
    assert cap.colmap.images
    dataroot = (tmp_path / "nuscenes").resolve()
    views = build_cameras(cap, out)  # raises the ticket's own missing-image error
    assert len(views) == len(cap.colmap.images)
    for v in views:
        scene, channel, _ = v.name.split("/")
        source = dataroot / "samples" / channel / f"{scene}.jpg"
        assert v.path == out / "images" / v.name
        assert v.path.exists()
        assert Path(os.path.realpath(v.path)) == source
        assert os.path.samefile(v.path, source)  # no copy: the link is the dataroot file
        assert Path(os.readlink(v.path)).is_absolute()


def test_link_images_reports_first_missing(tmp_path):
    from twin.capture import link_images

    good = tmp_path / "nuscenes" / "samples" / "CAM_FRONT" / "good.jpg"
    good.parent.mkdir(parents=True)
    good.write_bytes(b"")
    missing_src = tmp_path / "nuscenes" / "samples" / "CAM_FRONT" / "absent.jpg"
    sources = {
        "scene-0000/CAM_FRONT/1000.jpg": missing_src,
        "scene-0001/CAM_FRONT/1100.jpg": good,
    }
    images_dir = tmp_path / "capture" / "images"

    with pytest.raises(FileNotFoundError) as excinfo:
        link_images(images_dir, sources)

    msg = str(excinfo.value)
    assert "1 capture image(s) missing" in msg
    assert "first missing: 'scene-0000/CAM_FRONT/1000.jpg'" in msg
    assert str(missing_src) in msg
    assert not images_dir.exists()  # collect-then-write: nothing was linked


def test_capture_missing_image_rejected(tmp_path):
    merged = _write_merged(tmp_path)
    (tmp_path / "nuscenes" / "samples" / "CAM_FRONT" / "scene-0001.jpg").unlink()
    out = tmp_path / "areas" / "demo-capture"

    with pytest.raises(FileNotFoundError) as excinfo:
        build_area_capture(merged, out, "demo", dataroot=tmp_path / "nuscenes")

    msg = str(excinfo.value)
    assert "1 capture image(s) missing" in msg
    assert "first missing: 'scene-0001/CAM_FRONT/1100.jpg'" in msg
    assert str(tmp_path / "nuscenes" / "samples" / "CAM_FRONT" / "scene-0001.jpg") in msg
    assert not out.exists()  # atomic: a failed build never publishes a partial capture


def test_capture_duplicate_image_name_different_path_rejected(tmp_path):
    merged = tmp_path / "areas" / "demo-merged"
    (merged / "drives" / "scene-0000" / "1_load").mkdir(parents=True)
    (merged / "drives" / "scene-0000" / "3_align").mkdir(parents=True)
    np.savez(
        merged / "merged.npz",
        x=np.array([100.0], dtype=float),
        y=np.array([200.0], dtype=float),
        z=np.array([10.0], dtype=float),
        intensity=np.ones(1),
        drive=np.array([0], dtype=np.int64),
    )
    (merged / "drives.json").write_text(
        json.dumps([{"scene": "scene-0000", "date": "2018-05-01", "scene_token": "tok0"}])
    )
    poses = {
        "crs": "EPSG:32619",
        "poses": [
            {"sweep": 0, "timestamp_us": 1000, "matrix": np.eye(4).tolist()},
            {"sweep": 1, "timestamp_us": 2000, "matrix": np.eye(4).tolist()},
        ],
    }
    (merged / "drives" / "scene-0000" / "3_align" / "poses.json").write_text(json.dumps(poses))
    rel_a = "samples/CAM_FRONT/scene-0000-a.jpg"
    rel_b = "samples/CAM_FRONT/scene-0000-b.jpg"
    cameras = {
        "cameras": [
            {
                "channel": "CAM_FRONT",
                "sample_token": "s0a",
                "timestamp_us": 1000,
                "image": rel_a,
                "intrinsics": [[500.0, 0.0, 320.0], [0.0, 500.0, 240.0], [0.0, 0.0, 1.0]],
                "extrinsics": {"translation": [0.0, 0.0, 1.0], "rotation_wxyz": [1.0, 0.0, 0.0, 0.0]},
            },
            {
                "channel": "CAM_FRONT",
                "sample_token": "s0b",
                "timestamp_us": 1000,
                "image": rel_b,
                "intrinsics": [[500.0, 0.0, 320.0], [0.0, 500.0, 240.0], [0.0, 0.0, 1.0]],
                "extrinsics": {"translation": [0.0, 0.0, 1.0], "rotation_wxyz": [1.0, 0.0, 0.0, 0.0]},
            },
        ]
    }
    (merged / "drives" / "scene-0000" / "1_load" / "cameras.json").write_text(json.dumps(cameras))
    for rel in (rel_a, rel_b):
        img = tmp_path / "nuscenes" / rel
        img.parent.mkdir(parents=True, exist_ok=True)
        img.write_bytes(b"")

    out = tmp_path / "areas" / "demo-capture"
    with pytest.raises(ValueError) as excinfo:
        build_area_capture(merged, out, "demo", dataroot=tmp_path / "nuscenes")

    msg = str(excinfo.value)
    assert "duplicate capture image name 'scene-0000/CAM_FRONT/1000.jpg'" in msg
    assert rel_a in msg
    assert rel_b in msg
    assert not out.exists()



def test_capture_writes_image_captures_for_multi_drive(tmp_path):
    merged = _write_merged(tmp_path)
    out = tmp_path / "areas" / "demo-capture"
    build_area_capture(merged, out, "demo", dataroot=tmp_path / "nuscenes")

    from recon_core.capture import load_capture

    cap = load_capture(out)
    meta = json.loads((out / "capture.json").read_text())
    mapping = meta["image_captures"]

    assert len(mapping) == 2
    assert set(mapping) == {im.name for im in cap.colmap.images.values()}
    assert set(mapping.values()) == set(meta["captures"]) == {"scene-0000", "scene-0001"}
    assert mapping == {
        "scene-0000/CAM_FRONT/1000.jpg": "scene-0000",
        "scene-0001/CAM_FRONT/1100.jpg": "scene-0001",
    }
    assert dict(cap.meta.image_captures) == mapping


def _nearest_old_centre(t_us: int) -> np.ndarray:
    """Old nearest-sweep camera centre in local metres for this fixture.

    np.argmin picks the first sweep on the 1.5 s tie.
    """
    ego_x = 0.0 if abs(t_us - SWEEP_A) <= abs(t_us - SWEEP_B) else 10.0
    return np.array([ego_x + 1.0 - 100.0, -200.0, 2.0])


def test_capture_interpolates_pose_between_sweeps(tmp_path):
    merged = _write_one_drive_merged(tmp_path)
    out = tmp_path / "areas" / "demo-capture"
    build_area_capture(merged, out, "demo", dataroot=tmp_path / "nuscenes")

    from recon_core.capture import load_capture

    cap = load_capture(out)

    def colmap_centre(im) -> tuple[int, np.ndarray]:
        t_us = int(im.name.rsplit("/", 1)[1].removesuffix(".jpg"))
        R = _qvec_to_R(np.array(im.qvec, dtype=float))
        return t_us, -R.T @ np.array(im.tvec, dtype=float)

    centres = dict(colmap_centre(im) for im in cap.colmap.images.values())

    # ego interpolates to x=5 at 1.5 s; + extrinsic [1,0,2]; - origin [100,200,0]
    np.testing.assert_allclose(centres[1_500_000], [-94.0, -200.0, 2.0], atol=1e-9)
    # the old nearest-sweep rule ties at 1.5 s and picks the 1.0 s sweep: ego x=0
    old_nearest_centre = np.array([-99.0, -200.0, 2.0])
    assert float(np.linalg.norm(centres[1_500_000] - old_nearest_centre)) == pytest.approx(5.0)

    changes = {
        t_us: float(np.linalg.norm(c - _nearest_old_centre(t_us))) for t_us, c in centres.items()
    }
    assert set(changes) == {1_000_000, 1_500_000, 2_000_000}
    assert changes[1_000_000] == pytest.approx(0.0)
    assert changes[1_500_000] == pytest.approx(5.0)
    assert changes[2_000_000] == pytest.approx(0.0)
    largest = max(changes.values())
    assert largest == pytest.approx(5.0)
    print(
        "largest synthetic camera-position change "
        f"(nearest sweep -> interpolated, 1 s sweep gap): {largest:.1f} m"
    )


def test_capture_drops_images_outside_sweep_span(tmp_path):
    merged = _write_one_drive_merged(tmp_path)
    out = tmp_path / "areas" / "demo-capture"
    build_area_capture(merged, out, "demo", dataroot=tmp_path / "nuscenes")

    from recon_core.capture import load_capture

    cap = load_capture(out)
    expected = {
        "scene-0000/CAM_FRONT/1000000.jpg",
        "scene-0000/CAM_FRONT/1500000.jpg",
        "scene-0000/CAM_FRONT/2000000.jpg",
    }
    names = {im.name for im in cap.colmap.images.values()}
    assert names == expected
    assert "scene-0000/CAM_FRONT/500000.jpg" not in names
    assert "scene-0000/CAM_FRONT/2500000.jpg" not in names
    assert len(cap.colmap.images) == 3
    total = camera_count(merged / "drives" / "scene-0000" / "1_load")
    dropped = total - len(cap.colmap.images)
    assert total == 5
    assert dropped == 2
    mapping = dict(cap.meta.image_captures)
    assert set(mapping) == expected
    assert set(mapping.values()) == {"scene-0000"}
    assert not (out / "images" / "scene-0000" / "CAM_FRONT" / "500000.jpg").exists()
    assert not (out / "images" / "scene-0000" / "CAM_FRONT" / "2500000.jpg").exists()
    print(f"images dropped outside the sweep span: {dropped} of {total} (synthetic area)")


def _reference_qvec(R: np.ndarray) -> tuple[float, float, float, float]:
    """Ticket-required migration oracle: the pre-#433 _matrix_to_qvec algorithm, test-only."""
    tr = float(R[0, 0] + R[1, 1] + R[2, 2])
    if tr > 0:
        s = math.sqrt(tr + 1.0) * 2
        qw = 0.25 * s
        qx = (R[2, 1] - R[1, 2]) / s
        qy = (R[0, 2] - R[2, 0]) / s
        qz = (R[1, 0] - R[0, 1]) / s
    elif R[0, 0] > R[1, 1] and R[0, 0] > R[2, 2]:
        s = math.sqrt(1.0 + R[0, 0] - R[1, 1] - R[2, 2]) * 2
        qw = (R[2, 1] - R[1, 2]) / s
        qx = 0.25 * s
        qy = (R[0, 1] + R[1, 0]) / s
        qz = (R[0, 2] + R[2, 0]) / s
    elif R[1, 1] > R[2, 2]:
        s = math.sqrt(1.0 + R[1, 1] - R[0, 0] - R[2, 2]) * 2
        qw = (R[0, 2] - R[2, 0]) / s
        qx = (R[0, 1] + R[1, 0]) / s
        qy = 0.25 * s
        qz = (R[1, 2] + R[2, 1]) / s
    else:
        s = math.sqrt(1.0 + R[2, 2] - R[0, 0] - R[1, 1]) * 2
        qw = (R[1, 0] - R[0, 1]) / s
        qx = (R[0, 2] + R[2, 0]) / s
        qy = (R[1, 2] + R[2, 1]) / s
        qz = 0.25 * s
    q = np.array([qw, qx, qy, qz], dtype=float)
    q /= np.linalg.norm(q)
    return tuple(float(v) for v in q)


def test_matrix_to_quat_agrees_with_reference_up_to_sign():
    rng = np.random.default_rng(433)
    for _ in range(200):
        q = rng.normal(size=4)
        R = quat_to_matrix(q / np.linalg.norm(q))
        ref = np.array(_reference_qvec(R))
        got = matrix_to_quat(R)
        got_unit = got / np.linalg.norm(got)
        assert abs(float(np.dot(got_unit, ref))) == pytest.approx(1.0)
        np.testing.assert_allclose(quat_to_matrix(got), R, atol=1e-9)
