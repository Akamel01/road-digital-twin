import base64
import io
import json
import sys

import numpy as np
from PIL import Image

import twin.labelraster as lr
from twin.dataset import DatasetConfig


def _block_cv2(monkeypatch):
    monkeypatch.setitem(sys.modules, "cv2", None)


def test_import_labeltool_without_cv2(monkeypatch):
    _block_cv2(monkeypatch)
    # remove cached
    for m in ["twin.labeltool", "twin.labelraster"]:
        sys.modules.pop(m, None)
    import twin.labeltool  # noqa: F401
    assert "cv2" not in sys.modules or sys.modules.get("cv2") is None


def test_import_labelraster_without_cv2(monkeypatch):
    _block_cv2(monkeypatch)
    sys.modules.pop("twin.labelraster", None)
    import twin.labelraster  # noqa: F401
    assert True


def test_blank_window_full_size_raw_base64():
    missing = ["x"]
    d = lr.blank_window("site", 1.0, 2.0, missing)
    assert d["no_imagery"] is True
    for key in ("intensity", "ortho", "fused", "height"):
        assert "data:" not in d[key]
        img = Image.open(io.BytesIO(base64.b64decode(d[key])))
        assert img.size == (1600, 1500)
    assert d["frames"] == []
    assert d["fuse_stats"] == {}
    assert d["missing"] == missing
    assert d["name"] == "site"
    assert d["window"] == {"x0": 1.0, "y1": 2.0, "g": 0.05, "w": 1600, "h": 1500}


def _make_laz(path, x0, y1, nx=200, ny=100, intensity_range=None):
    import laspy

    xs = np.linspace(x0, x0 + 10, nx)
    ys = np.linspace(y1 - 10, y1, ny)
    xx, yy = np.meshgrid(xs, ys)
    xx = xx.ravel()
    yy = yy.ravel()
    z = np.zeros_like(xx)
    if intensity_range is None:
        intensity = np.ones_like(xx) * 100
    else:
        lo, hi = intensity_range
        intensity = np.linspace(lo, hi, xx.size)
    header = laspy.LasHeader(point_format=3, version="1.2")
    las = laspy.LasData(header)
    las.x = xx
    las.y = yy
    las.z = z
    las.intensity = intensity.astype(np.uint16)
    path.parent.mkdir(parents=True, exist_ok=True)
    las.write(str(path))


def test_collect_drive_without_ortho_keeps_intensity_and_height(tmp_path, monkeypatch):
    _block_cv2(monkeypatch)
    run_dir = tmp_path / "run1"
    _make_laz(run_dir / "4_ground" / "ground.laz", 0.0, 20.0)
    dd = lr._collect_drive(run_dir, 0.0, 20.0, width=1600, height=1500, cell=0.05)
    assert dd["raw"] is None
    assert dd["obs"] is None
    assert dd["si"].shape == (1500, 1600)


def test_sparse_drive_skipped(tmp_path):
    run_dir = tmp_path / "run1"
    _make_laz(run_dir / "4_ground" / "ground.laz", 0.0, 20.0, nx=10, ny=10)
    try:
        lr._collect_drive(run_dir, 0.0, 20.0)
        assert False, "expected sparse skip"
    except OSError as e:
        assert "sparse" in str(e)
        assert "points < 20000" in str(e)
    data = lr.export_window(tmp_path, [run_dir], site="s", x0=0.0, y1=20.0)
    assert data["no_imagery"] is True
    assert any("sparse" in m and "points < 20000" in m for m in data["missing"]) or data["missing"] == ["no drives"]


def test_export_window_without_cv2_keeps_lidar_and_height(tmp_path, monkeypatch):
    _block_cv2(monkeypatch)
    prev = Image.MAX_IMAGE_PIXELS
    run_dir = tmp_path / "run1"
    _make_laz(run_dir / "4_ground" / "ground.laz", 0.0, 20.0)
    od = run_dir / "6_colour"
    od.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", (100, 100), (255, 0, 0, 255)).save(od / "ortho.png")
    (od / "ortho.pgw").write_text("0.05 0 0 -0.05 0.025 19.975\n")
    data = lr.export_window(tmp_path, [run_dir], site="s", x0=0.0, y1=20.0)
    assert "opencv unavailable: fused/ortho skipped" in data["missing"]
    assert data["no_imagery"] is False
    for key in ("intensity", "height"):
        Image.open(io.BytesIO(base64.b64decode(data[key])))
    assert Image.MAX_IMAGE_PIXELS == prev


def test_export_window_records_cv2_error_per_drive(tmp_path, monkeypatch):
    run1 = tmp_path / "runA"
    run2 = tmp_path / "runB"
    _make_laz(run1 / "4_ground" / "ground.laz", 0.0, 20.0)
    _make_laz(run2 / "4_ground" / "ground.laz", 0.0, 20.0)
    od = run1 / "6_colour"
    od.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", (50, 50), (0, 0, 0, 255)).save(od / "ortho.png")
    (od / "ortho.pgw").write_text("0.05 0 0 -0.05 0.025 19.975\n")
    od2 = run2 / "6_colour"
    od2.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", (50, 50), (0, 0, 0, 255)).save(od2 / "ortho.png")
    (od2 / "ortho.pgw").write_text("0.05 0 0 -0.05 0.025 19.975\n")

    def patched(drive, **kw):
        name = drive["run_name"] if isinstance(drive, dict) else str(drive)
        if name == "runA":
            raise lr.RasterError(name)
        return {"used": False}, None

    monkeypatch.setattr(lr, "_fuse", patched)
    data = lr.export_window(tmp_path, [run1, run2], site="s", x0=0.0, y1=20.0)
    assert data["no_imagery"] is False
    assert any("runA" in m and "raster error" in m for m in data["missing"])
    assert "opencv unavailable: fused/ortho skipped" not in data["missing"]
    Image.open(io.BytesIO(base64.b64decode(data["intensity"])))


def test_export_window_all_raster_errors_keep_lidar(tmp_path, monkeypatch):
    run_dir = tmp_path / "run1"
    _make_laz(run_dir / "4_ground" / "ground.laz", 0.0, 20.0, intensity_range=(100, 60000))
    od = run_dir / "6_colour"
    od.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", (50, 50), (0, 0, 0, 255)).save(od / "ortho.png")
    (od / "ortho.pgw").write_text("0.05 0 0 -0.05 0.025 19.975\n")

    def patched(drive, **kw):
        name = drive["run_name"] if isinstance(drive, dict) else str(drive)
        raise lr.RasterError(name)

    monkeypatch.setattr(lr, "_fuse", patched)
    data = lr.export_window(tmp_path, [run_dir], site="s", x0=0.0, y1=20.0)
    assert data["no_imagery"] is False
    assert data["missing"] == ["run1: raster error"]
    img = Image.open(io.BytesIO(base64.b64decode(data["intensity"])))
    assert img.size == (1600, 1500)
    arr = np.asarray(img)
    assert arr.max() > 0
    assert float(arr.std()) > 0.0


def test_export_window_data_is_json_serialisable(tmp_path):
    run_dir = tmp_path / "run1"
    _make_laz(run_dir / "4_ground" / "ground.laz", 0.0, 20.0)
    data = lr.export_window(tmp_path, [run_dir], site="s", x0=0.0, y1=20.0)
    json.dumps(data)


def test_export_window_frames_use_run_names(tmp_path):
    run_dir = tmp_path / "run1"
    _make_laz(run_dir / "4_ground" / "ground.laz", 0.0, 20.0)
    (run_dir / "3_align").mkdir(parents=True, exist_ok=True)
    (run_dir / "1_load").mkdir(parents=True, exist_ok=True)
    pose = [[1, 0, 0, 40], [0, 1, 0, -40], [0, 0, 1, 0], [0, 0, 0, 1]]
    (run_dir / "3_align" / "poses.json").write_text(
        json.dumps(
            {
                "poses": [
                    {"timestamp_us": 1000, "matrix": pose},
                    {"timestamp_us": 2000, "matrix": pose},
                ]
            }
        )
    )
    img_dir = tmp_path / "nuscenes" / "samples"
    img_dir.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (1600, 900), (10, 20, 30)).save(img_dir / "cam.jpg")
    cams = {
        "cameras": [
            {
                "channel": "CAM_FRONT",
                "timestamp_us": 1500,
                "image": "samples/cam.jpg",
                "intrinsics": [[800, 0, 800], [0, 800, 450], [0, 0, 1]],
                "extrinsics": {
                    "translation": [0, 0, 0],
                    "rotation_wxyz": [0.7071067811865476, -0.7071067811865476, 0, 0],
                },
            }
        ]
    }
    (run_dir / "1_load" / "cameras.json").write_text(json.dumps(cams))
    data = lr.export_window(
        tmp_path, [run_dir], site="s", x0=0.0, y1=20.0, nuscenes_root=tmp_path / "nuscenes"
    )
    assert data["no_imagery"] is False
    assert len(data["frames"]) >= 1
    f = data["frames"][0]
    assert f["run"] == "run1"
    assert isinstance(f["K"], list)
    assert isinstance(f["c2w"], list)
    json.dumps(data)


def test_export_window_uses_dataset_root_default(monkeypatch, tmp_path):
    target = str(tmp_path / "nuscenes-root")
    monkeypatch.setenv("NUSCENES_ROOT", target)
    assert lr._nuscenes_root(None) == target
    assert lr._nuscenes_root(None) == DatasetConfig.from_env().root
    assert lr._nuscenes_root(None) != "/data/nuscenes" or target == "/data/nuscenes"
