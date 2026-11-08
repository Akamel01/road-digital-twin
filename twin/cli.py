"""Command-line entry point for the twin package."""

import argparse
import json
from pathlib import Path

from twin.contracts import AreaIndex, Manifest, Params, Pipeline, StageResult

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
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "schema":
        for path in write_schemas(args.out):
            print(path)
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
