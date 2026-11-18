#!/usr/bin/env python3
"""Measurement fixture for #288: composite per-drive tiles into per-layer mosaics.

NOT production code. See twin/tiles.py::write_mosaic_tiles for the real publisher.
"""
import argparse
import json
import math
import shutil
from pathlib import Path

import numpy as np
from PIL import Image

TILE = 256
MOSAIC_RASTERS = ["lidar", "ortho", "height", "coverage"]


def _copytree(src, dst):
    if dst.exists():
        shutil.rmtree(dst)
    if src.exists():
        shutil.copytree(src, dst)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--source", default="unknown")
    args = ap.parse_args()

    src = Path(args.src)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    fixture_showcase = out / "showcase"
    if fixture_showcase.exists():
        shutil.rmtree(fixture_showcase)
    fixture_showcase.mkdir(parents=True)

    # Copy top-level files
    for f in ("area.json", "publish_report.json"):
        if (src / f).exists():
            shutil.copy2(src / f, fixture_showcase / f)

    area = json.loads((fixture_showcase / "area.json").read_text())
    drives = area["drives"]

    # Copy per-run files + per-drive tile trees (BEFORE layout)
    per_file_status = {}
    for d in drives:
        rid = d["run_id"]
        rsrc = src / rid
        rdst = fixture_showcase / rid
        rdst.mkdir(parents=True, exist_ok=True)
        for f in ("manifest.json", "twin.geojson", "profile.csv", "centrelines.geojson"):
            s = rsrc / f
            if s.exists():
                shutil.copy2(s, rdst / f)
                per_file_status.setdefault(rid, {})[f] = {"status": 200, "bytes": s.stat().st_size}
            else:
                per_file_status.setdefault(rid, {})[f] = {"status": 404, "bytes": 0}
        # tiles
        tsrc = src / "tiles" / rid
        tdst = fixture_showcase / "tiles" / rid
        if tsrc.exists():
            shutil.copytree(tsrc, tdst)

    # bbox
    xs0 = [d["bbox"][0] for d in drives]
    ys0 = [d["bbox"][1] for d in drives]
    xs1 = [d["bbox"][2] for d in drives]
    ys1 = [d["bbox"][3] for d in drives]
    x0 = min(xs0)
    y0 = min(ys0)
    extent = max(max(x - x0 for x in xs1), max(y - y0 for y in ys1))

    # per-layer cell + zmax
    layer_cell = {}
    layer_zmax = {}
    for layer in MOSAIC_RASTERS:
        cells = []
        for d in drives:
            rid = d["run_id"]
            meta_path = src / "tiles" / rid / layer / "meta.json"
            if meta_path.exists():
                m = json.loads(meta_path.read_text())
                if "cell_m_at_zmax" in m:
                    cells.append(m["cell_m_at_zmax"])
        if cells:
            cell = min(cells)
            zmax = math.ceil(math.log2(extent / (TILE * cell)))
            zmax = min(zmax, 8)
            zmax = max(zmax, 0)
        else:
            cell = extent / (TILE * 16)
            zmax = 4
        layer_cell[layer] = cell
        layer_zmax[layer] = zmax

    # Determine which layers actually have drives
    layers_present = [l for l in MOSAIC_RASTERS if any(
        (src / "tiles" / d["run_id"] / l).exists() for d in drives)]

    # Composite + write mosaic
    import twin.publish as pub
    from twin.tiles import write_mosaic_tiles

    layer_tiles_bytes = {}
    for layer in layers_present:
        zmax = layer_zmax[layer]
        side = TILE * (2 ** zmax)
        canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
        for d in drives:
            rid = d["run_id"]
            tdir = src / "tiles" / rid / layer
            meta_path = tdir / "meta.json"
            if not meta_path.exists():
                continue
            meta = json.loads(meta_path.read_text())
            dz = meta.get("zmax", 0)
            native_side = TILE * (2 ** dz)
            # build drive image
            img = Image.new("RGBA", (native_side, native_side), (0, 0, 0, 0))
            for zdir in [tdir / str(dz)]:
                if not zdir.exists():
                    continue
                for xf in zdir.iterdir():
                    if not xf.is_dir():
                        continue
                    try:
                        xi = int(xf.name)
                    except ValueError:
                        continue
                    for yf in xf.iterdir():
                        if yf.suffix != ".webp":
                            continue
                        try:
                            yi = int(yf.stem)
                        except ValueError:
                            continue
                        tile_img = Image.open(yf).convert("RGBA")
                        img.paste(tile_img, (xi * TILE, yi * TILE), tile_img)
            # position in area image space
            mb = meta.get("bbox", d["bbox"])
            # image-space: x offset from west; y offset from north (top)
            area_north = y0 + extent  # since y0=min (south), north = y0+extent
            drive_north = mb[3]
            ox = (mb[0] - x0) / extent * side
            oy = (area_north - drive_north) / extent * side
            drv_w = (mb[2] - mb[0]) / extent * side
            drv_h = (mb[3] - mb[1]) / extent * side
            if drv_w < 1 or drv_h < 1:
                continue
            resized = img.resize((max(1, round(drv_w)), max(1, round(drv_h))), Image.Resampling.NEAREST)
            canvas.paste(resized, (round(ox), round(oy)), resized)

        meta_out = {
            "crs": "EPSG:32619",
            "bbox": [float(x0), float(y0), float(x0 + extent), float(y0 + extent)],
            "tile_px": TILE,
            "zmin": 0,
            "zmax": int(zmax),
            "cell_m_at_zmax": float(layer_cell[layer]),
        }
        write_mosaic_tiles(fixture_showcase, layer, np.asarray(canvas), zmax, (x0, y0, x0 + extent, y0 + extent), meta_out)
        # count
        ldir = fixture_showcase / "tiles" / layer
        nfiles = len(list(ldir.rglob("*.webp")))
        nbytes = sum(p.stat().st_size for p in ldir.rglob("*.webp"))
        layer_tiles_bytes[layer] = {"tiles": nfiles, "bytes": nbytes}

    # tile_version
    try:
        report_path = fixture_showcase / "publish_report.json"
        if report_path.exists():
            rep = json.loads(report_path.read_text())
        else:
            rep = {}
        rep["tile_version"] = pub._tile_version(fixture_showcase)
        # also set layers maybe
        rep.setdefault("layers", {})
        report_path.write_text(json.dumps(rep, indent=2))
    except Exception as e:  # noqa: BLE001 - fixture best-effort version stamp
        (out / "version_error.txt").write_text(str(e))

    # provenance
    provenance = {
        "source": args.source,
        "drives": [d["run_id"] for d in drives],
        "bbox": [float(x0), float(y0), float(x0 + extent), float(y0 + extent)],
        "extent": float(extent),
        "layers": {l: {"cell": layer_cell[l], "zmax": layer_zmax[l], **layer_tiles_bytes.get(l, {})} for l in layers_present},
        "per_file": per_file_status,
    }
    (out / "provenance.json").write_text(json.dumps(provenance, indent=2))
    print(f"fixture written to {out} ({len(drives)} drives, extent {extent:.1f}m)")


if __name__ == "__main__":
    main()
