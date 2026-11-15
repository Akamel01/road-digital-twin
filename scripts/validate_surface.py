"""Plane vs curved per-drive height surface with leave-pairs-out validation (issue #207). Usage:
python scripts/validate_surface.py <area.json> <merged-folder> [ref]
Each fold fits on 80% of the pairs and scores the held-out 20% (median and worst pair P95, metres)."""

import sys

import numpy as np
from diagnose_registration import load

from twin import merge


def score(cells, coef, pairs):
    v = []
    for a, b in pairs:
        r = merge.ground_disagreement(
            merge.apply_cells(cells[a], coef[a]), merge.apply_cells(cells[b], coef[b])
        )
        if r:
            v.append(r["p95_m"])
    return v


if __name__ == "__main__":
    cells = load(sys.argv[1], sys.argv[2])
    ref = sys.argv[3] if len(sys.argv) > 3 else "scene-0255"
    ids = sorted(cells)
    plane = merge.fit_surfaces(cells, ref, 1)
    kept, n = merge.reject_layers(
        {k: merge.apply_cells(cells[k], plane[k]) for k in cells}
    )
    kept = {k: {c: cells[k][c] for c in kept[k]} for k in cells}
    print(
        "layer cells dropped",
        {k[6:]: v for k, v in n.items() if v},
        "of",
        {k[6:]: len(cells[k]) for k in ids if n[k]},
    )
    pairs = [
        (a, b)
        for i, a in enumerate(ids)
        for b in ids[i + 1 :]
        if len(cells[a].keys() & cells[b].keys()) >= merge.MIN_CELLS
    ]
    for name, cs in (("raw cells", cells), ("layer cells rejected", kept)):
        for deg, ridge in ((1, 0), (2, 0), (2, 1), (2, 5), (2, 20), (2, 100)):
            full = merge.fit_surfaces(cs, ref, deg, ridge)
            f = score(cs, full, pairs)
            held = []
            for fold in range(5):
                out = [p for i, p in enumerate(pairs) if i % 5 == fold]
                coef = merge.fit_surfaces(cs, ref, deg, ridge, frozenset(out))
                held += score(cs, coef, out)
            print(
                f"{name:22s} deg {deg} ridge {ridge:>3}: all pairs median {np.median(f):.3f} worst {max(f):.3f} | held-out median {np.median(held):.3f} worst {max(held):.3f}"
            )
