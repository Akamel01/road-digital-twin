"""Area pipeline steps as Node-ready commands (A1.3/A1.4).

Each step writes stage files under --out, plus metrics.json and core-format checks.json.
These are extracted from twin.areatwin so recon-core can wrap them as Manifest Nodes.
"""

from __future__ import annotations

import json
import logging
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import shapely
from recon_core.checks import Check, write_checks
from shapely.geometry import shape

from twin.contracts import Params, flatten, stage_dir
from twin.runner import StageContext

STAGE_ORDER = ("ground", "features", "profile", "isd", "accuracy")


@dataclass(frozen=True)
class StepResult:
    status: str
    metrics: dict[str, Any]
    files: list[str]


def _fc(feats: list[dict]) -> str:
    return json.dumps({"type": "FeatureCollection", "features": feats})


def _check_value(value: Any) -> Any:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        return value
    if value is None:
        return "null"
    return str(value)


def _write_node_outputs(out: Path, status: str, metrics: dict[str, Any]) -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / "metrics.json").write_text(json.dumps(metrics, sort_keys=True, indent=2) + "\n")
    checks = [Check(name=k, value=_check_value(v), passed=True) for k, v in flatten(metrics).items()]
    checks.append(Check(name="stage_ok", value=status, passed=status in ("ok", "skipped")))
    write_checks(out, checks)


def _load_area(area_path: Path) -> dict:
    return json.loads(area_path.expanduser().resolve().read_text())


def _load_drives(drives_path: Path | None, work: Path) -> list[dict]:
    if drives_path is not None:
        return json.loads(drives_path.expanduser().resolve().read_text())
    return json.loads((work / "drives.json").read_text())


def _load_params(params_path: Path | None) -> Params:
    if params_path is None:
        return Params()
    import yaml

    data = yaml.safe_load(params_path.read_text()) or {}
    return Params.model_validate(data)


def _ok(out: Path, metrics: dict[str, Any], files: list[str]) -> StepResult:
    _write_node_outputs(out, "ok", metrics)
    return StepResult(status="ok", metrics=metrics, files=files)


def load_step(work: Path, area: dict, out: Path, capture: Path | None = None) -> StepResult:
    """Write 1_load stand-ins for the area merged frame."""
    from twin import areatwin as at

    work = Path(work)
    out = Path(out)
    polygon = shape(area["polygon"])
    drives = json.loads((work / "drives.json").read_text())
    facilities, reference = at.area_inputs(drives, work, polygon)
    ident = json.dumps({"poses": [{"matrix": np.eye(4).tolist()}]})
    load_dir = stage_dir(out, "load")
    load_dir.mkdir(parents=True, exist_ok=True)
    files = {
        "facilities.geojson": _fc(facilities),
        "reference.full.geojson": _fc(reference),
        "reference.geojson": _fc(reference),
        "poses.json": ident,
    }
    for fn, text in files.items():
        (load_dir / fn).write_text(text)
    metrics: dict[str, Any] = {
        "n_drives": len(drives),
        "n_facilities": len(facilities),
        "n_reference": len(reference),
    }
    if capture is not None:
        metrics["capture"] = str(Path(capture).resolve())
        cap_meta = Path(capture) / "capture.json"
        if cap_meta.is_file():
            (load_dir / "capture.json").write_text(cap_meta.read_text())
    return _ok(out, metrics, [f"1_load/{k}" for k in files] + (["1_load/capture.json"] if (load_dir / "capture.json").is_file() else []))


def mask_step(work: Path, area: dict, out: Path) -> StepResult:
    """Write 2_mask/parked.npz in merged frame."""
    from twin import areatwin as at

    work = Path(work)
    out = Path(out)
    polygon = shape(area["polygon"])
    centre = np.array([*polygon.centroid.coords[0], 0.0])
    drives = json.loads((work / "drives.json").read_text())
    parked = at.parked_vehicles(drives, work, centre, polygon)
    mask_dir = stage_dir(out, "mask")
    mask_dir.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        mask_dir / "parked.npz",
        x=parked[:, 0],
        y=parked[:, 1],
        z=parked[:, 2],
        intensity=np.zeros(len(parked), np.float32),
        sweep=np.zeros(len(parked), np.uint16),
    )
    return _ok(out, {"n_parked_points": len(parked)}, ["2_mask/parked.npz"])


def align_step(out: Path) -> StepResult:
    """Write identity align stand-ins."""
    out = Path(out)
    align_dir = stage_dir(out, "align")
    align_dir.mkdir(parents=True, exist_ok=True)
    ident = json.dumps({"poses": [{"matrix": np.eye(4).tolist()}]})
    qa = {"method": "merged-icp", "fallback_used": False, "xy_drift_p95_m": None}
    (align_dir / "poses.json").write_text(ident)
    (align_dir / "qa.json").write_text(json.dumps(qa))
    return _ok(out, {"method": "merged-icp", "fallback_used": False}, ["3_align/poses.json", "3_align/qa.json"])


def _stage_dir_for(name: str, base: Path) -> Path:
    """Accept a node dir containing <n>_<name> or the stage dir itself."""
    base = Path(base)
    if base.name == f"{__import__('twin.contracts', fromlist=['STAGES']).STAGES[name].number}_{name}":
        return base
    candidate = stage_dir(base, name)
    if candidate.is_dir():
        return candidate
    if base.is_dir():
        return base
    return candidate


def ground_step(
    work: Path,
    area: dict,
    drives: list[dict],
    load_dir: Path,
    align_dir: Path,
    out: Path,
    params: Params,
    log: logging.Logger,
) -> StepResult:
    """Run ground on merged cloud; writes 4_ground/*."""
    from twin import areatwin as at

    work = Path(work)
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    load_stage = _stage_dir_for("load", load_dir)
    align_stage = _stage_dir_for("align", align_dir)
    with np.load(work / "merged.npz") as f:
        x, y, z = f["x"], f["y"], f["z"]
        intensity, drive = f["intensity"].astype(np.float32), f["drive"].astype(np.int64)

    polygon = shape(area["polygon"])
    np.array([*polygon.centroid.coords[0], 0.0])
    ctx = StageContext(out, f"area-{area.get('name', 'area')}", params.seed, log, params.facilities.min_observed)
    t0 = time.time()
    perm = np.random.default_rng(params.seed).permutation(len(x))
    xyz = np.column_stack([x, y, z])[perm]
    inten, drv = intensity[perm], drive[perm]
    keep = at.ground.voxel_first(xyz, params.ground.voxel_m)
    facilities = json.loads((load_stage / "facilities.geojson").read_text())["features"]
    align_qa = json.loads((align_stage / "qa.json").read_text())
    res = at.ground.split_and_write(
        ctx,
        params.ground,
        "ransac-tiles",
        lambda p, q: at.ground.ransac_ground(p, q, params.seed),
        xyz[keep],
        inten[keep],
        drv[keep].astype(np.int32),
        None,
        None,
        align_qa,
        facilities,
    )
    if res.status != "ok":
        _write_node_outputs(out, res.status, res.metrics)
        return StepResult(status=res.status, metrics=res.metrics, files=res.files)
    metrics = dict(res.metrics)
    metrics["seconds"] = round(time.time() - t0, 1)
    return _ok(out, metrics, list(res.files))


def _copy_tree_files(src_dir: Path, dst_dir: Path) -> list[str]:
    dst_dir.mkdir(parents=True, exist_ok=True)
    copied = []
    for p in sorted(src_dir.iterdir()):
        if p.is_file():
            target = dst_dir / p.name
            if target.resolve() != p.resolve():
                shutil.copy2(p, target)
            copied.append(p.name)
    return copied


def change_step(
    work: Path,
    area: dict,
    drives: list[dict],
    features_dir: Path,
    load_dir: Path,
    out: Path,
) -> StepResult:
    """Detect change, flag features, mask reference; write change.geojson and updated 1_load/5_features."""
    from twin import areatwin as at

    work = Path(work)
    out = Path(out)
    features_stage = _stage_dir_for("features", features_dir)
    load_stage = _stage_dir_for("load", load_dir)
    polygon = shape(area["polygon"])
    dates = [d["date"] for d in drives]
    scenes = [d["scene"] for d in drives]

    with np.load(work / "merged.npz") as f:
        x, y, z = f["x"], f["y"], f["z"]
        drive = f["drive"].astype(np.int64)

    b = polygon.bounds
    origin = np.array([b[0], b[1]])
    shape_yx = (int((b[3] - b[1]) // at.CELL_M) + 2, int((b[2] - b[0]) // at.CELL_M) + 2)
    inside = shapely.contains_xy(polygon, x, y)
    lo, hi = at.cell_stats(x[inside], y[inside], z[inside], drive[inside], origin, shape_yx, len(drives))
    del inside

    reference_full = json.loads((load_stage / "reference.full.geojson").read_text())["features"]
    road = shapely.union_all([shape(f["geometry"]) for f in reference_full if f["properties"]["layer"] == "drivable_area"])
    cx = origin[0] + (np.arange(lo.shape[1]) % shape_yx[1] + 0.5) * at.CELL_M
    cy = origin[1] + (np.arange(lo.shape[1]) // shape_yx[1] + 0.5) * at.CELL_M
    off = ~shapely.contains_xy(road, cx, cy)
    lo[:, off] = np.nan
    hi[:, off] = np.nan
    noise = at.noise_levels(lo, hi, dates, shape_yx)
    det = at.detect_change(lo, hi, dates, noise, shape_yx)
    regions = at.change_regions(det, origin, shape_yx, dates, scenes)

    out.mkdir(parents=True, exist_ok=True)
    (out / "change.geojson").write_text(_fc(regions))

    gz = np.nanmedian(np.where(np.isfinite(lo), lo, np.nan), axis=0)
    cell = (np.floor((y - origin[1]) / at.CELL_M).astype(np.int64) * shape_yx[1] + np.floor((x - origin[0]) / at.CELL_M).astype(np.int64))
    cell = np.clip(cell, 0, gz.size - 1)

    # Copy 5_features from features_dir into out, then flag support/changed in place.
    out_feat = stage_dir(out, "features")
    out_feat.mkdir(parents=True, exist_ok=True)
    if features_stage.resolve() != out_feat.resolve():
        for p in features_stage.iterdir():
            if p.is_file():
                target = out_feat / p.name
                if p.resolve() != target.resolve():
                    shutil.copy2(p, target)
    qa_src = features_stage / "qa.json"
    qa_dst = out_feat / "qa.json"
    if qa_src.is_file() and qa_src.resolve() != qa_dst.resolve():
        shutil.copy2(qa_src, qa_dst)

    all_feats: dict[str, list[dict]] = {}
    for fn in at.FEATURE_FILES:
        fp = out_feat / fn
        if fp.is_file():
            all_feats[fn] = json.loads(fp.read_text())["features"]
    flat = [f for v in all_feats.values() for f in v]
    at.support(flat, np.column_stack([x, y, z]), drive, gz[cell], origin, shape_yx, scenes)
    n_changed = at.flag_changed(flat, regions)
    for fn, v in all_feats.items():
        (out_feat / fn).write_text(_fc(v))

    # Copy 1_load from load_dir, then overwrite reference.geojson with masked reference.
    out_load = stage_dir(out, "load")
    copied = _copy_tree_files(load_stage, out_load)
    # ensure reference.full.geojson present
    ref_full_src = load_stage / "reference.full.geojson"
    ref_full_dst = out_load / "reference.full.geojson"
    if ref_full_src.is_file() and "reference.full.geojson" not in copied and ref_full_src.resolve() != ref_full_dst.resolve():
        shutil.copy2(ref_full_src, ref_full_dst)
    (out_load / "reference.geojson").write_text(_fc(at.mask_reference(reference_full, regions)))

    metrics = {
        "noise": noise,
        "n_change_regions": len(regions),
        "change_area_m2": round(sum(r["properties"]["area_m2"] for r in regions), 1),
        "by_date": {
            d: {
                "regions": sum(d in r["properties"]["dates"] for r in regions),
                "area_m2": round(sum(r["properties"]["area_m2"] for r in regions if d in r["properties"]["dates"]), 1),
            }
            for d in sorted(set(dates))
        },
        "n_features_changed": int(n_changed),
        "n_features": len(flat),
    }
    files = ["change.geojson"] + [f"5_features/{fn}" for fn in all_feats] + ["1_load/reference.geojson"]
    if (out_feat / "qa.json").is_file():
        files.append("5_features/qa.json")
    return _ok(out, metrics, files)


def area_step_command(
    step: str,
    *,
    work: Path,
    area: Path,
    drives: Path | None = None,
    features: Path | None = None,
    load: Path | None = None,
    align: Path | None = None,
    out: Path,
    params: Path | None = None,
    capture: Path | None = None,
) -> int:
    """CLI entry for area steps. Exit 0 ok, 1 failed, 2 bad args/missing paths."""
    log = logging.getLogger("twin.areasteps")
    try:
        work = Path(work).expanduser().resolve()
        out = Path(out).expanduser().resolve()
        area_doc = _load_area(Path(area))
        params_obj = _load_params(params)
    except Exception as exc:  # noqa: BLE001
        print(f"twin area step: {exc}", flush=True)
        return 2

    try:
        if step == "load":
            res = load_step(work, area_doc, out, capture=Path(capture).expanduser().resolve() if capture else None)
        elif step == "mask":
            res = mask_step(work, area_doc, out)
        elif step == "align":
            res = align_step(out)
        elif step == "ground":
            if load is None or align is None:
                print("twin area step: ground requires --load and --align", flush=True)
                return 2
            drives_doc = _load_drives(Path(drives) if drives else None, work)
            res = ground_step(work, area_doc, drives_doc, Path(load), Path(align), out, params_obj, log)
        elif step == "change":
            if features is None or load is None:
                print("twin area step: change requires --features and --load", flush=True)
                return 2
            drives_doc = _load_drives(Path(drives) if drives else None, work)
            res = change_step(work, area_doc, drives_doc, Path(features), Path(load), out)
        else:
            print(f"twin area step: unknown step {step!r}", flush=True)
            return 2
    except FileNotFoundError as exc:
        print(f"twin area step: missing path: {exc}", flush=True)
        return 2
    except Exception as exc:
        log.exception("area step %s failed", step)
        _write_node_outputs(out, "failed", {"error": f"{type(exc).__name__}: {exc}"})
        print(f"twin area step: {step} failed: {exc}", flush=True)
        return 1

    print(json.dumps({"status": res.status, "metrics": res.metrics, "files": res.files}, sort_keys=True))
    return 0 if res.status in ("ok", "skipped") else 1
