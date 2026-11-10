"""Parameter sweeps (ADR 0005): a search space over stage params becomes queued jobs, and the
gate reports of the finished runs become a leaderboard.

Space file (yaml):
    mode: random          # or grid
    n: 12                 # random: number of variants
    seed: 0               # random: sampling seed
    params:               # dotted paths into Params
      ground.ransac_dist_m: {min: 0.03, max: 0.12}
      features.cluster_eps_m: {values: [0.2, 0.3, 0.5]}
      features.min_points: {min: 10, max: 40, steps: 4}   # steps: grid only, default 3

Every variant is validated against the contract ranges before any job is queued. Target is a base
run id (each variant is a rerun from the earliest stage it changes, with eval) or a scene token
(each variant is a full run). Area targets wait for area runs.
"""

import itertools
import json
import random
import re
import secrets
import sys
from datetime import UTC, datetime
from pathlib import Path

import yaml

from twin import jobqueue
from twin.contracts import PARAM_STAGE, STAGE_NAMES, Params
from twin.gates import GO, NO_GO, margin_score
from twin.runner import RUN_ID_RE, default_store

MAX_VARIANTS = 500
RANK = {GO: 0, NO_GO: 2}  # anything else (not measured) ranks 1


def _dim_values(path: str, spec: dict, grid: bool, rng: random.Random) -> list:
    if "values" in spec:
        return list(spec["values"])
    lo, hi = spec["min"], spec["max"]
    kind = type(_get(Params().model_dump(), path))
    if kind not in (int, float):
        raise ValueError(f"{path}: min/max needs a number parameter, use values")
    if grid:
        k = int(spec.get("steps", 3))
        pts = [lo + (hi - lo) * i / max(k - 1, 1) for i in range(k)]
    else:
        pts = [rng.uniform(lo, hi)]
    return [round(v) if kind is int else round(v, 4) for v in pts]


def _get(tree: dict, path: str):
    for key in path.split("."):
        tree = tree[key]
    return tree


def _set(tree: dict, path: str, value) -> None:
    *head, last = path.split(".")
    for key in head:
        tree = tree[key]
    tree[last] = value


def build_variants(space: dict, base: dict) -> list[dict]:
    """Return [{overrides, params, from_stage}], deduplicated, none equal to base.
    Raises ValueError when a value falls outside the contract ranges or a path is unknown."""
    base = Params.model_validate(base).model_dump(
        mode="json"
    )  # fill fields an old manifest lacks
    dims = space.get("params") or {}
    if not dims:
        raise ValueError("space has no params")
    mode = space.get("mode", "random")
    if mode not in ("random", "grid"):
        raise ValueError(f"mode must be random or grid, got {mode!r}")
    rng = random.Random(space.get("seed", 0))
    paths = sorted(dims)
    if mode == "grid":
        axes = [_dim_values(p, dims[p], True, rng) for p in paths]
        combos = list(itertools.product(*axes))
    else:
        combos = [
            tuple(_dim_values(p, dims[p], False, rng)[0] for p in paths)
            for _ in range(int(space.get("n", 10)))
        ]
    if len(combos) > MAX_VARIANTS:
        raise ValueError(f"{len(combos)} variants; the limit is {MAX_VARIANTS}")
    out, seen = [], set()
    for combo in combos:
        params = json.loads(json.dumps(base))
        for path, value in zip(paths, combo, strict=True):
            try:
                _set(params, path, value)
            except (KeyError, TypeError) as exc:
                raise ValueError(f"unknown parameter {path!r}") from exc
        params = Params.model_validate(params).model_dump(
            mode="json"
        )  # contract ranges
        key = json.dumps(params, sort_keys=True)
        if key in seen or params == base:
            continue
        seen.add(key)
        out.append(
            {
                "overrides": dict(zip(paths, combo, strict=True)),
                "params": params,
                "from_stage": earliest_stage(base, params),
            }
        )
    return out


def earliest_stage(base: dict, params: dict) -> str:
    """Earliest stage whose parameters differ (the existing PARAM_STAGE mapping)."""
    stages = {
        PARAM_STAGE[k] for k in params if params[k] != base.get(k) and PARAM_STAGE[k]
    }
    return min(stages, key=STAGE_NAMES.index)


def queue_sweep(store: Path, target: str, space: dict, extra: dict | None = None) -> str:
    """Queue one job per variant and write sweeps/<id>/sweep.json. Returns the sweep id."""
    is_run = re.fullmatch(RUN_ID_RE, target) is not None
    if is_run:
        mpath = store / target / "manifest.json"
        if not mpath.is_file():
            raise ValueError(f"run {target} not found in {store}")
        base = json.loads(mpath.read_text())["params"]
    else:
        base = Params().model_dump(mode="json")
    variants = build_variants(space, base)
    if not variants:
        raise ValueError("every variant equals the base parameters")
    sweep_id = f"{datetime.now(UTC):%Y%m%d-%H%M%S}-{secrets.token_hex(3)}"
    for n, var in enumerate(variants):
        job = (
            {"type": "rerun", "run_id": target, "from_stage": var["from_stage"]}
            if is_run
            else {"type": "run", "scene": target}
        )
        var["job_id"] = jobqueue.add(
            store,
            {
                **job,
                "params": var["params"],
                "eval": True,
                "sweep": sweep_id,
                "variant": n,
                **(extra or {}),
            },
        )
        del var["params"]  # the job and the run manifest hold the full params
    folder = store / "sweeps" / sweep_id
    folder.mkdir(parents=True)
    (folder / "sweep.json").write_text(
        json.dumps({"id": sweep_id, "target": target, "variants": variants}, indent=2)
        + "\n"
    )
    return sweep_id


def leaderboard(store: Path, sweep_id: str) -> dict:
    """Rank the finished variants (verdict first, then margin score) and write
    leaderboard.json, leaderboard.md and, when a variant passes, proposed_baseline.yaml.
    The proposed baseline is a proposal only; the operator adopts it."""
    folder = store / "sweeps" / sweep_id
    sweep = json.loads((folder / "sweep.json").read_text())
    jobs = {j["id"]: j for j in jobqueue.list_jobs(store)}
    rows, waiting = [], 0
    for var in sweep["variants"]:
        job = jobs.get(var["job_id"], {})
        gates = store / job.get("run_id", "-") / "gates.json"
        if (
            job.get("state") not in ("done", "failed")
            or job.get("error")
            or not gates.is_file()
        ):
            waiting += job.get("state") not in ("done", "failed")
            continue
        report = json.loads(gates.read_text())
        rows.append(
            {
                "run_id": job["run_id"],
                "verdict": report["verdict"],
                "score": margin_score(report),
                "overrides": var["overrides"],
                "from_stage": var["from_stage"],
            }
        )
    rows.sort(key=lambda r: (RANK.get(r["verdict"], 1), -r["score"]))
    board = {
        "sweep": sweep_id,
        "target": sweep["target"],
        "waiting": waiting,
        "rows": rows,
    }
    (folder / "leaderboard.json").write_text(json.dumps(board, indent=2) + "\n")
    lines = [
        f"# Sweep {sweep_id} on {sweep['target']}",
        "",
        (
            f"{len(rows)} scored, {waiting} still queued or running. "
            "Rank: verdict, then margin score (twin.gates.margin_score)."
        ),
        "",
        "| # | Verdict | Score | Run | Changed from | Overrides |",
        "|---|---|---|---|---|---|",
    ]
    for i, r in enumerate(rows, 1):
        lines.append(
            f"| {i} | {r['verdict']} | {r['score']:.3f} | {r['run_id']} | {r['from_stage']}"
            f" | `{json.dumps(r['overrides'])}` |"
        )
    (folder / "leaderboard.md").write_text("\n".join(lines) + "\n")
    best = next((r for r in rows if r["verdict"] == GO), None)
    if best:
        params = json.loads((store / best["run_id"] / "manifest.json").read_text())[
            "params"
        ]
        (folder / "proposed_baseline.yaml").write_text(
            "# PROPOSED baseline, not adopted. The operator approves it.\n"
            + yaml.safe_dump(
                {
                    "sweep": sweep_id,
                    "run_id": best["run_id"],
                    "score": best["score"],
                    "params": params,
                }
            )
        )
    return board


def sweep_command(
    target: str | None, space: Path | None, report: str | None, store: Path | None
) -> int:
    store = store or default_store()
    try:
        if report:
            leaderboard(store, report)
            print((store / "sweeps" / report / "leaderboard.md").read_text(), end="")
        elif target and space:
            print(queue_sweep(store, target, yaml.safe_load(space.read_text())))
        else:
            raise ValueError("give <target> --space FILE, or --report SWEEP_ID")
    except (OSError, yaml.YAMLError, ValueError, KeyError) as exc:
        print(f"twin sweep: {exc}", file=sys.stderr)
        return 2
    return 0
