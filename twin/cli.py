"""Command-line entry point for the twin package."""

import argparse
import json
from pathlib import Path

from twin import REPO
from twin.contracts import (
    STAGE_NAMES,
    AreaIndex,
    LabelFeature,
    Manifest,
    Params,
    Pipeline,
    SiteMeta,
    StageResult,
)
from twin.dataset import DatasetConfig
from twin.runner import cancel_command, rerun_command, run_command

SCHEMA_MODELS = {
    "params": Params,
    "pipeline": Pipeline,
    "manifest": Manifest,
    "stage_result": StageResult,
    "area_index": AreaIndex,
    "site_meta": SiteMeta,
    "label_feature": LabelFeature,
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
        default=Path(DatasetConfig.from_env().root),
    )
    box = sub.add_parser("box", help="box utilisation telemetry").add_subparsers(dest="box_cmd")
    box_mon = box.add_parser("monitor", help="sample the box into a daily CSV")
    box_mon.add_argument("--interval", type=float, default=10.0, help="seconds")
    box_mon.add_argument("--store", type=Path, help="run store (default: $TWIN_RUNS)")
    box_rep = box.add_parser("report", help="utilisation and idle report")
    box_rep.add_argument("--hours", type=float, default=24.0)
    box_rep.add_argument("--store", type=Path, help="run store (default: $TWIN_RUNS)")
    capture = sub.add_parser("capture", help="build a recon-core Posed Capture").add_subparsers(dest="capture_cmd")
    cap_area = capture.add_parser("area", help="build a Posed Capture from an area merge")
    cap_area.add_argument("name")
    cap_area.add_argument("--store", type=Path, help="run store (default: $TWIN_RUNS or /data/twin-runs)")

    stage = sub.add_parser("stage", help="run one contract stage as a Node command")
    stage.add_argument("name", choices=STAGE_NAMES)
    stage.add_argument("--in", dest="inputs", action="append", default=[], type=Path)
    stage.add_argument("--out", required=True, type=Path)
    stage.add_argument("--method")
    stage.add_argument("--params", type=Path)
    stage.add_argument("--scene")

    area = sub.add_parser("area", help="study areas").add_subparsers(dest="area_cmd")
    define = area.add_parser(
        "define", help="polygon from intersections or a GeoJSON polygon, and the drives through it"
    )
    define.add_argument("name")
    define.add_argument(
        "--intersection",
        action="append",
        metavar="TOKEN",
        help="HD-map intersection token or 8+ char prefix; repeat; exclusive with --polygon",
    )
    define.add_argument(
        "--polygon",
        type=Path,
        metavar="FILE",
        help="GeoJSON Polygon; CRS auto-detected (all x in [-180,180] and y in [-90,90] -> EPSG:4326 lon/lat, else EPSG:32619); exclusive with --intersection",
    )
    define.add_argument(
        "--buffer", type=float, default=0.0, help="metres around the intersections or polygon"
    )
    define.add_argument("--location", default="boston-seaport")
    define.add_argument("--version", default="v1.0-trainval")
    define.add_argument(
        "--include-rain", action="store_true", help="rain drives become build inputs"
    )
    define.add_argument(
        "--dataroot",
        type=Path,
        default=Path(DatasetConfig.from_env().root),
    )
    define.add_argument(
        "--store", type=Path, help="run store (default: $TWIN_RUNS or /data/twin-runs)"
    )
    suggest = area.add_parser(
        "suggest-drives", help="rank candidate trainval drives to improve area coverage"
    )
    suggest.add_argument("area")
    suggest.add_argument("--top", required=True, type=int, help="number of suggestions (>=1)")
    suggest.add_argument(
        "--density-threshold",
        type=float,
        default=50.0,
        help="low-coverage density threshold in sampled pts/m^2 (>=0, default 50.0; sweep_step=4)",
    )
    suggest.add_argument(
        "--apply", action="store_true", help="append ranked suggestions to resolved area file"
    )
    suggest.add_argument(
        "--dataroot",
        type=Path,
        default=Path(DatasetConfig.from_env().root),
    )
    suggest.add_argument(
        "--store", type=Path, help="run store (default: $TWIN_RUNS or /data/twin-runs)"
    )
    suggest.add_argument("--version", default="v1.0-trainval")
    merge = area.add_parser("merge", help="register the drives of an area into one cloud")
    merge.add_argument("name")
    merge.add_argument("--store", type=Path, help="run store (default: $TWIN_RUNS)")
    merge.add_argument("--heights", action="store_true", help="also fit sweep heights across drives")
    merge.add_argument("--method", choices=("chained-icp", "joint-pose-graph"), default="chained-icp", help="cross-drive registration method")
    at = area.add_parser("twin", help="twin from the merged cloud, with change detection")
    at.add_argument("name")
    at.add_argument("--store", type=Path, help="run store (default: $TWIN_RUNS)")
    at.add_argument("--check-date", help="report the change layer against the construction seen on this date")
    ab = area.add_parser("build", help="build an area twin through recon-core Manifest")
    ab.add_argument("name")
    ab.add_argument("--store", type=Path, help="run store (default: $TWIN_RUNS)")
    ab.add_argument("--check-date", help="report the change layer against the construction seen on this date")
    astep = area.add_parser("step", help="run one area pipeline step as a Node command")
    astep.add_argument("step", choices=("load", "mask", "align", "ground", "change"))
    astep.add_argument("--work", required=True, type=Path)
    astep.add_argument("--area", required=True, type=Path)
    astep.add_argument("--drives", type=Path)
    astep.add_argument("--features", type=Path)
    astep.add_argument("--load", type=Path)
    astep.add_argument("--align", type=Path)
    astep.add_argument("--capture", type=Path)
    astep.add_argument("--params", type=Path)
    astep.add_argument("--out", required=True, type=Path)
    ev = sub.add_parser("eval", help="go/no-go report for a run against the gates")
    ev.add_argument("run", help="run id (or run folder)")
    ev.add_argument("--baseline", help="run to compare every metric with")
    ev.add_argument("--rerun", help="rerun with the same inputs, for G1 determinism")
    ev.add_argument(
        "--store", type=Path, help="run store (default: $TWIN_RUNS or /data/twin-runs)"
    )
    sc = sub.add_parser("score", help="score a run against the labelled audit (or dev) sites")
    sc.add_argument("run", help="run id (or run/area folder or area name)")
    sc.add_argument("--sites", required=True, choices=("dev", "audit"), help="label sites by role")
    sc.add_argument("--store", type=Path, help="run store (default: $TWIN_RUNS or /data/twin-runs)")
    publish = sub.add_parser("publish", help="copy runs into a showcase folder")
    publish.add_argument("run_ids", nargs="+", metavar="run-id")
    publish.add_argument("--out", type=Path, required=True, help="showcase folder")
    publish.add_argument(
        "--store", type=Path, help="run store (default: $TWIN_RUNS or /data/twin-runs)"
    )
    site = sub.add_parser("site", help="publish a run to the public site, or roll back")
    site.add_argument("action", choices=("publish", "rollback", "history", "redeploy"))
    site.add_argument("run_id", nargs="?", help="run to publish (for publish)")
    site.add_argument("--latest", metavar="AREA", help="publish the area's latest build (any verdict)")
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
    pg.add_argument("--repo", default=REPO)
    pg.add_argument("--root", type=Path, default=Path.home() / "rdt-prgate")
    pg.add_argument("--dry-run", action="store_true", help="post nothing, print it")
    pg.add_argument("--store", type=Path, help="main run store (baseline, queue)")
    ap = sub.add_parser("autopilot", help="keep the queue full: PR gates, area rebuild, sweeps, prefetch")
    ap.add_argument("--store", type=Path, help="run store (default: $TWIN_RUNS)")
    ap.add_argument("--poll", type=float, default=60, help="seconds between checks")
    ap.add_argument("--once", action="store_true", help="one pass, then exit")
    ap.add_argument("--skip", action="append", default=[], metavar="P2|P3|P4", help="leave a source off")
    hl = sub.add_parser("health", help="write <store>/health.json and raise or clear box-alarm issues")
    hl.add_argument("--store", type=Path, help="run store (default: $TWIN_RUNS)")
    hl.add_argument("--no-alert", action="store_true", help="write health.json only, touch no issues")
    pl = sub.add_parser("pipeline", help="end-to-end checks: smoke (fake data, CI) or preflight (real data, box)")
    pl.add_argument("action", choices=("smoke", "preflight"))
    pl.add_argument("--store", type=Path, help="preflight: live store to read the area from (default: $TWIN_RUNS)")
    pl.add_argument("--work", type=Path, help="scratch folder (default: a new one under $TMPDIR)")
    serve = sub.add_parser("serve", help="run the control API")
    serve.add_argument("--store", type=Path, help="run store (default: $TWIN_RUNS)")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8090)
    labels = sub.add_parser("labels", help="labelled site management").add_subparsers(
        dest="labels_cmd"
    )
    labels_draft = labels.add_parser("draft", help="draft labels from an area build")
    labels_draft.add_argument("site", help="site id")
    labels_draft.add_argument("--area", required=True, help="area name or build dir")
    labels_draft.add_argument(
        "--role", choices=("dev", "audit"), default="dev", help="site role"
    )
    labels_draft.add_argument("--force", action="store_true", help="overwrite existing site")
    labels_draft.add_argument(
        "--store", type=Path, help="run store (default: $TWIN_RUNS or /data/twin-runs)"
    )
    labels_draft.add_argument(
        "--areas", type=Path, default=None, help="areas root (default: <store>/areas)"
    )
    labels_approve = labels.add_parser("approve", help="approve and freeze a site")
    labels_approve.add_argument("site", help="site id")
    labels_approve.add_argument("--by", required=True, help="approver name")
    labels_approve.add_argument(
        "--store", type=Path, help="run store (default: $TWIN_RUNS or /data/twin-runs)"
    )
    labels_new_version = labels.add_parser("new-version", help="start a new editable version")
    labels_new_version.add_argument("site", help="site id")
    labels_new_version.add_argument(
        "--store", type=Path, help="run store (default: $TWIN_RUNS or /data/twin-runs)"
    )
    labels_tool = labels.add_parser("tool", help="generate a labelling tool page")
    labels_tool.add_argument("site", help="site id")
    labels_tool.add_argument("--area", help="area name, build dir, or area json")
    labels_tool.add_argument(
        "--areas", type=Path, default=None, help="areas root (default: <store>/areas)"
    )
    labels_tool.add_argument("--reset", action="store_true", help="recreate an existing site empty")
    labels_tool.add_argument("--import", dest="import_path", type=Path, help="import a draft JSON before rendering")
    labels_tool.add_argument("--replace", action="store_true", help="replace the label collection on import")
    labels_tool.add_argument("--x0", type=float, help="window origin x (UTM)")
    labels_tool.add_argument("--y1", type=float, help="window top y (UTM)")
    labels_tool.add_argument(
        "--store", type=Path, help="run store (default: $TWIN_RUNS or /data/twin-runs)"
    )
    labels_import = labels.add_parser("import", help="import a draft JSON into a site")
    labels_import.add_argument("site", help="site id")
    labels_import.add_argument("draft", type=Path, help="draft JSON file")
    labels_import.add_argument("--replace", action="store_true", help="replace the label collection")
    labels_import.add_argument(
        "--store", type=Path, help="run store (default: $TWIN_RUNS or /data/twin-runs)"
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
            polygon=args.polygon,
        )
    if args.command == "area" and args.area_cmd == "suggest-drives":
        from twin.area import suggest_drives_command

        if args.top < 1:
            import sys

            print("--top must be an integer >= 1", file=sys.stderr)
            return 2
        if args.density_threshold < 0:
            import sys

            print("--density-threshold must be >= 0", file=sys.stderr)
            return 2
        return suggest_drives_command(
            args.area,
            args.top,
            args.density_threshold,
            args.apply,
            args.dataroot,
            args.store,
            args.version,
        )
    if args.command == "area" and args.area_cmd == "merge":
        from twin.merge import area_merge_command

        return area_merge_command(args.name, args.store, args.heights, args.method)
    if args.command == "area" and args.area_cmd == "twin":
        from twin.areatwin import area_twin_command

        return area_twin_command(args.name, args.store, args.check_date)
    if args.command == "area" and args.area_cmd == "build":
        from twin.areabuild import area_build_command

        return area_build_command(args.name, args.store, args.check_date)
    if args.command == "area" and args.area_cmd == "step":
        from twin.areasteps import area_step_command

        return area_step_command(
            args.step,
            work=args.work,
            area=args.area,
            drives=args.drives,
            features=args.features,
            load=args.load,
            align=args.align,
            out=args.out,
            params=args.params,
            capture=args.capture,
        )
    if args.command == "capture" and args.capture_cmd == "area":
        from twin.capture import capture_area_command

        return capture_area_command(args.name, args.store)
    if args.command == "stage":
        from twin.stagecli import stage_command

        return stage_command(
            args.name,
            args.inputs,
            args.out,
            method=args.method,
            params_path=args.params,
            scene=args.scene,
        )
    if args.command == "box":
        from twin.telemetry import box_command

        return box_command(args)
    if args.command == "eval":
        from twin.gates import eval_command

        return eval_command(args.run, args.baseline, args.rerun, args.store)
    if args.command == "score":
        from twin.score import score_command

        return score_command(args.run, args.sites, args.store)
    if args.command == "publish":
        from twin.publish import publish_command

        return publish_command(args.run_ids, args.out, args.store)
    if args.command == "site":
        from twin.site import site_command

        return site_command(args.action, args.run_id, args.dry_run, args.store, args.latest)
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
    if args.command == "autopilot":
        from twin.autopilot import autopilot_command

        return autopilot_command(args.store, args.poll, args.once, tuple(args.skip))
    if args.command == "health":
        from twin.health import health_command

        return health_command(args.store, args.no_alert)
    if args.command == "pipeline":
        from twin.pipeline_check import pipeline_command

        return pipeline_command(args.action, args.store, args.work)
    if args.command == "serve":
        from twin.api import serve_command

        return serve_command(args.store, args.host, args.port)
    if args.command == "labels" and args.labels_cmd == "draft":
        import sys

        from twin.labels import draft as draft_labels
        from twin.runner import default_store

        store = args.store if args.store is not None else default_store()
        try:
            draft_labels(
                store,
                args.site,
                args.area,
                force=args.force,
                role=args.role,
                areas_root=getattr(args, "areas", None),
            )
        except (ValueError, FileNotFoundError, FileExistsError) as exc:
            print(str(exc), file=sys.stderr)
            return 2
        return 0
    if args.command == "labels" and args.labels_cmd == "approve":
        from twin.labels import approve as approve_labels
        from twin.runner import default_store

        store = args.store if args.store is not None else default_store()
        approve_labels(store, args.site, args.by)
        return 0
    if args.command == "labels" and args.labels_cmd == "new-version":
        from twin.labels import new_version as new_version_labels
        from twin.runner import default_store

        store = args.store if args.store is not None else default_store()
        new_version_labels(store, args.site)
        return 0
    if args.command == "labels" and args.labels_cmd == "tool":
        import sys

        from twin import labels as labels_mod
        from twin.runner import default_store

        store = args.store if args.store is not None else default_store()
        try:
            from twin.labeltool import DraftError, generate

            path = generate(
                store,
                args.site,
                area=getattr(args, "area", None),
                areas_root=getattr(args, "areas", None),
                import_path=getattr(args, "import_path", None),
                replace=getattr(args, "replace", False),
                reset=getattr(args, "reset", False),
                x0=getattr(args, "x0", None),
                y1=getattr(args, "y1", None),
            )
        except (DraftError, ValueError, FileNotFoundError, labels_mod.FrozenSiteError) as exc:
            print(str(exc), file=sys.stderr)
            return 2
        print(path)
        print("serve locally at http://127.0.0.1:8090 (default; adjust for --host/--port)")
        return 0
    if args.command == "labels" and args.labels_cmd == "import":
        import sys

        from twin import labels as labels_mod
        from twin.runner import default_store

        store = args.store if args.store is not None else default_store()
        try:
            from twin.labeltool import DraftError, import_draft

            n = import_draft(
                store,
                args.site,
                args.draft,
                replace=getattr(args, "replace", False),
            )
        except (DraftError, ValueError, FileNotFoundError, labels_mod.FrozenSiteError) as exc:
            print(str(exc), file=sys.stderr)
            return 2
        print(n)
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
