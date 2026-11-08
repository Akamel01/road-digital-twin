"""Plan and profile sheets: DXF (ezdxf R2018, metres) and PDF (A3 landscape).

Plain data in, files out. twin/stages/outputs.py reads the stage files and
passes shaped data here. Plan coordinates are EPSG:32619 metres. Profile x is
distance along the facility (m) and y is ground z drawn at VERTICAL_EXAGGERATION.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import ezdxf
from ezdxf import bbox
from ezdxf.addons.drawing import Frontend, RenderContext
from ezdxf.addons.drawing.matplotlib import MatplotlibBackend
from matplotlib.figure import Figure

Point = tuple[float, float]

A3_LANDSCAPE_IN = (16.54, 11.69)
VERTICAL_EXAGGERATION = 10.0
PAD_M = 5.0  # margin around the content in PDF views
TEXT_H = 0.8  # metres, drawing units
LINE_GAP = 1.6  # metres between title block lines
SCALE_BAR_M = 10.0
RED, GREEN = 1, 3  # ACI colours used for sightlines


def _doc(layers: dict[str, int]) -> ezdxf.document.Drawing:
    doc = ezdxf.new("R2018")
    doc.units = ezdxf.units.M
    for name, colour in layers.items():
        doc.layers.add(name, color=colour)
    return doc


def _text(msp, text: str, xy: Point, layer: str, colour: int | None = None) -> None:
    attribs = {"layer": layer, "insert": xy, "height": TEXT_H}
    if colour is not None:
        attribs["color"] = colour
    msp.add_text(text, dxfattribs=attribs)


def _bounds(points: Sequence[Point]) -> tuple[float, float, float, float]:
    if not points:
        return (0.0, 0.0, 10.0, 10.0)
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return min(xs), min(ys), max(xs), max(ys)


def _title_block(
    msp, x: float, y: float, heading: list[str], source: str, licence: str
) -> float:
    """Heading lines, source and licence from (x, y) downwards. Returns the y after the last line."""
    for i, text in enumerate([*heading, source, licence]):
        _text(msp, text, (x, y - i * LINE_GAP), "TITLE")
    return y - (len(heading) + 2) * LINE_GAP


def _scale_bar(msp, x: float, y: float) -> None:
    """Graphic bar of SCALE_BAR_M metres in two halves, labelled in m."""
    half = SCALE_BAR_M / 2
    for k in range(2):
        x0 = x + k * half
        msp.add_lwpolyline(
            [(x0, y), (x0 + half, y), (x0 + half, y + 0.5), (x0, y + 0.5)],
            close=True,
            dxfattribs={"layer": "TITLE"},
        )
    _text(msp, "0", (x, y - LINE_GAP), "TITLE")
    _text(msp, f"{half:g}", (x + half, y - LINE_GAP), "TITLE")
    _text(msp, f"{SCALE_BAR_M:g} m", (x + SCALE_BAR_M, y - LINE_GAP), "TITLE")


def _north_arrow(msp, x: float, y: float, length: float = 5.0) -> None:
    msp.add_lwpolyline(
        [(x, y + length), (x - length * 0.3, y), (x + length * 0.3, y)],
        close=True,
        dxfattribs={"layer": "NORTH"},
    )
    _text(msp, "N", (x - 0.4, y + length + 0.5), "NORTH")


def write_plan(
    path: Path,
    *,
    lines: dict[str, list[list[Point]]],
    labels: list[tuple[str, Point]],
    sight: list[tuple[Point, Point | None, bool, str]],
    source: str,
    licence: str,
) -> None:
    """Plan sheet.

    lines: layer name -> polylines (MARKINGS, CROSSWALKS, FACILITIES, and CURBS only when present).
    labels: facility id text on FACILITIES, at a point.
    sight: (eye, end, short, text). end None means text only (indeterminate).
    """
    layers = {
        "MARKINGS": 7,
        "CROSSWALKS": 2,
        "FACILITIES": 8,
        "SIGHTLINES": GREEN,
        "TITLE": 7,
        "NORTH": 7,
    }
    if "CURBS" in lines:
        layers["CURBS"] = 5
    doc = _doc(layers)
    msp = doc.modelspace()

    for layer, polylines in lines.items():
        for pts in polylines:
            if len(pts) >= 2:
                msp.add_lwpolyline(
                    pts, close=layer == "FACILITIES", dxfattribs={"layer": layer}
                )
    for text, xy in labels:
        _text(msp, text, xy, "FACILITIES")
    for eye, end, short, text in sight:
        colour = RED if short else GREEN
        if end is None:
            _text(msp, text, eye, "SIGHTLINES", colour)
            continue
        msp.add_line(eye, end, dxfattribs={"layer": "SIGHTLINES", "color": colour})
        _text(msp, text, end, "SIGHTLINES", colour)

    all_pts = [p for polylines in lines.values() for pts in polylines for p in pts]
    all_pts += [xy for _, xy in labels]
    x0, y0, x1, y1 = _bounds(all_pts)
    y_end = _title_block(msp, x0, y0 - 5, ["Plan"], source, licence)
    _scale_bar(msp, x0, y_end - 2)
    _north_arrow(msp, x1 + 3, y1 - 6)
    doc.saveas(path)


def write_profile(
    path: Path,
    *,
    profiles: list[tuple[str, list[float], list[float]]],
    height_valid: bool,
    source: str,
    licence: str,
) -> None:
    """Profile sheet, one block per facility: (label, s_m, z_m).

    With height_valid false the line is replaced by "indeterminate (height)".
    """
    doc = _doc({"PROFILE": 5, "AXES": 7, "TITLE": 7})
    msp = doc.modelspace()
    s_max = max([s for _, ss, _ in profiles for s in ss] or [10.0])

    cursor = 0.0
    for label, s, z in profiles:
        base = cursor - 2.5
        _text(msp, label, (0, cursor), "PROFILE")
        msp.add_line((0, base), (s_max, base), dxfattribs={"layer": "AXES"})
        if not height_valid:
            _text(msp, "indeterminate (height)", (1, base + 1), "PROFILE")
            cursor = base - 3
            continue

        zmin, zmax = min(z), max(z)
        plot_h = (zmax - zmin) * VERTICAL_EXAGGERATION
        msp.add_line((0, base), (0, base + plot_h + 0.5), dxfattribs={"layer": "AXES"})
        zt = (
            (zmin // 0.5 + 1) * 0.5 if zmin % 0.5 else zmin
        )  # first tick at or above zmin
        while zt <= zmax + 1e-9:
            y = base + (zt - zmin) * VERTICAL_EXAGGERATION
            msp.add_line((-0.4, y), (0, y), dxfattribs={"layer": "AXES"})
            _text(msp, f"{zt:.1f} m", (-3.2, y - 0.3), "AXES")
            zt += 0.5
        for st in range(0, int(s_max) + 1, 5):
            msp.add_line((st, base), (st, base - 0.4), dxfattribs={"layer": "AXES"})
            _text(msp, f"{st} m", (st - 0.5, base - 1.2), "AXES")
        pts = [(si, base + (zi - zmin) * VERTICAL_EXAGGERATION) for si, zi in zip(s, z)]
        if len(pts) >= 2:
            msp.add_lwpolyline(pts, dxfattribs={"layer": "PROFILE"})
        cursor = base - plot_h - 4

    heading = [
        "Descriptive profile (not an accuracy claim)",
        f"Vertical exaggeration {VERTICAL_EXAGGERATION:g}x (vertical scale {VERTICAL_EXAGGERATION:g} times horizontal)",
    ]
    y_end = _title_block(msp, 0.0, cursor - 1, heading, source, licence)
    _scale_bar(msp, 0.0, y_end - 2)
    doc.saveas(path)


def render_pdf(dxf_path: Path, pdf_path: Path) -> None:
    """Draw a DXF to an A3 landscape PDF with the ezdxf drawing add-on (matplotlib backend).

    The view fits everything except sight lines, so a long line does not shrink the sheet.
    """
    doc = ezdxf.readfile(dxf_path)
    msp = doc.modelspace()
    fig = Figure(figsize=A3_LANDSCAPE_IN, facecolor="white")
    ax = fig.add_axes((0.0, 0.0, 1.0, 1.0))
    ax.set_facecolor("white")
    Frontend(RenderContext(doc), MatplotlibBackend(ax)).draw_layout(msp, finalize=True)
    ext = bbox.extents([e for e in msp if e.dxf.layer != "SIGHTLINES"], fast=True)
    if ext.has_data:
        ax.set_xlim(ext.extmin.x - PAD_M, ext.extmax.x + PAD_M)
        ax.set_ylim(ext.extmin.y - PAD_M, ext.extmax.y + PAD_M)
    fig.savefig(pdf_path, format="pdf", facecolor="white")
