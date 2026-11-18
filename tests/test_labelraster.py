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
    assert "data:" not in d["intensity"]
    for key in ("intensity", "ortho", "fused", "height"):
        img = Image.open(io.BytesIO(base64.b64decode(d[key])))
        assert img.size == (1600, 1500)
    assert d["frames"] == []
    assert d["missing"] == missing


def _make_laz(path, x0, y1):
    import laspy

    # 20k+ points in window
    xs = np.linspace(x0, x0 + 10, 200)
    ys = np.linspace(y1 - 10, y1, 200)
    xx, yy = np.meshgrid(xs, ys)
    xx = xx.ravel()
    yy = yy.ravel()
    z = np.zeros_like(xx)
    intensity = np.ones_like(xx) * 100
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
    # no ortho
    dd = lr._collect_drive(run_dir, 0.0, 20.0, width=1600, height=1500, cell=0.05)
    assert dd["raw"] is None
    assert dd["obs"] is None
    assert dd["si"].shape == (1500, 1600)


def test_export_window_without_cv2_keeps_lidar_and_height(tmp_path, monkeypatch):
    _block_cv2(monkeypatch)
    run_dir = tmp_path / "run1"
    _make_laz(run_dir / "4_ground" / "ground.laz", 0.0, 20.0)
    # ortho present
    od = run_dir / "6_colour"
    od.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGBA", (100, 100), (255, 0, 0, 255))
    img.save(od / "ortho.png")
    (od / "ortho.pgw").write_text("0.05 0 0 -0.05 0.025 19.975\n")
    # fix pgw: need valid; use simple
    data = lr.export_window(tmp_path, [run_dir], site="s", x0=0.0, y1=20.0)
    assert "opencv unavailable: fused/ortho skipped" in data["missing"]
    assert data["no_imagery"] is False
    for key in ("intensity", "height"):
        Image.open(io.BytesIO(base64.b64decode(data[key])))


def test_export_window_records_cv2_error_per_drive(tmp_path, monkeypatch):
    # cv2 available (not blocked) but _fuse raises RasterError for first run
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

    orig_fuse = lr._fuse

    def patched(drive, **kw):
        name = drive["run_name"] if isinstance(drive, dict) else str(drive)
        if name == "runA":
            raise lr.RasterError(name)
        return orig_fuse(drive, **kw)

    monkeypatch.setattr(lr, "_fuse", patched)
    data = lr.export_window(tmp_path, [run1, run2], site="s", x0=0.0, y1=20.0)
    # one survived
    assert isinstance(data, dict)
    # missing mentions runA
    assert any("runA" in m for m in data["missing"])


def test_export_window_data_is_json_serialisable(tmp_path):
    run_dir = tmp_path / "run1"
    _make_laz(run_dir / "4_ground" / "ground.laz", 0.0, 20.0)
    data = lr.export_window(tmp_path, [run_dir], site="s", x0=0.0, y1=20.0)
    json.dumps(data)


def test_export_window_frames_use_run_names(tmp_path):
    # no frames because no poses; just ensure structure
    run_dir = tmp_path / "run1"
    _make_laz(run_dir / "4_ground" / "ground.laz", 0.0, 20.0)
    data = lr.export_window(tmp_path, [run_dir], site="s", x0=0.0, y1=20.0)
    assert isinstance(data["frames"], list)


def test_export_window_uses_dataset_root_default(monkeypatch):
    # _nuscenes_root(None) -> env root
    assert lr._nuscenes_root(None) == DatasetConfig.from_env().root
