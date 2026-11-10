"""Command-line entry point for the twin package."""

import argparse
import json
import os
from pathlib import Path

from twin.contracts import (
    STAGE_NAMES,
    AreaIndex,
    Manifest,
    Params,
    Pipeline,
    StageResult,
)
from twin.runner import cancel_command, rerun_command, run_command

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
    rerun = sub.add_parser("rerun", help="re-run a run from one stage")
    rerun.add_argument("run_id", help="parent run id")
    rerun.add_argument(
        "--from", dest="from_stage", required=True, choices=STAGE_NAMES, metavar="STAGE"
    )
    rerun.add_argument(
        "--pipeline", type=Path, help="pipeline overrides (partial yaml)"
    )
    rerun.add_argument("--params", type=Path, help="params overrides (partial yaml)")
    rerun.add_argument(
        "--store", type=Path, help="run store (default: $TWIN_RUNS or /data/twin-runs)"
    )
    cancel = sub.add_parser("cancel", help="stop a run before its next stage")
    cancel.add_argument("run_id", help="run id")
    cancel.add_argument(
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
    area = sub.add_parser("area", help="study areas").add_subparsers(dest="area_cmd")
    define = area.add_parser(
        "define", help="polygon from intersections, and the drives through it"
    )
    define.add_argument("name")
    define.add_argument(
        "--intersection",
        action="append",
        required=True,
        metavar="TOKEN",
        help="HD-map intersection token or 8+ char prefix; repeat",
    )
    define.add_argument(
        "--buffer", type=float, default=0.0, help="metres around the intersections"
    )
    define.add_argument("--location", default="boston-seaport")
    define.add_argument("--version", default="v1.0-trainval")
    define.add_argument(
        "--include-rain", action="store_true", help="rain drives become build inputs"
    )
    define.add_argument(
        "--dataroot",
        type=Path,
        default=Path(os.environ.get("NUSCENES_ROOT", "/data/nuscenes")),
    )
    define.add_argument(
        "--store", type=Path, help="run store (default: $TWIN_RUNS or /data/twin-runs)"
    )
    merge = area.add_parser("merge", help="register the drives of an area into one cloud")
    merge.add_argument("name")
    merge.add_argument("--store", type=Path, help="run store (default: $TWIN_RUNS)")
    ev = sub.add_parser("eval", help="go/no-go report for a run against the gates")
    ev.add_argument("run", help="run id (or run folder)")
    ev.add_argument("--baseline", help="run to compare every metric with")
    ev.add_argument("--rerun", help="rerun with the same inputs, for G1 determinism")
    ev.add_argument(
        "--store", type=Path, help="run store (default: $TWIN_RUNS or /data/twin-runs)"
    )
    publish = sub.add_parser("publish", help="copy runs into a showcase folder")
    publish.add_argument("run_ids", nargs="+", metavar="run-id")
    publish.add_argument("--out", type=Path, required=True, help="showcase folder")
    publish.add_argument(
        "--store", type=Path, help="run store (default: $TWIN_RUNS or /data/twin-runs)"
    )
    site = sub.add_parser("site", help="publish a run to the public site, or roll back")
    site.add_argument("action", choices=("publish", "rollback", "history"))
    site.add_argument("run_id", nargs="?", help="run to publish (for publish)")
    site.add_argument("--dry-run", action="store_true", help="build, do not deploy")
    site.add_argument("--store", type=Path, help="run store (default: $TWIN_RUNS)")
    fake = sub.add_parser("fake-run", help="write synthetic runs and a showcase bundle")
    fake.add_argument("--out", type=Path, default=Path("runs"))
    fake.add_argument("--drives", type=int, choices=(1, 2), default=2)
    queue = sub.add_parser("queue", help="job queue in the run store")
    queue.add_argument("action", choices=("add", "ls"))
    queue.add_argument("job_file", nargs="?", type=Path, help="job.json (for add)")
    queue.add_argument("--store", type=Path, help="run store (default: $TWIN_RUNS)")
    worker = sub.add_parser("worker", help="process queued jobs, one at a time")
    worker.add_argument("--store", type=Path, help="run store (default: $TWIN_RUNS)")
    worker.add_argument("--jobs", type=int, default=0, help="stop after N jobs (0: run on)")
    worker.add_argument("--poll", type=float, default=30, help="seconds between checks")
    worker.add_argument("--stream", action="store_true", help="stage-level scheduler instead of one job at a time")
    worker.add_argument("--tasks", type=int, default=None, help="with --stream: at most N tasks at once")
    worker.add_argument("--exit-when-idle", action="store_true", help="with --stream: stop when the queue is empty")
    sweep = sub.add_parser("sweep", help="queue a parameter sweep, or rank a finished one")
    sweep.add_argument("target", nargs="?", help="base run id, or scene token")
    sweep.add_argument("--space", type=Path, help="search space yaml")
    sweep.add_argument("--report", metavar="SWEEP_ID", help="write the leaderboard")
    sweep.add_argument("--store", type=Path, help="run store (default: $TWIN_RUNS)")
    pg = sub.add_parser("prgate", help="gate method PRs: poll the open ones, or run one")
    pg.add_argument("action", choices=("poll", "run"))
    pg.add_argument("pr", nargs="?", type=int, help="PR number (for run)")
    pg.add_argument("sha", nargs="?", help="PR head commit (for run)")
    pg.add_argument("--repo", default="Akamel01/road-digital-twin")
    pg.add_argument("--root", type=Path, default=Path.home() / "rdt-prgate")
    pg.add_argument("--dry-run", action="store_true", help="post nothing, print it")
    pg.add_argument("--store", type=Path, help="main run store (baseline, queue)")
    serve = sub.add_parser("serve", help="run the control API")
    serve.add_argument("--store", type=Path, help="run store (default: $TWIN_RUNS)")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8090)
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
    if args.command == "rerun":
        return rerun_command(
            args.run_id, args.from_stage, args.pipeline, args.params, args.store
        )
    if args.command == "cancel":
        return cancel_command(args.run_id, args.store)
    if args.command == "select":
        from twin.select import run_select

        return run_select(args.dataroot, args.min_density, args.min_contrast)
    if args.command == "area" and args.area_cmd == "define":
        from twin.area import area_define_command

        return area_define_command(
            args.name,
            args.intersection,
            args.buffer,
            args.location,
            args.dataroot,
            args.version,
            args.store,
            args.include_rain,
        )
    if args.command == "area" and args.area_cmd == "merge":
        from twin.merge import area_merge_command

        return area_merge_command(args.name, args.store)
    if args.command == "eval":
        from twin.gates import eval_command

        return eval_command(args.run, args.baseline, args.rerun, args.store)
    if args.command == "publish":
        from twin.publish import publish_command

        return publish_command(args.run_ids, args.out, args.store)
    if args.command == "site":
        from twin.site import site_command

        return site_command(args.action, args.run_id, args.dry_run, args.store)
    if args.command == "fake-run":
        from twin.fake_run import write_fake_runs

        for path in write_fake_runs(args.out, args.drives):
            print(path)
        return 0
    if args.command == "queue":
        from twin.jobqueue import queue_command

        return queue_command(args.action, args.job_file, args.store)
    if args.command == "worker":
        from twin.jobqueue import worker_command

        if args.stream:
            from twin.scheduler import stream_worker

            return stream_worker(args.store or __import__('twin.runner').runner.default_store(), args.tasks, min(args.poll, 5), args.exit_when_idle)
        return worker_command(args.store, args.jobs, args.poll)
    if args.command == "sweep":
        from twin.sweep import sweep_command

        return sweep_command(args.target, args.space, args.report, args.store)
    if args.command == "prgate":
        from twin.prgate import prgate_command

        return prgate_command(args)
    if args.command == "serve":
        from twin.api import serve_command

        return serve_command(args.store, args.host, args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
