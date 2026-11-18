import base64
import io
import json
import sys
import types

import numpy as np
from PIL import Image

import twin.labelraster as lr
from twin.dataset import DatasetConfig


def _block_cv2(monkeypatch):
    monkeypatch.setitem(sys.modules, "cv2", None)
    monkeypatch.setattr(lr, "_cv2", None, raising=False)
    monkeypatch.setattr(lr, "_cv2_tried", False, raising=False)


class _FakeBuf:
    def __init__(self, data):
        self._data = data

    def tobytes(self):
        return self._data


def _fake_cv2_module(calls):
    m = types.ModuleType("cv2")
    m.INTER_LINEAR = 1
    m.INTER_AREA = 2
    m.INTER_NEAREST = 0
    m.IMWRITE_JPEG_QUALITY = 1
    m.COLOR_RGB2BGR = 4
    m.error = Exception

    def GaussianBlur(arr, ksize, sigma):
        calls.append(("blur", tuple(np.asarray(arr).shape), tuple(ksize), float(sigma)))
        return np.asarray(arr, dtype=np.float32)

    def resize(arr, dsize, interpolation=None):
        w, h = dsize
        arr = np.asarray(arr)
        calls.append(("resize", tuple(arr.shape), (h, w), interpolation))
        if arr.ndim == 2:
            return np.zeros((h, w), dtype=arr.dtype)
        return np.zeros((h, w, arr.shape[2]), dtype=arr.dtype)

    def imencode(ext, arr, params=None):
        calls.append(("imencode", str(ext), tuple(np.asarray(arr).shape), tuple(params or [])))
        # produce a real decodable image of same shape/size
        a = np.asarray(arr)
        if a.ndim == 2:
            img = Image.fromarray(a.astype(np.uint8), mode="L")
        else:
            img = Image.fromarray(a.astype(np.uint8), mode="RGB")
        buf = io.BytesIO()
        if ext == ".png":
            img.save(buf, format="PNG")
        else:
            img.save(buf, format="JPEG", quality=82)
        return True, _FakeBuf(buf.getvalue())

    def cvtColor(arr, code):
        calls.append(("cvtColor", tuple(np.asarray(arr).shape), code))
        return np.asarray(arr)

    def warpAffine(arr, M, dsize, flags=None):
        w, h = dsize
        arr = np.asarray(arr)
        calls.append(("warpAffine", tuple(arr.shape), (h, w), flags))
        if arr.ndim == 2:
            return np.zeros((h, w), dtype=arr.dtype)
        return np.zeros((h, w, arr.shape[2]), dtype=arr.dtype)

    m.GaussianBlur = GaussianBlur
    m.resize = resize
    m.imencode = imencode
    m.cvtColor = cvtColor
    m.warpAffine = warpAffine
    return m


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


def test_helpers_prefer_cv2_when_available(monkeypatch):
    calls = []
    fake = _fake_cv2_module(calls)
    monkeypatch.setitem(sys.modules, "cv2", fake)
    monkeypatch.setattr(lr, "_cv2", None, raising=False)
    monkeypatch.setattr(lr, "_cv2_tried", False, raising=False)

    a = np.ones((4, 6), dtype=np.float32)
    b = lr._blur(a, 2.0)
    r = lr._resize(a, (8, 12), interpolation="linear")
    r_area = lr._resize(a, (8, 12), interpolation="area")
    enc = lr._encode(np.zeros((3, 5, 3), dtype=np.uint8), ".jpg")
    assert b.shape == a.shape
    assert r.shape == (8, 12)
    assert r_area.shape == (8, 12)
    assert "data:" not in enc
    assert base64.b64decode(enc)
    blur = next(c for c in calls if c[0] == "blur")
    assert blur[2] == (0, 0)
    assert blur[3] == 2.0
    area = [c for c in calls if c[0] == "resize" and c[3] == fake.INTER_AREA]
    assert len(area) == 1
    assert area[0][2] == (8, 12)
    jpeg = next(c for c in calls if c[0] == "imencode" and c[1] == ".jpg")
    assert jpeg[3] == (fake.IMWRITE_JPEG_QUALITY, 82)
    assert ("cvtColor", (3, 5, 3), fake.COLOR_RGB2BGR) in calls


def test_helpers_fallback_without_cv2_produce_valid_images(monkeypatch):
    _block_cv2(monkeypatch)
    a = np.tile(np.linspace(0, 255, 16, dtype=np.uint8), (8, 1)).astype(np.float32)
    b = lr._blur(a, 1.5)
    r = lr._resize(a, (10, 20), interpolation="area")
    enc_png = lr._encode((b[:4, :4]).astype(np.uint8), ".png")
    enc_jpg = lr._encode(np.dstack([r.astype(np.uint8)] * 3), ".jpg")
    assert b.shape == a.shape
    assert r.shape == (10, 20)
    for data, size in ((enc_png, (4, 4)), (enc_jpg, (20, 10))):
        img = Image.open(io.BytesIO(base64.b64decode(data)))
        assert img.size == size
        assert "data:" not in data


def test_encode_raw_base64_decodes_to_right_size(monkeypatch):
    _block_cv2(monkeypatch)
    arr_l = np.full((7, 9), 5, dtype=np.uint8)
    arr_rgb = np.full((11, 13, 3), 7, dtype=np.uint8)
    for arr, ext, size in ((arr_l, ".png", (9, 7)), (arr_rgb, ".jpg", (13, 11))):
        data = lr._encode(arr, ext)
        assert not data.startswith("data:")
        raw = base64.b64decode(data)
        img = Image.open(io.BytesIO(raw))
        assert img.size == size


def test_blur_masked_matches_masked_normalisation(monkeypatch):
    _block_cv2(monkeypatch)
    from scipy import ndimage

    a = np.array(
        [[1.0, 2.0, 0.0, 4.0], [0.0, 3.0, 5.0, 0.0], [2.0, 0.0, 1.0, 6.0], [0.0, 4.0, 0.0, 2.0]],
        dtype=np.float32,
    )
    m = np.array([[1, 1, 0, 1], [0, 1, 1, 0], [1, 0, 1, 1], [0, 1, 0, 1]], dtype=np.float32)
    sigma = 1.0
    out = lr._blur_masked(a, m, sigma)
    num = ndimage.gaussian_filter(a * m, sigma=sigma)
    den = ndimage.gaussian_filter(m, sigma=sigma) + 1e-6
    expected = (num / den).astype(np.float32)
    assert out.shape == a.shape
    np.testing.assert_allclose(out, expected, rtol=1e-6, atol=1e-6)


def test_try_cv2_returns_none_for_partial_fake(monkeypatch):
    calls = []
    partial = _fake_cv2_module(calls)
    del partial.warpAffine
    monkeypatch.setitem(sys.modules, "cv2", partial)
    monkeypatch.setattr(lr, "_cv2", None, raising=False)
    monkeypatch.setattr(lr, "_cv2_tried", False, raising=False)
    assert lr._try_cv2() is None
    assert lr._try_cv2() is None
    assert calls == []
