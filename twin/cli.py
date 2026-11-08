"""Command-line entry point for the twin package."""

import argparse
import json
import os
from pathlib import Path

from twin.contracts import AreaIndex, Manifest, Params, Pipeline, StageResult
from twin.runner import run_command

SCHEMA_MODELS = {
    "params": Params,
    "pipeline": Pipeline,
    "manifest": Manifest,
    "stage_result": StageResult,
    "area_index": AreaIndex,
}


def render_schema(model) -> str:
    return json.dumps(model.model_json_schema(), sort_keys=True, indent=2) + "\n"


def write_schemas(out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for name, model in SCHEMA_MODELS.items():
        path = out_dir / f"{name}.schema.json"
        path.write_text(render_schema(model))
        written.append(path)
    return written


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="twin",
        description="Build a measurable 3D digital twin of a road from sensor data.",
    )
    sub = parser.add_subparsers(dest="command")
    schema = sub.add_parser("schema", help="write JSON Schemas for the contracts")
    schema.add_argument("--out", type=Path, default=Path("schemas"))
    run = sub.add_parser("run", help="run the pipeline on one scene")
    run.add_argument("--scene", required=True, help="scene token")
    run.add_argument(
        "--pipeline", type=Path, help="pipeline.yaml (default: all stages on)"
    )
    run.add_argument(
        "--params", type=Path, help="params.yaml (default: contract defaults)"
    )
    run.add_argument(
        "--store", type=Path, help="run store (default: $TWIN_RUNS or /data/twin-runs)"
    )
    select = sub.add_parser("select", help="list Boston drives with go/no-go")
    select.add_argument("--min-density", type=float, default=None)
    select.add_argument("--min-contrast", type=float, default=None)
    select.add_argument(
        "--dataroot",
        type=Path,
        default=Path(os.environ.get("NUSCENES_ROOT", "/data/nuscenes")),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "schema":
        for path in write_schemas(args.out):
            print(path)
        return 0
    if args.command == "run":
        return run_command(args.scene, args.pipeline, args.params, args.store)
    if args.command == "select":
        from twin.select import run_select

        return run_select(args.dataroot, args.min_density, args.min_contrast)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
