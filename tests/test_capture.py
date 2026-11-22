"""Posed Capture adapter: synthetic merged area -> recon-core capture."""

from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np
import pytest

from twin.capture import build_area_capture
from twin.cli import main


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
        "poses": [{"sweep": 0, "timestamp_us": 1000, "matrix": np.eye(4).tolist()}],
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
