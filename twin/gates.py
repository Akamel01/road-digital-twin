"""Go/no-go report for a run against the gates file (ADR 0005)."""

import json
import math
from pathlib import Path

import yaml

from twin.runner import default_store

GATES_FILE = Path(__file__).with_name("gates.yaml")
GO, NO_GO, NOT_MEASURED = "go", "no-go", "not measured"
# Metrics compared with a baseline: distance errors in metres, lower is better.
_ERROR_SUFFIXES = ("p50_m", "p95_m", "rmse_m")


def load_gates(path: Path = GATES_FILE) -> dict:
    return yaml.safe_load(path.read_text())


def run_dir(run: str, store: Path | None) -> Path:
    path = Path(run)
    return path if path.is_dir() else (store or default_store()) / run


def _lookup(tree, dotted: str):
    for key in dotted.split("."):
        if not isinstance(tree, dict) or key not in tree:
            return None
        tree = tree[key]
    return tree


def _flatten(tree, prefix: str = "") -> dict:
    flat = {}
    for key, val in tree.items():
        name = f"{prefix}{key}"
        if isinstance(val, dict):
            flat.update(_flatten(val, name + "."))
        else:
            flat[name] = val
    return flat


def _isnum(val) -> bool:
    return (
        isinstance(val, int | float)
        and not isinstance(val, bool)
        and math.isfinite(val)
    )


def _metrics(manifest: dict, extra: dict) -> dict:
    metrics = dict(manifest.get("metrics", {}))
    seconds = sum(s.get("seconds", 0.0) for s in manifest.get("stages", []))
    metrics["runtime"] = {"total_min": round(seconds / 60, 3)}
    return {**metrics, **extra}


def _check(spec: dict, metrics: dict) -> dict:
    value = _lookup(metrics, spec["metric"])
    out = {
        "metric": spec["metric"],
        "op": spec["op"],
        "threshold": spec["value"],
        "value": value if _isnum(value) else None,
    }
    if out["value"] is None:
        out["status"] = NOT_MEASURED
    elif spec["op"] == "<=":
        out["status"] = GO if value <= spec["value"] else NO_GO
    else:
        out["status"] = GO if value >= spec["value"] else NO_GO
    return out


def _combine(statuses: list[str]) -> str:
    if NO_GO in statuses:
        return NO_GO
    return NOT_MEASURED if NOT_MEASURED in statuses else GO


def margin_score(report: dict) -> float:
    """Sweep score: the sum over measured checks of the normalised margin
    (threshold - value) / threshold for "<=" and (value - threshold) / threshold for ">=",
    each clipped to [-1, 1]. Positive is headroom, negative is a miss. A zero threshold
    cannot be normalised, so that check scores 0 when it passes and -1 when it fails.
    Not-measured checks add nothing. This is the only place the formula lives."""
    total = 0.0
    for gate in report["gates"].values():
        for c in gate["checks"]:
            if c["value"] is None:
                continue
            if c["status"] == GO and not c["threshold"]:
                continue
            if not c["threshold"]:
                total -= 1
                continue
            sign = 1 if c["op"] == "<=" else -1
            margin = sign * (c["threshold"] - c["value"]) / abs(c["threshold"])
            total += max(-1.0, min(1.0, margin))
    return round(total, 6)


def regressions(run: dict, base: dict, tol: float) -> list[dict]:
    """Error metrics worse than the baseline by more than tol, or lost since."""
    cur, old = _flatten(run), _flatten(base)
    found = []
    for name, was in sorted(old.items()):
        if not name.endswith(_ERROR_SUFFIXES) or not _isnum(was):
            continue
        now = cur.get(name)
        if not _isnum(now):
            found.append({"metric": name, "baseline": was, "value": None})
        elif now - was > tol:
            found.append({"metric": name, "baseline": was, "value": now})
    return found


def evaluate(
    manifest: dict,
    baseline: dict | None = None,
    rerun: dict | None = None,
    gates: dict | None = None,
) -> dict:
    gates = gates or load_gates()
    extra = {}
    if rerun is not None:
        a, b = _flatten(manifest.get("metrics", {})), _flatten(rerun.get("metrics", {}))
        diff = sorted(k for k in a.keys() | b.keys() if a.get(k) != b.get(k))
        extra["determinism"] = {"n_differing_metrics": len(diff)}
    metrics = _metrics(manifest, extra)
    results = {}
    for gid, gate in gates["gates"].items():
        checks = [_check(c, metrics) for c in gate["checks"]]
        results[gid] = {
            "name": gate["name"],
            "status": _combine([c["status"] for c in checks]),
            "checks": checks,
        }
        if (
            gid == "G1"
            and rerun is not None
            and extra["determinism"]["n_differing_metrics"]
        ):
            results[gid]["differing_metrics"] = diff[:50]
    report = {
        "gates_version": gates["version"],
        "run_id": manifest["run_id"],
        "baseline": baseline["run_id"] if baseline else None,
        "rerun": rerun["run_id"] if rerun else None,
        "gates": results,
    }
    statuses = [g["status"] for g in results.values()]
    if baseline is not None:
        tol = gates["noise_tolerance_m"]
        worse = regressions(
            manifest.get("metrics", {}), baseline.get("metrics", {}), tol
        )
        report["regressions"] = worse
        report["noise_tolerance_m"] = tol
        statuses.append(NO_GO if worse else GO)
    report["verdict"] = _combine(statuses)
    return report


def render_markdown(report: dict) -> str:
    lines = [
        f"# Gates for run {report['run_id']}: {report['verdict'].upper()}",
        "",
        f"Gates file version {report['gates_version']}. Baseline: "
        + f"{report['baseline'] or 'none'}. Rerun: {report['rerun'] or 'none'}.",
        "",
        "| Gate | Metric | Value | Threshold | Status |",
        "|---|---|---|---|---|",
    ]
    for gid, gate in report["gates"].items():
        for c in gate["checks"]:
            val = "-" if c["value"] is None else f"{c['value']:g}"
            lines.append(
                f"| {gid} {gate['name']} | `{c['metric']}` | {val}"
                f" | {c['op']} {c['threshold']:g} | {c['status']} |"
            )
    if "regressions" in report:
        n = len(report["regressions"])
        lines += [
            "",
            f"## Baseline comparison (tolerance {report['noise_tolerance_m']} m)",
            "",
        ]
        lines.append(
            "No metric worse than the baseline." if not n else f"{n} regression(s):"
        )
        for r in report["regressions"]:
            now = "lost" if r["value"] is None else f"{r['value']:g}"
            lines.append(f"- `{r['metric']}`: baseline {r['baseline']:g}, now {now}")
    return "\n".join(lines) + "\n"


def eval_command(
    run: str, baseline: str | None, rerun: str | None, store: Path | None
) -> int:
    def manifest(r: str) -> dict:
        return json.loads((run_dir(r, store) / "manifest.json").read_text())

    report = evaluate(
        manifest(run),
        manifest(baseline) if baseline else None,
        manifest(rerun) if rerun else None,
    )
    out = run_dir(run, store)
    (out / "gates.json").write_text(json.dumps(report, indent=2) + "\n")
    text = render_markdown(report)
    (out / "gates.md").write_text(text)
    print(text, end="")
    return 0 if report["verdict"] == GO else 1
