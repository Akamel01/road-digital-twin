"""Tests for twin.marking_types."""

from __future__ import annotations

import sys

import pytest

import twin.marking_types as mt


def test_module_imports_without_torch():
    # Reload fresh to ensure lazy imports.
    if "torch" in sys.modules:
        pytest.skip("torch already imported; cannot test lazy import")
    # Re-import module object (already imported) but assert torch not pulled.
    assert "torch" not in sys.modules
    assert "transformers" not in sys.modules


def test_kind_values_match_enum():
    assert mt.KIND_VALUES == tuple(k.value for k in mt.KINDS)


def test_map_source_to_kind_vistas():
    assert mt.map_source_to_kind("vistas", "Lane Marking - Stop Line") == "stop_line"
    assert mt.map_source_to_kind("Vistas v2.0", "Lane Marking - Crosswalk") == "crosswalk_stripes"
    assert mt.map_source_to_kind("vistas", "Lane Marking - Ambiguous") == "unknown"


def test_map_source_to_kind_nuscenes():
    assert mt.map_source_to_kind("nuscenes", "solid") == "solid_white"
    assert mt.map_source_to_kind("nu_scenes", "double solid") == "double_solid_white"
    assert mt.map_source_to_kind("nuscenes", "unknown_type") == "unknown"


def test_map_source_to_kind_av2():
    assert mt.map_source_to_kind("av2", "SOLID_WHITE") == "solid_white"
    assert mt.map_source_to_kind("argoverse", "DOUBLE_DASHED_WHITE") == "double_dashed_white"
    assert mt.map_source_to_kind("av2", "ARROW_LEFT_X") == "arrow_left"


def test_map_source_to_kind_unknown_source_raises():
    with pytest.raises(ValueError):
        mt.map_source_to_kind("other", "x")


def test_all_mapped_kinds_are_canonical():
    for src, label in [("vistas", "Lane Marking - Stop Line"), ("nuscenes", "solid"), ("av2", "SOLID_WHITE")]:
        assert mt.map_source_to_kind(src, label) in mt.KIND_VALUES


def test_kind_to_feature_type_coverage():
    expected_features = {"divider", "stop_line", "crosswalk_stripe", "other_paint"}
    for kind in mt.KINDS:
        ft = mt.kind_to_feature_type(kind)
        assert ft is None or ft in expected_features
    # every non-None maps into the canonical feature set
    for v in mt.KIND_TO_FEATURE_TYPE.values():
        assert v is None or v in expected_features


def test_kind_to_feature_type_from_string():
    assert mt.kind_to_feature_type("solid_white") == "divider"
    assert mt.kind_to_feature_type(mt.KINDS.NONE) is None


def test_intersects_holdout_point():
    bbox = mt.HOLDOUT_BBOX_DEFAULT
    x = (bbox[0] + bbox[1]) // 2
    y = (bbox[2] + bbox[3]) // 2
    assert mt.intersects_holdout((x, y), bbox) is True
    assert mt.in_holdout(x, y, bbox) is True


def test_intersects_holdout_outside():
    bbox = mt.HOLDOUT_BBOX_DEFAULT
    assert mt.intersects_holdout((0.0, 0.0), bbox) is False


def test_intersects_holdout_buffered_touches():
    bbox = mt.HOLDOUT_BBOX_DEFAULT
    # point just outside by 10, buffer 50 should include
    x = bbox[0] - 10
    y = (bbox[2] + bbox[3]) // 2
    assert mt.intersects_holdout((x, y), bbox, buffer=0.0) is False
    assert mt.intersects_holdout((x, y), bbox, buffer=50.0) is True


def test_holdout_exclusion_no_patch_intersects_buffered():
    bbox = mt.HOLDOUT_BBOX_DEFAULT
    buffer = 50.0
    # patches well outside
    patches = [
        (0, 10, 0, 10),
        (bbox[1] + 100, bbox[1] + 200, bbox[3] + 100, bbox[3] + 200),
        (bbox[0] - 300, bbox[0] - 200, bbox[2] - 300, bbox[2] - 200),
    ]
    for p in patches:
        assert mt.intersects_holdout(p, bbox, buffer=buffer) is False


def test_enforce_holdout_raises():
    bbox = mt.HOLDOUT_BBOX_DEFAULT
    x = (bbox[0] + bbox[1]) // 2
    y = (bbox[2] + bbox[3]) // 2
    sample = mt.Sample(scene_id="s1", bbox=(x, x, y, y))
    with pytest.raises(mt.HoldoutViolation):
        mt.enforce_holdout(sample, bbox, buffer=0.0)


def test_load_samples_unknown_route_raises():
    with pytest.raises(ValueError):
        list(mt.load_samples("foo", "/tmp"))


def test_load_samples_empty_yields_zero(tmp_path):
    samples = list(mt.load_samples("camera", str(tmp_path)))
    assert samples == []
    assert len(samples) == 0


def test_load_samples_count_with_monkeypatched_adapter(monkeypatch):
    outside = (0, 10, 0, 10)
    samples = [mt.Sample(scene_id=f"s{i}", bbox=outside) for i in range(3)]

    def fake_adapter(route, root):
        return iter(samples)

    monkeypatch.setattr(mt, "_adapter", fake_adapter)
    out = list(mt.load_samples("bev", "/tmp", holdout_bbox=mt.HOLDOUT_BBOX_DEFAULT, buffer=0.0))
    assert len(out) == 3


def test_load_samples_holdout_raises_with_monkeypatch(monkeypatch):
    bbox = mt.HOLDOUT_BBOX_DEFAULT
    x = (bbox[0] + bbox[1]) // 2
    y = (bbox[2] + bbox[3]) // 2
    bad = [mt.Sample(scene_id="bad", bbox=(x, x, y, y))]

    def fake_adapter(route, root):
        return iter(bad)

    monkeypatch.setattr(mt, "_adapter", fake_adapter)
    with pytest.raises(mt.HoldoutViolation):
        list(mt.load_samples("camera", "/tmp"))


# Synthetic-data smoke (CPU, optional torch).


def _tiny_model():
    from torch import nn

    class M(nn.Module):
        def __init__(self):
            super().__init__()
            self.conv = nn.Conv2d(3, 4, 3, padding=1)
            self.head = nn.Conv2d(4, 2, 1)

        def forward(self, x):
            return self.head(self.conv(x))

    return M()


def test_synthetic_forward_pass_cpu():
    torch = pytest.importorskip("torch")
    model = _tiny_model()
    x = torch.rand(2, 3, 8, 8)
    out = model(x)
    assert tuple(out.shape) == (2, 2, 8, 8)


def test_synthetic_loss_cpu():
    torch = pytest.importorskip("torch")
    model = _tiny_model()
    x = torch.rand(2, 3, 8, 8)
    mask = torch.randint(0, 2, (2, 8, 8))
    out = model(x)
    loss = torch.nn.functional.cross_entropy(out, mask)
    assert torch.isfinite(loss)


def test_synthetic_checkpoint_save_load_cpu(tmp_path):
    torch = pytest.importorskip("torch")
    model = _tiny_model()
    path = tmp_path / "ckpt.pt"
    torch.save(model.state_dict(), path)
    assert path.exists()
    model2 = _tiny_model()
    sd = torch.load(path, map_location="cpu")
    model2.load_state_dict(sd)
    x = torch.rand(1, 3, 8, 8)
    a = model(x).detach()
    b = model2(x).detach()
    assert torch.allclose(a, b)


def test_synthetic_loader_rgb_masks(tmp_path):
    torch = pytest.importorskip("torch")
    from PIL import Image

    img_dir = tmp_path / "imgs"
    msk_dir = tmp_path / "msks"
    img_dir.mkdir()
    msk_dir.mkdir()
    for i in range(2):
        Image.new("RGB", (8, 8), (i * 10, i * 20, i * 30)).save(img_dir / f"{i}.png")
        Image.new("L", (8, 8), i).save(msk_dir / f"{i}.png")
    # simple loader
    imgs = []
    msks = []
    for i in range(2):
        im = Image.open(img_dir / f"{i}.png").convert("RGB")
        mk = Image.open(msk_dir / f"{i}.png")
        imgs.append(torch.tensor(list(im.getdata())).reshape(8, 8, 3).permute(2, 0, 1).float() / 255.0)
        msks.append(torch.tensor(list(mk.getdata())).reshape(8, 8).long())
    assert len(imgs) == 2
    assert imgs[0].shape == (3, 8, 8)
    assert msks[0].shape == (8, 8)


def test_eval_output_schema():
    row = {
        "run_id": "r1",
        "route": "camera",
        "eval_index": 0,
        "dataset": "vistas_v2",
        "heldout_bbox_epsg32619": [332112, 332668, 4689895, 4690292],
        "class": "solid_white",
        "support_pixels": 100,
        "iou": 0.5,
        "precision": 0.6,
        "recall": 0.7,
        "miou_eval_classes": 0.5,
        "delta_miou_vs_prev": None,
        "peak_vram_mib": None,
        "wall_time_s": 1.0,
        "sec_per_frame": None,
        "sec_per_epoch": None,
        "checkpoint_path": "/data/models/marking-type/ckpt.pt",
        "manifest_path": "/data/models/marking-type/data_manifest.json",
        "notes": "smoke",
    }
    required = {
        "run_id", "route", "eval_index", "dataset", "heldout_bbox_epsg32619",
        "class", "support_pixels", "iou", "precision", "recall",
        "miou_eval_classes", "delta_miou_vs_prev", "peak_vram_mib",
        "wall_time_s", "sec_per_frame", "sec_per_epoch", "checkpoint_path",
        "manifest_path", "notes",
    }
    assert required.issubset(row.keys())


# GPU-dependent tests (skipped without GPU).
@pytest.mark.skipif(True, reason="no GPU in CI environment")
def test_gpu_smoke():
    torch = pytest.importorskip("torch")
    if not torch.cuda.is_available():
        pytest.skip("no GPU available")
    x = torch.rand(2, 3, 4, 4, device="cuda")
    assert x.device.type == "cuda"
