// Sight lines, same rule as twin/stages/outputs.py _sightlines: from the approach's eye point, one line per side
// (left, right) to the crossing approach, ending at available_m along that approach from its core edge (clipped to
// it). Indeterminate sides have no end.
import type { FacilityGeo, Point } from "@/lib/mapdata";
import type { LegMetric, LegStatus } from "@/lib/runmetrics";

export interface Sight {
  approach: string; // the viewer approach
  side: "left" | "right";
  eye: Point;
  end: Point | null; // null when indeterminate
  status: LegStatus;
}

function segLen(a: Point, b: Point): number {
  return Math.hypot(b[0] - a[0], b[1] - a[1]);
}

/** The point at arc length s along the polyline. */
function pointAt(line: Point[], s: number): Point {
  let acc = 0;
  for (let i = 0; i < line.length - 1; i++) {
    const len = segLen(line[i], line[i + 1]);
    if (acc + len >= s && len > 0) {
      const t = (s - acc) / len;
      const [a, b] = [line[i], line[i + 1]];
      return [a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])];
    }
    acc += len;
  }
  return line[line.length - 1];
}

export function sightsOf(geo: FacilityGeo, legs: Record<string, LegMetric> | undefined): Sight[] {
  const out: Sight[] = [];
  for (const leg of geo.legs) {
    const n = legs?.[leg.approach];
    if (!n) continue;
    for (const side of ["left", "right"] as const) {
      const v = n[side];
      if (!v) continue;
      if (v.status === "indeterminate" || v.available_m === null) {
        out.push({ approach: leg.approach, side, eye: leg.eye, end: null, status: "indeterminate" });
        continue;
      }
      const cross = geo.legs.find((x) => x.approach === v.leg);
      if (!cross) continue;
      const total = cross.line.reduce((s, p, i) => (i ? s + segLen(cross.line[i - 1], p) : s), 0);
      const end = pointAt(cross.line, Math.min(v.available_m, total));
      out.push({ approach: leg.approach, side, eye: leg.eye, end, status: v.status });
    }
  }
  return out;
}
