"""Training entry point for the marking-type model.

Camera route is the primary route (Mapillary Vistas v2.0 fine-tune); BEV is
documented as a fallback and is not implemented here. GPU access is gated
through ``twin.gpulease.lease``; the script aborts (with a warning) when the
lease reports ``record["ok"] is False``.

Training deps (torch/transformers) are imported lazily so importing this module
stays cheap and CI-safe. No datasets are shipped in the repo.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

HOLDOUT_BBOX_DEFAULT = (332112, 332668, 4689895, 4690292)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--route", choices=("camera", "bev"), default="camera")
    p.add_argument("--root", type=Path, default=None, help="dataset root (under /data)")
    p.add_argument("--out", type=Path, default=Path("/data/models/marking-type"))
    p.add_argument("--max-epochs", type=int, default=30)
    p.add_argument("--holdout-buffer", type=float, default=50.0)
    return p.parse_args(argv)


def _run_camera(args: argparse.Namespace, record: dict[str, Any]) -> int:
    from twin.marking_types import HOLDOUT_BBOX_DEFAULT as HB
    from twin.marking_types import load_samples

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    samples = list(
        load_samples("camera", args.root, holdout_bbox=HB, buffer=args.holdout_buffer)
    )

    manifest = {
        "dataset": "mapillary_vistas_v2",
        "version": "2.0",
        "paths": {"root": str(args.root) if args.root is not None else None},
        "held_out_box": {
            "epsg32619": list(HB),
            "buffer": args.holdout_buffer,
        },
        "counts": {"samples": len(samples)},
        "seed": None,
    }
    (out / "data_manifest.json").write_text(json.dumps(manifest, indent=2))
    (out / "LICENCES").write_text(
        "Mapillary Vistas v2.0 labels: CC BY-NC-SA 4.0 (non-commercial, share-alike).\n"
        "v1.2 pretrained backbone weights: see Hugging Face license tags.\n"
    )

    print(
        "Scaffold only: no training run performed. Operator must accept Vistas v2.0 "
        "terms, download under --root, then run training with torch/transformers "
        "installed (--extra marking). Training loop, per-class validation, plateau "
        "detection and checkpoint writing are operator-gated follow-ups.",
        file=sys.stderr,
    )
    summary = {
        "route": "camera",
        "samples": len(samples),
        "manifest_path": str(out / "data_manifest.json"),
        "licence_path": str(out / "LICENCES"),
    }
    print(json.dumps(summary))
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    if args.route == "bev":
        print(
            "BEV route not implemented: see docs/research/marking-type-model.md "
            "(fallback only; not built in #306).",
            file=sys.stderr,
        )
        return 2

    from twin import gpulease

    record: dict[str, Any] = {}
    with gpulease.lease(record) as rec:
        if not bool(rec.get("ok", False)):
            print(
                "gpulease WARNING: lease not ok; aborting training",
                file=sys.stderr,
            )
            return 1
        return _run_camera(args, rec)


if __name__ == "__main__":
    raise SystemExit(main())
