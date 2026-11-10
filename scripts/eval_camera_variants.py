"""G5 for the three Q5 variants (lidar-only, camera-only, fused) of a run that has the semantics stage.

Usage: eval_camera_variants.py RUN_ID [--store STORE]
Writes <store>/<run>-<variant>/manifest.json (the run's manifest with metrics.accuracy swapped for that variant's)
and runs `twin eval` on each, so gates.json and gates.md sit beside it. Prints the G5 rows side by side.
"""

import argparse
import json
from pathlib import Path

from twin.gates import eval_command, run_dir

p = argparse.ArgumentParser()
p.add_argument("run")
p.add_argument("--store", type=Path)
args = p.parse_args()
src = run_dir(args.run, args.store)
manifest = json.loads((src / "manifest.json").read_text())
variants = manifest["metrics"]["semantics"]["variants"]
rows: dict[str, dict[str, object]] = {}
for name, acc in variants.items():
    dst = src.parent / f"{src.name}-{name}"
    dst.mkdir(exist_ok=True)
    (dst / "manifest.json").write_text(
        json.dumps({**manifest, "metrics": {**manifest["metrics"], "accuracy": acc}})
    )
    eval_command(str(dst), None, None, None)
    for c in json.loads((dst / "gates.json").read_text())["gates"]["G5"]["checks"]:
        rows.setdefault(c["metric"], {})[name] = f"{c['value']} ({c['status']})"
print("\n| metric | " + " | ".join(variants) + " |\n|---|" + "---|" * len(variants))
for metric, by in rows.items():
    print(f"| {metric} | " + " | ".join(str(by.get(v)) for v in variants) + " |")
