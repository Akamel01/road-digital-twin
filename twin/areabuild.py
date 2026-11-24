"""Area build through recon-core Manifest (M5 / A1.3)."""

from __future__ import annotations

import json
import logging
import shutil
import sys
from pathlib import Path
from typing import Any

import recon_core.runner
import yaml

from twin.areastore import MERGED_NAME, open_area
from twin.areatwin import finish_area_twin, link_or_copy
from twin.contracts import Params

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
    area = open_area(base, name)
    core_dir = Path(core_dir)
    out = area.twin_dir
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
    link_or_copy(mask_node / "2_mask", out / "2_mask")
    link_or_copy(align_node / "3_align", out / "3_align")
    link_or_copy(ground_node / "4_ground", out / "4_ground")
    # 5_features from node change's 5_features
    link_or_copy(change_node / "5_features", out / "5_features")
    # 7_profile, 8_isd, 9_accuracy
    link_or_copy(profile_node / "7_profile", out / "7_profile")
    link_or_copy(isd_node / "8_isd", out / "8_isd")
    link_or_copy(accuracy_node / "9_accuracy", out / "9_accuracy")

    # change.geojson and change.json summary
    shutil.copy2(change_node / "change.geojson", out / "change.geojson")
    change_metrics = _read_json(change_node / "metrics.json")
    core_run_doc = _read_json(core_dir / "run.json")
    node_by_name = {n["name"]: n for n in core_run_doc.get("nodes", [])}
    seconds = {
        n: float(node_by_name.get(n, {}).get("duration_s", 0.0) or 0.0)
        for n in ["load", "mask", "align", "ground", "features", "change", "profile", "isd", "accuracy"]
    }

    shutil.copy2(core_dir / "run.json", out / "core-run.json")  # the core run record beside the twin's

    try:
        load_metrics = _read_json(load_node / "metrics.json")
    except (OSError, ValueError):
        load_metrics = {}
    return finish_area_twin(
        area,
        seconds=seconds,
        metrics={
            "load": load_metrics,
            "ground": _read_json(ground_node / "metrics.json"),
            "accuracy": _read_json(accuracy_node / "metrics.json"),
        },
        change=change_metrics,
        total_seconds=round(sum(seconds.values()), 1),
        check_date=check_date,
    )


def area_build(base: Path, name: str, log: logging.Logger, check_date: str | None = None) -> dict[str, Any]:
    from twin.capture import build_area_capture
    from twin.gates import eval_command

    base = Path(base)
    areas = base / "areas"
    area = open_area(base, name)
    if area.definition_path is None or not (area.merged_dir / MERGED_NAME).is_file() or not area.drive_records():
        raise ValueError(f"area {name!r} missing required inputs: its definition, {MERGED_NAME} or drives in {area.merged_dir}")

    capture_dir = areas / f"{name}-capture"
    if _capture_stale(capture_dir / "capture.json"):
        build_area_capture(area.merged_dir, capture_dir, name)

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
    twin_dir = area.twin_dir
    eval_command(str(twin_dir), None, None, None)
    gates = _read_json(twin_dir / "gates.json")
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
