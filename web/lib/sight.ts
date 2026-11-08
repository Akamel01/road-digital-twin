// Sight lines, same rule as twin/stages/outputs.py _sightlines: the eye point is projected onto its leg,
// and the line runs along the leg for available_m (clipped to the leg). Indeterminate legs have no end.
import type { FacilityGeo, LegNumbers, Point } from "@/lib/mapdata";

export interface Sight {
  approach: string;
  eye: Point;
  end: Point | null; // null when indeterminate
  status: LegNumbers["status"];
}

function segLen(a: Point, b: Point): number {
  return Math.hypot(b[0] - a[0], b[1] - a[1]);
}

/** Distance along the polyline to the point nearest to p. */
function project(line: Point[], p: Point): number {
  let best = Infinity;
  let at = 0;
  let acc = 0;
  for (let i = 0; i < line.length - 1; i++) {
    const [a, b] = [line[i], line[i + 1]];
    const len = segLen(a, b);
    const dx = b[0] - a[0];
    const dy = b[1] - a[1];
    const t = len ? Math.min(1, Math.max(0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / (len * len))) : 0;
    const d = Math.hypot(p[0] - (a[0] + t * dx), p[1] - (a[1] + t * dy));
    if (d < best) {
      best = d;
      at = acc + t * len;
    }
    acc += len;
  }
  return at;
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

export function sightsOf(geo: FacilityGeo, legs: Record<string, LegNumbers> | undefined): Sight[] {
  const out: Sight[] = [];
  for (const leg of geo.legs) {
    const n = legs?.[leg.approach];
    if (!n) continue;
    if (n.status === "indeterminate" || n.available_m === null) {
      out.push({ approach: leg.approach, eye: leg.eye, end: null, status: "indeterminate" });
      continue;
    }
    const total = leg.line.reduce((s, p, i) => (i ? s + segLen(leg.line[i - 1], p) : s), 0);
    const s0 = project(leg.line, leg.eye);
    const end = pointAt(leg.line, Math.min(s0 + n.available_m, total));
    out.push({ approach: leg.approach, eye: leg.eye, end, status: n.status });
  }
  return out;
}
