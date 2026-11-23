from __future__ import annotations

import argparse
import json
import math
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from scripts.eval_schema import (
    METRICS,
    REGISTRY_PATH,
    EvalRegistry,
    EvalRun,
    dump_registry,
    load_registry,
)


def metrics_from_score(score: object) -> dict[str, float]:
    if not isinstance(score, dict):
        raise ValueError("score must be a JSON object")  # noqa: TRY004
    on_path = score.get("on_path")
    if not isinstance(on_path, dict):
        raise ValueError("score has no on_path object")  # noqa: TRY004
    out: dict[str, float] = {}
    for key in METRICS:
        value = on_path.get(key, None)
        if isinstance(value, bool):
            continue
        if not isinstance(value, (int, float)):
            continue
        f = float(value)
        if not math.isfinite(f):
            continue
        out[key] = f
    if not out:
        raise ValueError("no usable metrics in score")
    return out


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Append a harness score to the eval registry")
    p.add_argument("--score", required=True)
    p.add_argument("--id", required=True)
    p.add_argument("--approach", required=True)
    p.add_argument("--ticket", required=True, type=int)
    p.add_argument("--iterations", required=True, type=int)
    p.add_argument("--eval-set", required=True, dest="eval_set")
    p.add_argument("--variant", default="")
    p.add_argument("--minutes", type=float, default=None, dest="train_minutes")
    p.add_argument("--cap", type=int, default=None, dest="gaussian_cap")
    p.add_argument("--notes", default="")
    p.add_argument("--date", default=None)
    p.add_argument("--registry", default=str(REGISTRY_PATH))
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    registry = Path(args.registry)
    if args.date is None:
        run_date = datetime.now(UTC).date()
    else:
        run_date = datetime.strptime(args.date, "%Y-%m-%d").date()

    try:
        reg = load_registry(registry)
        if any(r.id == args.id for r in reg.runs):
            raise ValueError(f"duplicate id: {args.id}")
        if reg.runs and args.eval_set != reg.runs[0].eval_set:
            raise ValueError(f"eval set differs from registry: {args.eval_set}")
        if reg.runs and run_date < reg.runs[-1].date:
            raise ValueError("date is older than the last record; the registry is append-ordered")

        score_path = Path(args.score)
        score = json.loads(score_path.read_text(encoding="utf-8"))
        metrics = metrics_from_score(score)

        run = EvalRun(
            id=args.id,
            date=run_date,
            approach=args.approach,
            variant=args.variant,
            ticket=args.ticket,
            iterations=args.iterations,
            train_minutes=args.train_minutes,
            gaussian_cap=args.gaussian_cap,
            eval_set=args.eval_set,
            notes=args.notes,
            metrics=metrics,
        )
        if not run.metrics:
            raise ValueError("no usable metrics in score")
        next_reg = EvalRegistry(pass_bar=reg.pass_bar, runs=[*reg.runs, run])
        text = dump_registry(next_reg)
        tmp = Path(str(registry) + ".tmp")
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, registry)
        # shortcut: single-writer only; concurrent appends can lose a record, add a lock when the harness appends in parallel.
        print(f"appended {args.id}")
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as e:
        print(e, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
