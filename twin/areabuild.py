"""Area build through recon-core Manifest (M5 / A1.3)."""

from __future__ import annotations

import json
import logging
import os
import shutil
import sys
from pathlib import Path
from typing import Any

import recon_core.runner
import yaml

from twin.contracts import Params
from twin.runrecord import read_record, write_document

TWIN = ["twin"] if shutil.which("twin") else [sys.executable, "-m", "twin.cli"]


def core_run(manifest_path: Path, workdir: Path) -> int:
    return recon_core.runner.run(manifest_path, workdir)


def area_manifest(base: Path, name: str) -> dict[str, Any]:
    """Return the literal A1.3 Manifest for an area build."""
    base = Path(base)
    # base is <store>/areas parent; manifest is written to <store>/areas/<name>-manifest.json
    # pipeline inputs are relative to core workdir <store>/areas/<name>-twin-core
    return {
        "pipeline": "area-twin",
        "inputs": {
            "area": f"../{name}.json",
            "merged_dir": f"../{name}-merged",
            "merged": f"../{name}-merged/merged.npz",
            "drives": f"../{name}-merged/drives.json",
            "capture": f"../{name}-capture",
            "params": f"../{name}-params.json",
        },
        "nodes": [
            {
                "name": "load",
                "command": [
                    *TWIN, "area", "step", "load",
                    "--work", "{in.merged_dir}",
                    "--area", "{in.area}",
                    "--capture", "{in.capture}",
                    "--out", "{out.root}",
                ],
                "inputs": {},
                "input_types": {"merged_dir": "dir", "area": "file", "capture": "posed_capture"},
                "outputs": {"root": ".", "dir": "1_load"},
                "output_types": {"root": "dir", "dir": "dir"},
            },
            {
                "name": "mask",
                "command": [
                    *TWIN, "area", "step", "mask",
                    "--work", "{in.merged_dir}",
                    "--area", "{in.area}",
                    "--out", "{out.root}",
                ],
                "inputs": {},
                "input_types": {"merged_dir": "dir", "area": "file"},
                "outputs": {"root": ".", "dir": "2_mask"},
                "output_types": {"root": "dir", "dir": "dir"},
            },
            {
                "name": "align",
                "command": [
                    *TWIN, "area", "step", "align",
                    "--work", "{in.merged_dir}",
                    "--area", "{in.area}",
                    "--out", "{out.root}",
                ],
                "inputs": {},
                "input_types": {"merged_dir": "dir", "area": "file"},
                "outputs": {"root": ".", "dir": "3_align"},
                "output_types": {"root": "dir", "dir": "dir"},
            },
            {
                "name": "ground",
                "command": [
                    *TWIN, "area", "step", "ground",
                    "--work", "{in.merged_dir}",
                    "--area", "{in.area}",
                    "--drives", "{in.drives}",
                    "--load", "{in.load}",
                    "--align", "{in.align}",
                    "--params", "{in.params}",
                    "--out", "{out.root}",
                ],
                "inputs": {
                    "load": {"node": "load", "output": "dir"},
                    "align": {"node": "align", "output": "dir"},
                },
                "input_types": {
                    "merged_dir": "dir", "area": "file", "drives": "file",
                    "load": "dir", "align": "dir", "params": "file",
                },
                "outputs": {"root": ".", "dir": "4_ground"},
                "output_types": {"root": "dir", "dir": "dir"},
            },
            {
                "name": "features",
                "command": [
                    *TWIN, "stage", "features",
                    "--in", "{in.load}",
                    "--in", "{in.align}",
                    "--in", "{in.ground}",
                    "--params", "{in.params}",
                    "--out", "{out.root}",
                ],
                "inputs": {
                    "load": {"node": "load", "output": "dir"},
                    "align": {"node": "align", "output": "dir"},
                    "ground": {"node": "ground", "output": "dir"},
                },
                "input_types": {"load": "dir", "align": "dir", "ground": "dir", "params": "file"},
                "outputs": {"root": ".", "dir": "5_features"},
                "output_types": {"root": "dir", "dir": "dir"},
            },
            {
                "name": "change",
                "command": [
                    *TWIN, "area", "step", "change",
                    "--work", "{in.merged_dir}",
                    "--area", "{in.area}",
                    "--drives", "{in.drives}",
                    "--features", "{in.features}",
                    "--load", "{in.load}",
                    "--out", "{out.root}",
                ],
                "inputs": {
                    "features": {"node": "features", "output": "dir"},
                    "load": {"node": "load", "output": "dir"},
                },
                "input_types": {
                    "merged_dir": "dir", "area": "file", "drives": "file",
                    "features": "dir", "load": "dir",
                },
                "outputs": {"root": ".", "features": "5_features", "load": "1_load", "change": "change.geojson"},
                "output_types": {"root": "dir", "features": "dir", "load": "dir", "change": "file"},
            },
            {
                "name": "profile",
                "command": [
                    *TWIN, "stage", "profile",
                    "--in", "{in.load}",
                    "--in", "{in.ground}",
                    "--params", "{in.params}",
                    "--out", "{out.root}",
                ],
                "inputs": {
                    "load": {"node": "load", "output": "dir"},
                    "ground": {"node": "ground", "output": "dir"},
                },
                "input_types": {"load": "dir", "ground": "dir", "params": "file"},
                "outputs": {"root": ".", "dir": "7_profile"},
                "output_types": {"root": "dir", "dir": "dir"},
            },
            {
                "name": "isd",
                "command": [
                    *TWIN, "stage", "isd",
                    "--in", "{in.load}",
                    "--in", "{in.mask}",
                    "--in", "{in.align}",
                    "--in", "{in.ground}",
                    "--params", "{in.params}",
                    "--out", "{out.root}",
                ],
                "inputs": {
                    "load": {"node": "load", "output": "dir"},
                    "mask": {"node": "mask", "output": "dir"},
                    "align": {"node": "align", "output": "dir"},
                    "ground": {"node": "ground", "output": "dir"},
                },
                "input_types": {"load": "dir", "mask": "dir", "align": "dir", "ground": "dir", "params": "file"},
                "outputs": {"root": ".", "dir": "8_isd"},
                "output_types": {"root": "dir", "dir": "dir"},
            },
            {
                "name": "accuracy",
                "command": [
                    *TWIN, "stage", "accuracy",
                    "--in", "{in.change}",
                    "--params", "{in.params}",
                    "--out", "{out.root}",
                ],
                "inputs": {"change": {"node": "change", "output": "root"}},
                "input_types": {"change": "dir", "params": "file"},
                "outputs": {"root": ".", "dir": "9_accuracy"},
                "output_types": {"root": "dir", "dir": "dir"},
            },
        ],
    }


def write_area_manifest(base: Path, name: str) -> Path:
    base = Path(base)
    areas = base / "areas"
    areas.mkdir(parents=True, exist_ok=True)
    path = areas / f"{name}-manifest.json"
    path.write_text(json.dumps(area_manifest(base, name), indent=2, sort_keys=True) + "\n")
    return path


def _symlink_or_copy(src: Path, dst: Path) -> None:
    if dst.exists() or dst.is_symlink():
        if dst.is_dir() and not dst.is_symlink():
            shutil.rmtree(dst)
        else:
            dst.unlink()
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.symlink(src.resolve(), dst)
    except OSError:
        if src.is_dir():
            shutil.copytree(src, dst)
        else:
            shutil.copy2(src, dst)


def _copy_tree_contents(src: Path, dst: Path) -> None:
    dst.mkdir(parents=True, exist_ok=True)
    for p in src.iterdir():
        target = dst / p.name
        if p.is_dir():
            shutil.copytree(p, target, dirs_exist_ok=True)
        else:
            shutil.copy2(p, target)


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def _capture_stale(capture_json: Path) -> bool:
    """Multi-drive capture without image_captures predates #409; rebuild it."""
    try:
        meta = json.loads(capture_json.read_text())
    except (OSError, ValueError):
        return True
    if not isinstance(meta, dict):
        return True
    captures = meta.get("captures")
    if not isinstance(captures, list):
        return True
    image_captures = meta.get("image_captures")
    return len(captures) > 1 and not (
        isinstance(image_captures, dict) and image_captures
    )


def assemble_area_twin(
    base: Path, name: str, core_dir: Path, manifest: dict[str, Any], check_date: str | None = None
) -> dict[str, Any]:
    base = Path(base)
    core_dir = Path(core_dir)
    out = base / "areas" / f"{name}-twin"
    if out.exists() or out.is_symlink():
        if out.is_dir() and not out.is_symlink():
            shutil.rmtree(out)
        else:
            out.unlink()
    out.mkdir(parents=True, exist_ok=True)

    nodes_dir = core_dir / "nodes"
    load_node = nodes_dir / "load"
    mask_node = nodes_dir / "mask"
    align_node = nodes_dir / "align"
    ground_node = nodes_dir / "ground"
    change_node = nodes_dir / "change"
    profile_node = nodes_dir / "profile"
    isd_node = nodes_dir / "isd"
    accuracy_node = nodes_dir / "accuracy"

    # 1_load from node change's 1_load (masked reference + facilities/poses)
    _copy_tree_contents(change_node / "1_load", out / "1_load")
    # 2_mask, 3_align, 4_ground
    _symlink_or_copy(mask_node / "2_mask", out / "2_mask")
    _symlink_or_copy(align_node / "3_align", out / "3_align")
    _symlink_or_copy(ground_node / "4_ground", out / "4_ground")
    # 5_features from node change's 5_features
    _symlink_or_copy(change_node / "5_features", out / "5_features")
    # 7_profile, 8_isd, 9_accuracy
    _symlink_or_copy(profile_node / "7_profile", out / "7_profile")
    _symlink_or_copy(isd_node / "8_isd", out / "8_isd")
    _symlink_or_copy(accuracy_node / "9_accuracy", out / "9_accuracy")

    # change.geojson and change.json summary
    shutil.copy2(change_node / "change.geojson", out / "change.geojson")
    change_metrics = _read_json(change_node / "metrics.json")
    core_run_doc = _read_json(core_dir / "run.json")
    node_by_name = {n["name"]: n for n in core_run_doc.get("nodes", [])}
    seconds = {
        n: float(node_by_name.get(n, {}).get("duration_s", 0.0) or 0.0)
        for n in ["load", "mask", "align", "ground", "features", "change", "profile", "isd", "accuracy"]
    }

    merged_dir = base / "areas" / f"{name}-merged"
    merged_doc = _read_json(merged_dir / "drives.json")
    for f in ("merged.npz", "drives.json", "qa.json"):
        src = merged_dir / f
        if src.exists():
            _symlink_or_copy(src, out / f)

    # core run record copy
    shutil.copy2(core_dir / "run.json", out / "core-run.json")

    # twin run record
    try:
        merged_record = read_record(merged_dir)
    except (OSError, ValueError):
        merged_record = {}
    ground_metrics = _read_json(ground_node / "metrics.json")
    accuracy_metrics = _read_json(accuracy_node / "metrics.json")
    try:
        load_metrics = _read_json(load_node / "metrics.json")
    except (OSError, ValueError, json.JSONDecodeError):
        load_metrics = {}
    # align metrics come from the joint (cross-drive) merge output, not from the
    # per-drive align node (which only reports the per-drive "merged-icp" method).
    align_metrics = dict(merged_record.get("metrics", {}).get("align", {}) or {})
    # also pull convergence/fallback/method from the merged qa.json if present
    for qa_path in (merged_dir / "qa.json",):
        try:
            qa = _read_json(qa_path)
        except (OSError, ValueError, json.JSONDecodeError):
            qa = {}
        for key in ("convergence", "fallback_used", "fallback_reason", "fallback", "method",
                    "n_anchors", "n_drives_with_overlap", "elapsed",
                    "anchor_residuals", "pair_residuals"):
            if key in qa and key not in align_metrics:
                align_metrics[key] = qa[key]
        if isinstance(qa.get("convergence"), dict):
            for k, v in qa["convergence"].items():
                if k not in align_metrics:
                    align_metrics[k] = v
    write_document(out, {
        "run_id": f"area-{name}-twin",
        "data": merged_record.get("data", {}),
        "metrics": {
            "load": load_metrics,
            "align": align_metrics,
            "ground": ground_metrics,
            "accuracy": accuracy_metrics,
        },
        "stages": [{"seconds": seconds[n]} for n in ["load", "mask", "align", "ground", "features", "change", "profile", "isd", "accuracy"]],
    })

    construction = None
    if check_date:
        import numpy as np
        from shapely.geometry import shape

        from twin.areatwin import construction_check

        area_doc = _read_json(base / "areas" / f"{name}.json")
        polygon = shape(area_doc["polygon"])
        centre = np.array([*polygon.centroid.coords[0], 0.0])
        regions = _read_json(change_node / "change.geojson").get("features", [])
        construction = construction_check(regions, merged_doc, merged_dir, centre, check_date)

    summary = {
        "area": name,
        "n_drives": len(merged_doc),
        "n_features": int(change_metrics.get("n_features", 0)),
        "n_features_changed": int(change_metrics.get("n_features_changed", 0)),
        "n_change_regions": int(change_metrics.get("n_change_regions", 0)),
        "change_area_m2": float(change_metrics.get("change_area_m2", 0.0)),
        "noise": change_metrics.get("noise", {}),
        "seconds": seconds,
        "twin_seconds": round(sum(seconds.values()), 1),
        "construction_check": construction,
        "by_date": change_metrics.get("by_date", {}),
    }
    (out / "change.json").write_text(json.dumps(summary, indent=2) + "\n")
    return summary


def area_build(base: Path, name: str, log: logging.Logger, check_date: str | None = None) -> dict[str, Any]:
    from twin.capture import build_area_capture
    from twin.gates import eval_command

    base = Path(base)
    areas = base / "areas"
    area_path = areas / f"{name}.json"
    merged_dir = areas / f"{name}-merged"
    merged_npz = merged_dir / "merged.npz"
    merged_drives = merged_dir / "drives.json"
    if not area_path.is_file() or not merged_npz.is_file() or not merged_drives.is_file():
        raise ValueError(f"area {name!r} missing required inputs: {area_path}, {merged_npz}, {merged_drives}")

    capture_dir = areas / f"{name}-capture"
    if _capture_stale(capture_dir / "capture.json"):
        build_area_capture(merged_dir, capture_dir, name)

    params_path = areas / f"{name}-params.json"
    if params_path.exists():
        Params.model_validate(yaml.safe_load(params_path.read_text()) or {})
    else:
        params_path.write_text(
            json.dumps(Params().model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
        )

    manifest_path = write_area_manifest(base, name)
    manifest = _read_json(manifest_path)
    core_dir = areas / f"{name}-twin-core"
    if core_dir.exists():
        shutil.rmtree(core_dir)
    rc = core_run(manifest_path, core_dir)
    core_doc = _read_json(core_dir / "run.json")
    for node in core_doc.get("nodes", []):
        status = node.get("status")
        if status != "done":
            err = node.get("error") or node.get("exit_code")
            raise RuntimeError(f"node {node.get('name')} failed: status={status} error={err}")
    if rc != 0:
        raise RuntimeError(f"core run failed with exit code {rc}")

    summary = assemble_area_twin(base, name, core_dir, manifest, check_date=check_date)
    eval_command(str(base / "areas" / f"{name}-twin"), None, None, None)
    gates = _read_json(base / "areas" / f"{name}-twin" / "gates.json")
    summary["gates_verdict"] = gates.get("verdict")
    return summary


def area_build_command(name: str, store: Path | None, check_date: str | None = None) -> int:
    from twin.runner import default_store

    logging.basicConfig(level=logging.INFO)
    log = logging.getLogger("twin.areabuild")
    base = Path(store) if store else default_store()
    try:
        summary = area_build(base, name, log, check_date=check_date)
    except ValueError as exc:
        print(f"twin area build: {exc}", flush=True)
        return 2
    except RuntimeError as exc:
        print(f"twin area build: {exc}", flush=True)
        return 1
    except Exception as exc:  # noqa: BLE001
        print(f"twin area build: {exc}", flush=True)
        return 1
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0
