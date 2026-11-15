"""Go/no-go report for a run against the gates file (ADR 0005)."""

import json
import math
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

import yaml

from twin.runner import default_store

GATES_FILE = Path(__file__).with_name("gates.yaml")
GO, NO_GO, NOT_MEASURED = "go", "no-go", "not measured"
# Metrics compared with a baseline: distance errors in metres, lower is better.
# (Only gated metrics whose names end in one of _ERROR_SUFFIXES are compared.)
_ERROR_SUFFIXES = ("p50_m", "p95_m", "rmse_m")

# G2 ratchet (#222/ADR 0005): 3 area builds in a row at current threshold pass -> due.
G2_STEPS = {0.20: 0.10, 0.10: 0.05}
G2_RUN = 3
G2_HISTORY_FILE = Path("autopilot") / "g2_history.json"
RANK = {GO: 0, NO_GO: 2}  # anything else (not measured) ranks 1
verdict_rank = RANK  # compat alias for sweep/autopilot consumers


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


def _report_checks(report: Mapping) -> list[tuple[str, Mapping]]:
    """Yield (gate_id, check) preserving report order."""
    out = []
    for gid, gate in (report.get("gates") or {}).items():
        for c in gate.get("checks", []):
            out.append((gid, c))
    return out


def _check_margin(c: Mapping) -> float | None:
    """Raw measured headroom like site.margins: threshold-value for <= else inverse."""
    v = c.get("value")
    if not _isnum(v):
        return None
    t = c.get("threshold")
    if t is None:
        return None
    sign = 1 if c.get("op", "<=") == "<=" else -1
    return sign * (t - v)


def _clip11(x: float) -> float:
    return max(-1.0, min(1.0, x))


def _score_component(c: Mapping) -> float:
    """Single-check contribution for sweep margin_score (existing formula)."""
    if c.get("value") is None:
        return 0.0
    if c.get("status") == GO and not c.get("threshold"):
        return 0.0
    if not c.get("threshold"):
        return -1.0
    sign = 1 if c.get("op") == "<=" else -1
    margin = sign * (c["threshold"] - c["value"]) / abs(c["threshold"])
    return _clip11(margin)


class GateCheck(Mapping):
    """A single gate check; dict-like for compat, exposes requested attributes."""

    def __init__(self, gate_id: str, data: Mapping):
        self.gate = gate_id
        self._data = dict(data)

    @property
    def name(self) -> str:
        return self.metric

    @property
    def metric(self) -> str:
        return self._data["metric"]

    @property
    def value(self):
        return self._data.get("value")

    @property
    def threshold(self):
        return self._data.get("threshold")

    @property
    def op(self) -> str:
        return self._data.get("op", "<=")

    @property
    def status(self) -> str:
        return self._data.get("status", NOT_MEASURED)

    @property
    def margin(self) -> float | None:
        return _check_margin(self._data)

    @property
    def site_margin_component(self) -> float:
        if self.value is None:
            return 0.0
        t = self.threshold or 0
        denom = abs(t) if t not in (0, 0.0) else 1
        sign = 1 if self.op == "<=" else -1
        return _clip11(sign * (t - self.value) / denom)

    @property
    def improves_component(self) -> float:
        if self.value is None:
            return 0.0
        t = self.threshold
        if t in (None, 0, 0.0):
            return 0.0
        sign = 1 if self.op == "<=" else -1
        return _clip11(sign * (t - self.value) / abs(t))

    def __getitem__(self, key):
        return self._data[key]

    def __iter__(self):
        return iter(self._data)

    def __len__(self):
        return len(self._data)

    def get(self, key, default=None):
        return self._data.get(key, default)

    def to_dict(self) -> dict:
        return dict(self._data)


class GateReport(Mapping):
    """Interprets a gates.json report for a build dir."""

    def __init__(self, data: Mapping):
        self._data = json.loads(json.dumps(data))
        self._checks = [GateCheck(gid, c) for gid, c in _report_checks(self._data)]

    @classmethod
    def load(cls, build_dir: str | Path) -> "GateReport":
        path = Path(build_dir) / "gates.json"
        return cls(json.loads(path.read_text()))

    @classmethod
    def from_dict(cls, data: Mapping) -> "GateReport":
        return cls(data)

    @property
    def verdict(self) -> str:
        return self._data.get("verdict", NOT_MEASURED)

    @property
    def checks(self) -> list[GateCheck]:
        return list(self._checks)

    @property
    def gates(self) -> dict:
        return self._data.get("gates", {})

    @property
    def total(self) -> int:
        return len(self._checks)

    @property
    def passed(self) -> int:
        return sum(1 for c in self._checks if c.status == GO)

    def margins(self) -> dict[str, float]:
        """Raw per-metric measured headroom (site semantics)."""
        return {c.metric: c.margin for c in self._checks if c.margin is not None}

    def margin_sum(self) -> float:
        """Site-compatible sum of normalised, clipped margins (denom 1 for zero threshold)."""
        return round(sum(c.site_margin_component for c in self._checks), 6)

    def score(self) -> float:
        """Sweep score; parity with margin_score()."""
        return round(sum(_score_component(c) for c in self._checks), 6)

    def to_dict(self) -> dict:
        return json.loads(json.dumps(self._data))

    @property
    def raw(self) -> dict:
        return self._data

    def __getitem__(self, key):
        return self._data[key]

    def __iter__(self):
        return iter(self._data)

    def __len__(self):
        return len(self._data)

    def get(self, key, default=None):
        return self._data.get(key, default)

    def regressions_vs(
        self,
        other=None,
        base_or_tolerance: float | Mapping | None = None,
        gates_spec: dict | None = None,
        *,
        tolerance: float | None = None,
        gates=None,
        run=None,
        base=None,
    ) -> list[dict]:
        """Compare regressions between run/base metrics.

        Contract:
        - ``regressions_vs(run_metrics, base_metrics, gates=...)``: compat form comparing
          explicit metric mappings (2nd positional slot carries base metrics).
        - ``regressions_vs(other, tolerance=..., gates_spec=...)`` (or ``gates=``): compare
          against ``other``/``base`` using gates-spec regression rules/default noise tolerance.
        - Accepts ``gates_spec=`` and compat ``gates=`` for the gates spec; numeric
          ``tolerance`` tolerated (including string-coercible).

        Returns regression list per ``regressions()`` semantics. Raises ``ValueError`` when a
        report-like comparison input is provided but metrics cannot be resolved for that side
        (gates.json reports do not carry manifest metrics), to avoid a misleading empty result.
        """
        spec = gates_spec if gates_spec is not None else gates
        gates_spec_resolved = spec if spec is not None else load_gates()
        tol = gates_spec_resolved.get("noise_tolerance_m", 0.02)
        tol_kw = tolerance
        if tol_kw is not None:
            try:
                tol = float(tol_kw)
            except (TypeError, ValueError):
                tol = gates_spec_resolved.get("noise_tolerance_m", 0.02)

        # Detect positional forms:
        # - API: (other, tolerance_num, gates_spec_dict) or (other, tolerance_num)
        # - Compat: (run_metrics, base_metrics, gates_dict)
        pos2 = base_or_tolerance
        pos3 = gates_spec if gates_spec is not None else None
        compat_pair = False
        if run is None and base is None and isinstance(other, Mapping) and "gates" not in other:
            has_self_metrics = bool(_metrics_for_regressions(self))
            if not has_self_metrics and isinstance(pos2, Mapping):
                # pos3 as gates spec means compat (run, base, gates=spec)
                if isinstance(pos3, Mapping) and ("gates" in pos3 or "noise_tolerance_m" in pos3 or "regression_metrics" in pos3):
                    run_metrics = _metrics_for_regressions(other)
                    base_metrics = _metrics_for_regressions(pos2)
                    run_source, base_source = other, pos2
                    gates_spec_resolved = pos3
                    tol = gates_spec_resolved.get("noise_tolerance_m", 0.02)
                    compat_pair = True
                elif _is_report_like(pos2) and not _metrics_for_regressions(pos2):
                    # (run_metrics, report_like_without_metrics, ...)
                    run_source, base_source = other, pos2
                    run_metrics = _metrics_for_regressions(run_source)
                    base_metrics = {}
                elif pos3 is None and gates is None and tol_kw is None and not _is_report_like(pos2):
                    # classic compat (run, base, gates=kw) or (run, base)
                    run_metrics = _metrics_for_regressions(other)
                    base_metrics = _metrics_for_regressions(pos2)
                    run_source, base_source = other, pos2
                    compat_pair = True
                else:
                    # (run, base, tolerance_num?, ...) API-style compat
                    run_metrics = _metrics_for_regressions(other)
                    base_metrics = _metrics_for_regressions(pos2)
                    run_source, base_source = other, pos2
                    if tol_kw is None and pos3 is not None and not isinstance(pos3, Mapping):
                        try:
                            tol = float(pos3)
                        except (TypeError, ValueError):
                            pass
                    compat_pair = True
            elif not has_self_metrics and pos2 is not None and not isinstance(pos2, Mapping):
                # (other, numeric_tolerance, ...)
                run_source = self
                base_source = other
                run_metrics = _metrics_for_regressions(run_source)
                base_metrics = _metrics_for_regressions(base_source)
                if tol_kw is None:
                    try:
                        tol = float(pos2)
                    except (TypeError, ValueError):
                        pass
            else:
                run_source = run if run is not None else self
                base_source = base if base is not None else other
                run_metrics = _metrics_for_regressions(run_source)
                base_metrics = _metrics_for_regressions(base_source)
        else:
            run_source = run if run is not None else self
            base_source = base if base is not None else other
            run_metrics = _metrics_for_regressions(run_source)
            base_metrics = _metrics_for_regressions(base_source)
            # numeric positional tolerance in API form: (other, 0.02, ...)
            if tol_kw is None and pos2 is not None and not isinstance(pos2, Mapping):
                try:
                    tol = float(pos2)
                except (TypeError, ValueError):
                    pass

        # Report-like inputs without resolvable metrics cannot be compared; fail explicitly
        # rather than returning a false "no regressions" result.
        if not compat_pair:
            if base_source is not None and _is_report_like(base_source) and not base_metrics:
                raise ValueError(
                    "regressions_vs: cannot resolve metrics from report-like base/other "
                    "input (gates reports do not include manifest metrics); pass explicit "
                    "run/base metric mappings or keyword run=/base="
                )
            if run is not None and _is_report_like(run_source) and not run_metrics:
                raise ValueError(
                    "regressions_vs: cannot resolve metrics from report-like run input; "
                    "pass explicit metric mappings"
                )

        # No comparison requested (e.g. report.regressions_vs()): preserve stored regressions
        # snapshot behavior-equivalent empty comparison only when there is nothing to compare.
        if run is None and base is None and other is None and not run_metrics and not base_metrics:
            stored = self.raw.get("regressions")
            return list(stored) if isinstance(stored, list) else []

        return regressions(run_metrics, base_metrics, tol, gates_spec_resolved)

    def improves_on(self, other) -> bool:
        """#222: more go checks, else larger sum of margins normalised by |threshold| clipped to [-1,1].

        Ties are not improvements. Missing/invalid other falls back to publish/True as today.
        """
        if other is None:
            return True
        try:
            cand_gc = self.passed
            cand_ms = self._improves_margin_sum()
            oth = _coerce_comparable(other)
            oth_gc = oth["go_count"]
            oth_ms = oth["improves_margin_sum"]
        except (TypeError, ValueError, KeyError, AttributeError):
            return True
        if oth_gc is None or oth_ms is None:
            return True
        if cand_gc != oth_gc:
            return cand_gc > oth_gc
        return cand_ms > oth_ms

    def _improves_margin_sum(self) -> float:
        return round(sum(c.improves_component for c in self._checks), 6)

    def exit_code(self) -> int:
        return 0 if self.verdict == GO else 1


def _is_report_like(obj) -> bool:
    return isinstance(obj, GateReport) or (
        isinstance(obj, Mapping) and "gates" in obj and ("verdict" in obj or "run_id" in obj or "checks" in obj)
    )


def _metrics_for_regressions(obj) -> dict:
    """Accept report-like (with gates+metrics) or plain metric dicts."""
    if isinstance(obj, GateReport):
        metrics = obj.raw.get("metrics")
        return dict(metrics) if isinstance(metrics, dict) else {}
    if isinstance(obj, Mapping):
        if "gates" in obj and ("verdict" in obj or "run_id" in obj):
            metrics = obj.get("metrics")
            return dict(metrics) if isinstance(metrics, dict) else {}
        metrics = obj.get("metrics")
        if isinstance(metrics, dict) and "gates" not in metrics:
            return dict(metrics)
        # treat as metrics tree (possibly flattened handled by regressions)
        return dict(obj)
    return {}


def _coerce_comparable(other) -> dict:
    if isinstance(other, GateReport):
        return {"go_count": other.passed, "improves_margin_sum": other._improves_margin_sum()}
    if isinstance(other, Mapping):
        # history entry shape: go_count/margin_sum/report; or report dict
        go_count = other.get("go_count")
        margin_sum = other.get("margin_sum")
        if go_count is not None and margin_sum is not None:
            # site stored margin_sum (denom 1 for zero threshold) — accept as comparable proxy
            return {"go_count": go_count, "improves_margin_sum": margin_sum}
        report = other.get("report")
        if isinstance(report, Mapping):
            gr = GateReport(report)
            return {"go_count": gr.passed, "improves_margin_sum": gr._improves_margin_sum()}
        if "gates" in other:
            gr = GateReport(other)
            return {"go_count": gr.passed, "improves_margin_sum": gr._improves_margin_sum()}
        # try stored margins dict fallback? none known
    raise ValueError("uncomparable")


def margin_score(report: dict | GateReport) -> float:
    """Sweep score: the sum over measured checks of the normalised margin
    (threshold - value) / threshold for "<=" and (value - threshold) / threshold for ">=",
    each clipped to [-1, 1]. Positive is headroom, negative is a miss. A zero threshold
    cannot be normalised, so that check scores 0 when it passes and -1 when it fails.
    Not-measured checks add nothing. This is the only place the formula lives."""
    gr = report if isinstance(report, GateReport) else GateReport(report)
    return gr.score()


def _gated_metrics(gates: dict) -> set[str]:
    return set(_gated_ops(gates))


def _gated_ops(gates: dict) -> dict[str, str]:
    out: dict[str, str] = {}
    for gate in (gates or {}).get("gates", {}).values():
        for c in gate.get("checks", []):
            if "metric" in c:
                out[c["metric"]] = c.get("op", "<=")
    return out


def regressions(run: dict, base: dict, tol: float, gates: dict | None = None) -> list[dict]:
    """Gated metrics worse than the baseline by more than tol, or lost since."""
    if gates is None:
        gates = load_gates()
    gated_ops = _gated_ops(gates)
    extra = (gates or {}).get("regression_metrics") or []
    candidates = set(gated_ops) | set(extra)
    cur, old = _flatten(run), _flatten(base)
    found = []
    for name in sorted(candidates):
        higher = gated_ops.get(name) == ">="
        # Error-suffix rule: lower-is-better metrics are only compared when their
        # name ends in a distance-error suffix. Higher-is-better gated metrics
        # (e.g. coverage) are compared regardless of suffix.
        if not higher and not name.endswith(_ERROR_SUFFIXES):
            continue
        was = old.get(name)
        if not _isnum(was):
            continue
        now = cur.get(name)
        if not _isnum(now):
            found.append({"metric": name, "baseline": was, "value": None})
            continue
        if higher:
            if was - now > tol:
                found.append({"metric": name, "baseline": was, "value": now})
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
            manifest.get("metrics", {}), baseline.get("metrics", {}), tol, gates
        )
        report["regressions"] = worse
        report["noise_tolerance_m"] = tol
        statuses.append(NO_GO if worse else GO)
    report["verdict"] = _combine(statuses)
    return report


def render_markdown(report: dict | GateReport) -> str:
    report = report.to_dict() if isinstance(report, GateReport) else report
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


# --- G2 ratchet helpers (shared by autopilot/health) -------------------------

def _find_g2_check(report: Mapping):
    """Select G2 by gate identity; robust to check ordering."""
    gates = (report or {}).get("gates") or {}
    g2 = gates.get("G2")
    if isinstance(g2, Mapping):
        checks = g2.get("checks") or []
        if checks:
            return checks[0]
    # fallback: first check whose metric looks like G2
    for gate in gates.values():
        for c in (gate or {}).get("checks", []):
            if "cross_drive_ground" in str(c.get("metric", "")):
                return c
    return None


def _g2_history_path(store: Path) -> Path:
    return Path(store) / G2_HISTORY_FILE


def read_g2_history(store: Path) -> list[dict]:
    try:
        data = json.loads(_g2_history_path(store).read_text())
        return data if isinstance(data, list) else []
    except (OSError, ValueError, TypeError):
        return []


def g2_entry_from_report(report: Mapping, ts: str | None = None) -> dict | None:
    check = _find_g2_check(report)
    if not isinstance(check, Mapping):
        return None
    value = check.get("value")
    threshold = check.get("threshold")
    if threshold is None or not _isnum(threshold):
        return None
    status = check.get("status")
    if status is None:
        status = NOT_MEASURED if not _isnum(value) else None
    entry = {
        "run_id": report.get("run_id"),
        "value": value,
        "threshold": threshold,
        "status": status or NOT_MEASURED,
    }
    if ts:
        entry["ts"] = ts
    return entry


def _g2_due(history: list[dict]) -> tuple[bool, float | None]:
    if not history:
        return False, None
    last = history[-1]
    thr = last.get("threshold")
    nxt = G2_STEPS.get(thr)
    if not nxt:
        return False, None
    tail = history[-G2_RUN:]
    if len(tail) != G2_RUN:
        return False, None
    ok = all(
        h.get("threshold") == thr and h.get("status") == GO for h in tail
    )
    return ok, (nxt if ok else None)


def record_g2_result(store: Path, report: Mapping | None = None, build_dir: str | Path | None = None):
    """Append latest area G2 result to autopilot/g2_history.json and return due info.

    Dedupe key: (run_id, threshold). Silent on absent/malformed input per autopilot behavior.
    Returns (entry_or_none, due_next_threshold_or_none).
    """
    try:
        if report is None:
            if build_dir is None:
                build_dir = Path(store) / "areas" / "seaport-twin"
            report = json.loads((Path(build_dir) / "gates.json").read_text())
        entry = g2_entry_from_report(report, ts=datetime.now(UTC).isoformat(timespec="seconds"))
        if entry is None or entry.get("run_id") is None:
            return None, None
        history = read_g2_history(store)
        key = (entry["run_id"], entry["threshold"])
        if any((h.get("run_id"), h.get("threshold")) == key for h in history):
            due, nxt = _g2_due(history)
            return None, nxt if due else None
        history.append(entry)
        path = _g2_history_path(store)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(history, indent=2) + "\n")
        due, nxt = _g2_due(history)
        return entry, nxt if due else None
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return None, None


def g2_state(store: Path) -> dict | None:
    """Health view: {threshold, passing_in_a_row} or None."""
    try:
        history = read_g2_history(store)
        if not history:
            return None
        threshold = history[-1].get("threshold")
        if threshold is None:
            return None
        streak = 0
        for h in reversed(history):
            if h.get("threshold") == threshold and h.get("status") == GO:
                streak += 1
            else:
                break
        return {"threshold": threshold, "passing_in_a_row": streak}
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return None
