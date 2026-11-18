"""Per-element scorer against labelled sites (issue #302).

Evaluation module like twin/gates.py / twin/site.py: audit labels are used only
to score. The accuracy matcher is imported, not copied.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import shapely
from shapely.geometry import shape

from twin.contracts import AccuracyParams, SiteMeta
from twin.labels import FEATURE_FILES, list_sites
from twin.stages import accuracy

SCHEMA = 1
METHOD = "labels-one-way"
DENSIFY_M = accuracy.DENSIFY_M
_BUFFER = AccuracyParams()
BUFFER_M = _BUFFER.buffer_m
RADIUS_M = _BUFFER.match_radius_m
ELEMENT_ORDER = ("marking", "crosswalk", "curb", "curb_ramp")
MARKING_TYPE_ORDER = ("divider", "stop_line", "crosswalk_stripe", "other_paint")
LABEL_METRICS: dict[tuple[str, str], tuple[str | None, str | None, str, bool]] = {
    ("marking", "divider"): ("marking", "divider", "markings.geojson", False),
    ("marking", "stop_line"): ("marking", "stop_line", "markings.geojson", False),
    ("marking", "crosswalk_stripe"): (None, "crosswalk_stripe", "markings.geojson", False),
    ("marking", "other_paint"): ("marking", "other_paint", "markings.geojson", False),
    ("crosswalk", "zebra"): ("crosswalk", None, "crosswalks.geojson", True),
    ("crosswalk", "parallel"): ("crosswalk", None, "crosswalks.geojson", True),
    ("curb", "curb"): ("curb", None, "curbs.geojson", False),
    ("curb_ramp", "curb_ramp"): ("curb_ramp", None, "ramps.geojson", False),
}
RAMP_FIELDS = ("running_slope_pct", "cross_slope_pct", "flare_slope_pct", "gutter_step_m")
NOISE = {
    "p95_m": 0.02,  # shortcut: twin/gates.yaml:4 noise_tolerance_m; upgrade when #299 calibrates
    "precision": 0.01,  # shortcut: one TIE_MARGIN unit (twin/site.py:143); upgrade with #299
    "recall": 0.01,  # shortcut: same unit, provisional; upgrade with #299
}
SCORE_ERRORS = (OSError, ValueError, KeyError, TypeError, shapely.errors.ShapelyError)

_MARKING_TYPES = set(accuracy.MARKING_TYPES)
INTERVAL_NOTE = "intervals (shape/segment rules) are not expressible in the label schema; out of scope for v1 (#301)"


def _props(feat: dict) -> dict:
    if isinstance(feat, dict) and "properties" in feat and isinstance(feat["properties"], dict):
        return feat["properties"]
    return feat if isinstance(feat, dict) else {}


def _geom(feat: dict):
    g = feat.get("geometry") if isinstance(feat, dict) and "geometry" in feat else None
    if g is None:
        return None
    return shapely.force_2d(shape(g))


def _make_valid(g):
    if g is None:
        return None
    if not getattr(g, "is_valid", True):
        g = shapely.make_valid(g)
    return shapely.force_2d(g)


def _effective_type(feat: dict) -> str:
    p = _props(feat)
    element = p.get("element")
    if element == "marking":
        src = p.get("source_marking_type")
        if src in _MARKING_TYPES:
            return src
        t = p.get("type")
        if t in ("solid_line", "dashed_line", "edge_line"):
            return "divider"
        if t == "stop_line":
            return "stop_line"
        if t in ("arrow", "text"):
            return "other_paint"
        return t
    return p.get("type")


def _round(v):
    if v is None:
        return None
    return round(float(v), 3)


def _pct(vals):
    if not vals:
        return None
    return float(np.percentile(np.asarray(vals, dtype=float), 95))


def _lineal_parts(g):
    if g is None or g.is_empty:
        return []
    if g.geom_type in ("LineString", "MultiLineString"):
        return [g]
    parts = []
    for gg in getattr(g, "geoms", [g]):
        if gg.geom_type in ("LineString", "MultiLineString"):
            parts.append(gg)
    return parts


def _areal_parts(g):
    if g is None or g.is_empty:
        return []
    if g.geom_type in ("Polygon", "MultiPolygon"):
        return [g]
    parts = []
    for gg in getattr(g, "geoms", [g]):
        if gg.geom_type in ("Polygon", "MultiPolygon"):
            parts.append(gg)
    return parts


def _feeds(file_name: str, props: dict):
    """Return list of (element_slot or None, marking_type_slot or None)."""
    if file_name == "markings.geojson":
        mt = props.get("marking_type")
        if mt == "crosswalk_stripe":
            return [(None, "crosswalk_stripe")]
        mm = mt if mt in _MARKING_TYPES else "other_paint"
        return [("marking", mm)]
    if file_name == "crosswalks.geojson":
        return [("crosswalk", None)]
    if file_name == "curbs.geojson":
        return [("curb", None)]
    if file_name == "ramps.geojson":
        return [("curb_ramp", None)]
    return []


def score_elements(run_features: dict[str, list[dict]], sites: list[tuple[SiteMeta, list[dict]]]) -> dict:
    area_by_slot = {"crosswalk": True}

    element_runs = {s: [] for s in ELEMENT_ORDER}
    element_labels = {s: [] for s in ELEMENT_ORDER}
    mt_runs = {m: [] for m in MARKING_TYPE_ORDER}
    mt_labels = {m: [] for m in MARKING_TYPE_ORDER}

    curb_pairs = []  # (run_props, label_props, dist)
    ramp_pairs = []  # (run_props, label_props, dist)
    all_run_curbs_props = []
    all_label_curbs_props = []
    all_run_ramps_props = []
    all_label_ramps_props = []

    n_excluded_not_observed = 0
    n_excluded_stripes = 0
    absent_files = []
    unmapped: list[dict] = []
    sites_skipped: list[dict] = []
    scored_sites: list[dict] = []

    # absent files
    for fn in FEATURE_FILES:
        if fn not in run_features:
            absent_files.append(fn)

    # observed run features per file
    for fn in FEATURE_FILES:
        if fn in run_features:
            _geoms, excl = accuracy._observed(run_features.get(fn, []) or [])
            n_excluded_not_observed += excl
            # count observed stripes
            if fn == "markings.geojson":
                for f in (run_features.get(fn) or []):
                    if accuracy._observed([f])[0] and _props(f).get("marking_type") == "crosswalk_stripe":
                        n_excluded_stripes += 1

    observed_features_by_file: dict[str, list[dict]] = {}
    for fn in FEATURE_FILES:
        if fn not in run_features:
            observed_features_by_file[fn] = []
            continue
        feats = run_features.get(fn) or []
        kept_feats = []
        for f in feats:
            g, excl = accuracy._observed([f])
            if g:
                kept_feats.append(f)
        observed_features_by_file[fn] = kept_feats

    # site loop
    for site, labels in sorted(sites, key=lambda t: t[0].id):
        site_poly = _make_valid(shape(site.polygon))
        labels = labels or []
        if len(labels) == 0:
            sites_skipped.append({"id": site.id, "reason": "no labels"})
            continue
        # make valid labels
        valid_labels = []
        for lab in labels:
            g = _make_valid(_geom(lab))
            if g is None or g.is_empty:
                unmapped.append({"id": _props(lab).get("id", ""), "reason": "empty label geometry"})
                continue
            valid_labels.append((lab, g))

        # clip run features for this site
        site_run_slots = {s: [] for s in ELEMENT_ORDER}
        site_run_mt = {m: [] for m in MARKING_TYPE_ORDER}
        site_run_curbs = []
        site_run_ramps = []
        site_run_any = False

        for fn in FEATURE_FILES:
            for f in observed_features_by_file.get(fn, []):
                g = _make_valid(_geom(f))
                if g is None or g.is_empty:
                    continue
                props = _props(f)
                # determine if any slot is area
                feeds = _feeds(fn, props)
                is_point = fn == "ramps.geojson"
                # clip
                if is_point:
                    if not site_poly.covers(g):
                        continue
                else:
                    inter = _make_valid(g.intersection(site_poly))
                    if inter is None or inter.is_empty:
                        continue
                    if fn == "crosswalks.geojson":
                        parts = _areal_parts(inter)
                    elif fn == "ramps.geojson":
                        parts = [inter]
                    else:
                        # markings/curbs lines
                        if "crosswalk" in [x[0] for x in feeds] and fn == "crosswalks.geojson":
                            parts = _areal_parts(inter)
                        else:
                            parts = _lineal_parts(inter)
                    if not parts:
                        continue
                    # if multiple parts, keep as separate? We'll extend per feed for each part
                    clipped_parts = parts
                # For points, single
                if is_point:
                    clipped_list = [g]
                else:
                    clipped_list = clipped_parts

                for clipped_g in clipped_list:
                    site_run_any = True
                    for (eslot, mtslot) in feeds:
                        if eslot is not None:
                            site_run_slots[eslot].append(clipped_g)
                        if mtslot is not None:
                            site_run_mt[mtslot].append(clipped_g)
                    if fn == "curbs.geojson":
                        site_run_curbs.append((clipped_g, props))
                    if fn == "ramps.geojson":
                        site_run_ramps.append((clipped_g, props))

        # labels effective mapping
        site_label_slots = {s: [] for s in ELEMENT_ORDER}
        site_label_mt = {m: [] for m in MARKING_TYPE_ORDER}
        site_label_curbs = []
        site_label_ramps = []

        for lab, g in valid_labels:
            p = _props(lab)
            eid = p.get("id", "")
            element = p.get("element")
            eff = _effective_type(lab)
            mapping = LABEL_METRICS.get((element, eff))
            if mapping is None:
                unmapped.append({"id": eid, "reason": "no metric for element/type"})
                continue
            if element == "crosswalk" and g.geom_type not in ("Polygon", "MultiPolygon"):
                unmapped.append({"id": eid, "reason": "non-polygon crosswalk label"})
                continue
            slot, mtslot, _run_source, _area = mapping
            if slot is not None:
                site_label_slots[slot].append(g)
            if mtslot is not None:
                site_label_mt[mtslot].append(g)
            if element == "curb":
                site_label_curbs.append((g, p))
            if element == "curb_ramp":
                site_label_ramps.append((g, p))

        if not site_run_any:
            sites_skipped.append({"id": site.id, "reason": "no extracted elements in site"})
            continue

        # accumulate
        for s in ELEMENT_ORDER:
            element_runs[s].extend(site_run_slots[s])
            element_labels[s].extend(site_label_slots[s])
        for m in MARKING_TYPE_ORDER:
            mt_runs[m].extend(site_run_mt[m])
            mt_labels[m].extend(site_label_mt[m])

        scored_sites.append({"id": site.id, "role": site.role, "version": site.version, "n_labels": len(labels)})
        for _, rp in site_run_curbs:
            all_run_curbs_props.append(rp)
        for _, lp in site_label_curbs:
            all_label_curbs_props.append(lp)
        for _, rp in site_run_ramps:
            all_run_ramps_props.append(rp)
        for _, lp in site_label_ramps:
            all_label_ramps_props.append(lp)

        # attribute pairing
        # curbs: pair run curbs to label curbs one-to-one nearest within radius (geometry distance)
        _pair_items(site_run_curbs, site_label_curbs, curb_pairs, RADIUS_M)
        _pair_items(site_run_ramps, site_label_ramps, ramp_pairs, RADIUS_M)
        # ramp pairs collected

    # Build entries
    entries_elements = {}
    for slot in ELEMENT_ORDER:
        entries_elements[slot] = _share_entry(element_runs[slot], element_labels[slot], area_by_slot.get(slot, False))

    entries_mt = {}
    for mt in MARKING_TYPE_ORDER:
        entries_mt[mt] = _share_entry(mt_runs[mt], mt_labels[mt], False)

    # curb_ramp is count basis, not share. Override.
    # Need count entry for curb_ramp using run/label counts and ramp_pairs distances.
    run_ramp_count = len([g for g in element_runs["curb_ramp"]])  # already pooled geoms
    label_ramp_count = len(element_labels["curb_ramp"])
    # matched count = number of ramp_pairs (unique run/label)
    matched_ramp = len(ramp_pairs)
    ramp_dists = [p[2] for p in ramp_pairs if p[2] is not None]
    if label_ramp_count == 0:
        reason = "no labels for this element"
        measured = False
    elif run_ramp_count == 0:
        reason = "no extracted elements"
        measured = False
    else:
        reason = ""
        measured = True
    entries_elements["curb_ramp"] = {
        "basis": "count",
        "n_extracted": run_ramp_count,
        "n_labels": label_ramp_count,
        "precision": _round(matched_ramp / run_ramp_count) if (measured and run_ramp_count) else (0.0 if measured else None),
        "recall": _round(matched_ramp / label_ramp_count) if (measured and label_ramp_count) else (0.0 if measured else None),
        "p95_m": _round(_pct(ramp_dists)) if (measured and ramp_dists) else None,
        "measured": measured,
        "reason": reason,
    }
    # If measured but no pairs, precision/recall 0.0, p95 None
    if measured and matched_ramp == 0:
        entries_elements["curb_ramp"]["precision"] = 0.0
        entries_elements["curb_ramp"]["recall"] = 0.0

    # attributes
    attributes = _build_attributes(curb_pairs, ramp_pairs, all_run_curbs_props, all_label_curbs_props, all_run_ramps_props, all_label_ramps_props)

    qa = {
        "n_excluded_not_observed": n_excluded_not_observed,
        "n_excluded_crosswalk_stripes": n_excluded_stripes,
        "absent_element_files": sorted(absent_files),
        "unmapped_labels": sorted(unmapped, key=lambda x: x["id"]),
        "sites_skipped": sites_skipped,
        "notes": [INTERVAL_NOTE],
    }

    return {
        "sites": scored_sites,
        "elements": entries_elements,
        "marking_types": entries_mt,
        "attributes": attributes,
        "qa": qa,
    }


def _share_entry(run_geoms, label_geoms, area):
    n_extracted = len(run_geoms)
    n_labels = len(label_geoms)
    ref = shapely.union_all(label_geoms) if label_geoms else shapely.geometry.GeometryCollection()
    # empty check
    if n_labels == 0:
        return {"basis": "sample+area" if area else "sample+length", "n_extracted": n_extracted, "n_labels": n_labels,
                "precision": None, "recall": None, "p95_m": None, "measured": False, "reason": "no labels for this element"}
    if n_extracted == 0:
        return {"basis": "sample+area" if area else "sample+length", "n_extracted": n_extracted, "n_labels": n_labels,
                "precision": None, "recall": None, "p95_m": None, "measured": False, "reason": "no extracted elements"}
    if ref.is_empty:
        return {"basis": "sample+area" if area else "sample+length", "n_extracted": n_extracted, "n_labels": n_labels,
                "precision": None, "recall": None, "p95_m": None, "measured": False, "reason": "empty label geometry"}
    dists = accuracy._vertex_distances(run_geoms, ref)
    matched = accuracy._matched(run_geoms, ref, BUFFER_M, area)
    ref_size = accuracy._size(ref, area)
    precision = float(np.mean(dists <= RADIUS_M)) if len(dists) else 0.0
    recall = min(matched / ref_size, 1.0) if ref_size > 0 else 0.0
    p95 = float(np.percentile(dists, 95)) if len(dists) else None
    basis = "sample+area" if area else "sample+length"
    return {"basis": basis, "n_extracted": n_extracted, "n_labels": n_labels,
            "precision": _round(precision), "recall": _round(recall), "p95_m": _round(p95),
            "measured": True, "reason": ""}


def _pair_items(run_items, label_items, out_pairs, radius):
    used = set()
    for rg, rp in run_items:
        best = None
        best_d = float("inf")
        for li, (lg, lp) in enumerate(label_items):
            if li in used:
                continue
            d = float(rg.distance(lg))
            if d < best_d:
                best_d = d
                best = li
        if best is not None and best_d <= radius:
            used.add(best)
            out_pairs.append((rp, label_items[best][1], best_d))




def _build_attributes(curb_pairs, ramp_pairs, run_curbs_props, label_curbs_props, run_ramps_props, label_ramps_props):
    # curb height
    label_height_count = sum(1 for lp in label_curbs_props if lp.get("height_m") is not None)
    run_height_any = any(rp.get("height_m") is not None for rp in run_curbs_props)
    height_deltas = [abs(rp.get("height_m") - lp.get("height_m")) for rp, lp, d in curb_pairs
                     if rp.get("height_m") is not None and lp.get("height_m") is not None]
    if label_height_count == 0:
        height_reason = "no label carries height_m"
    elif not run_height_any:
        height_reason = "run curbs carry no height_m"
    else:
        height_reason = ""
    height_entry = {
        "n_labels": label_height_count,
        "n_compared": len(height_deltas),
        "p95_abs_delta_m": _round(_pct(height_deltas)) if height_deltas else None,
        "max_abs_delta_m": _round(max(height_deltas)) if height_deltas else None,
        "reason": height_reason,
    }

    # ramp fields
    ramp_entry = {}
    for field in RAMP_FIELDS:
        label_field_count = sum(1 for lp in label_ramps_props if lp.get(field) is not None)
        run_field_any = any(rp.get(field) is not None for rp in run_ramps_props)
        deltas = [abs(rp.get(field) - lp.get(field)) for rp, lp, d in ramp_pairs
                  if rp.get(field) is not None and lp.get(field) is not None]
        if label_field_count == 0:
            reason = f"no label carries {field}"
        elif not run_field_any:
            reason = f"run ramps carry no {field}"
        else:
            reason = ""
        key = "p95_abs_delta_m" if field == "gutter_step_m" else "p95_abs_delta_pct"
        maxkey = "max_abs_delta_m" if field == "gutter_step_m" else "max_abs_delta_pct"
        ramp_entry[field] = {
            "n_labels": label_field_count,
            "n_compared": len(deltas),
            key: _round(_pct(deltas)) if deltas else None,
            maxkey: _round(max(deltas)) if deltas else None,
            "reason": reason,
        }

    return {
        "curb": {"height_m": height_entry},
        "curb_ramp": ramp_entry,
    }


NULL_D = {"d_precision": None, "d_recall": None, "d_p95_m": None}


def publish_decision(candidate: dict, baseline: dict | None, noise: dict[str, float] = NOISE) -> dict:
    if baseline is None:
        return {"baseline": None, "comparable": True, "reason": "no baseline", "publish": True,
                "elements": {el: {"status": "new", **NULL_D} for el in ELEMENT_ORDER}}

    comparable = (
        candidate.get("target_kind") == baseline.get("target_kind")
        and [(s.get("id"), s.get("version"), s.get("label_hash")) for s in candidate.get("sites", [])]
        == [(s.get("id"), s.get("version"), s.get("label_hash")) for s in (baseline.get("sites") or [])]
    )
    if not comparable:
        return {"baseline": baseline.get("target"), "comparable": False,
                "reason": "target kind or label sites changed; publish rule not applicable", "publish": None,
                "elements": {el: {"status": "not compared", **NULL_D} for el in ELEMENT_ORDER}}

    blocked = []
    elements = {}
    improved = []
    for el in ELEMENT_ORDER:
        c = (candidate.get("elements") or {}).get(el)
        b = (baseline.get("elements") or {}).get(el)
        cm = bool(c is not None and c.get("measured"))
        bm = bool(b is not None and b.get("measured"))
        if not bm:
            status = "new" if cm else "not measured"
            d = dict(NULL_D)
        elif c is None or c.get("n_labels", 0) == 0:
            status = "not measured"
            d = dict(NULL_D)
        elif not cm:
            status = "lost"
            d = dict(NULL_D)
            blocked.append(f"{el}: lost")
        else:
            d = {}
            for m_src, m_out in (("precision", "d_precision"), ("recall", "d_recall"), ("p95_m", "d_p95_m")):
                cv = c.get(m_src)
                bv = b.get(m_src)
                if cv is not None and bv is not None:
                    d[m_out] = round(cv - bv, 3)
                else:
                    d[m_out] = None
            dp = d.get("d_precision")
            dr = d.get("d_recall")
            dk = d.get("d_p95_m")
            worse = False
            better = False
            if dp is not None and dp < -noise["precision"]:
                worse = True
            if dr is not None and dr < -noise["recall"]:
                worse = True
            if dk is not None and dk > noise["p95_m"]:
                worse = True
            if dp is not None and dp > noise["precision"]:
                better = True
            if dr is not None and dr > noise["recall"]:
                better = True
            if dk is not None and dk < -noise["p95_m"]:
                better = True
            if worse:
                status = "worse"
            elif better:
                status = "improved"
            else:
                status = "tie"
            d = {"d_precision": dp, "d_recall": dr, "d_p95_m": dk}
        if status == "worse":
            c = (candidate.get("elements") or {}).get(el)
            b = (baseline.get("elements") or {}).get(el)
            dprec = d.get("d_precision")
            drec = d.get("d_recall")
            dp95 = d.get("d_p95_m")
            why = None
            if dprec is not None and dprec < -noise["precision"]:
                why = f"{el}: precision {c.get('precision')} vs {b.get('precision')} ({dprec:+g} < -noise {noise['precision']})"
            elif drec is not None and drec < -noise["recall"]:
                why = f"{el}: recall {c.get('recall')} vs {b.get('recall')} ({drec:+g} < -noise {noise['recall']})"
            elif dp95 is not None and dp95 > noise["p95_m"]:
                why = f"{el}: p95 {c.get('p95_m')} m vs {b.get('p95_m')} m ({dp95:+g} > noise {noise['p95_m']})"
            if why is None:
                why = f"{el}: worse"
            blocked.append(why)
        if status == "improved":
            improved.append(el)
        elements[el] = {"status": status, "d_precision": d["d_precision"], "d_recall": d["d_recall"], "d_p95_m": d["d_p95_m"]}

    publish = not blocked
    if blocked:
        reason = "; ".join(blocked)
    elif improved:
        reason = f"no element worse than baseline (improved: {', '.join(improved)})"
    else:
        reason = "no element worse than baseline (tie)"
    return {"baseline": baseline.get("target"), "comparable": True, "reason": reason,
            "publish": publish, "elements": elements}


def load_baseline(store: Path) -> dict | None:
    from twin import site
    hist = site.history(store)
    return hist[-1].get("score") if hist else None


def score_target(store: Path, target: Path, sites: str = "audit", baseline: dict | None = None) -> tuple[dict | None, str]:
    store = Path(store)
    target = Path(target)
    feat_dir = target / "5_features"
    if not feat_dir.is_dir():
        return (None, "no 5_features")
    run_features: dict[str, list[dict]] = {}
    for fn in FEATURE_FILES:
        p = feat_dir / fn
        if p.is_file():
            run_features[fn] = json.loads(p.read_text()).get("features", [])
    lbl_root = store / "labels"
    if not lbl_root.is_dir():
        return (None, "no labels dir")
    metas = list_sites(store, role=sites)
    if not metas:
        return (None, f"no {sites} label sites")
    sites_list = []
    for sm in metas:
        lp = store / "labels" / sm.id / "labels.geojson"
        labels = json.loads(lp.read_text()).get("features", []) if lp.is_file() else []
        sites_list.append((sm, labels))
    partial = score_elements(run_features, sites_list)
    if not partial.get("sites"):
        return (None, "no usable label sites")

    # add label_hash
    sites_out = []
    for s in partial["sites"]:
        sid = s["id"]
        lp = store / "labels" / sid / "labels.geojson"
        h = hashlib.sha256(lp.read_bytes()).hexdigest()[:12] if lp.is_file() else ""
        sites_out.append({"id": s["id"], "role": s["role"], "version": s["version"],
                          "label_hash": h, "n_labels": s["n_labels"]})

    target_kind = "area" if (target / "merged.npz").is_file() else "run"
    target_name = target.name
    candidate = {"target_kind": target_kind, "sites": sites_out, "elements": partial["elements"]}
    compare = publish_decision(candidate, baseline)
    doc = {
        "schema": SCHEMA,
        "method": METHOD,
        "target": target_name,
        "target_kind": target_kind,
        "sites": sites_out,
        "elements": partial["elements"],
        "marking_types": partial["marking_types"],
        "attributes": partial["attributes"],
        "compare": compare,
        "noise": dict(NOISE),
        "qa": partial["qa"],
    }
    (target / "score.json").write_text(json.dumps(doc, indent=2) + "\n")
    return (doc, "")


def score_command(run: str, sites: str, store: Path | None = None) -> int:
    from twin import site
    from twin.gates import run_dir
    from twin.runner import default_store

    st = Path(store) if store is not None else default_store()
    target = run_dir(run, st)
    if not target.is_dir():
        try:
            target = site.resolve_area(st, run)
        except (RuntimeError, OSError, ValueError, KeyError, TypeError) as exc:
            print(f"cannot score: {exc}", file=sys.stderr)
            return 2
    try:
        baseline = load_baseline(st)
        doc, reason = score_target(st, target, sites=sites, baseline=baseline)
    except (SCORE_ERRORS, site.SiteStop) as exc:
        print(f"cannot score: {exc}", file=sys.stderr)
        return 2
    if doc is None:
        print(f"cannot score: {reason}", file=sys.stderr)
        return 2

    comparable = doc["compare"].get("comparable")
    if comparable is False:
        if sites == "dev":
            print(f"publish: not comparable ({doc['compare'].get('reason')})", file=sys.stderr)
            print("dev labels never decide publishing", file=sys.stderr)
            _print_table(doc, target, sites)
            return 0
        print(f"publish: not comparable ({doc['compare'].get('reason')})", file=sys.stderr)
        _print_table(doc, target, sites)
        return 2

    _print_table(doc, target, sites)
    publish = doc["compare"].get("publish")
    if publish is True:
        print(f"publish: yes ({doc['compare'].get('reason')})")
        return 0
    print(f"publish: no ({doc['compare'].get('reason')})")
    return 1


def _print_table(doc, target, sites):
    baseline = doc["compare"].get("baseline")
    print(f"score {target.name}: labels={sites} sites={len(doc['sites'])} baseline={baseline if baseline is not None else 'none'}")
    print("element        precision  recall   p95_m  n_extracted  n_labels  measured")
    for el in ELEMENT_ORDER:
        e = doc["elements"][el]
        prec = "-" if e.get("precision") is None else e["precision"]
        rec = "-" if e.get("recall") is None else e["recall"]
        p95 = "-" if e.get("p95_m") is None else e["p95_m"]
        meas = "yes" if e.get("measured") else "no"
        print(f"{el:14} {prec!s:>9} {rec!s:>7} {p95!s:>6} {e['n_extracted']:>12} {e['n_labels']:>9}  {meas}")
