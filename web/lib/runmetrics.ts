// Run-level numbers for the right column and the profile strip, read from each drive's manifest.json and
// profile.csv in the showcase bundle. Every value comes from the run; nothing here is estimated.
// Loads are cached per run, so the rail and the profile strip share one fetch.

export type LegStatus = "ok" | "short" | "indeterminate";
export type ElementName = "markings" | "crosswalks" | "curbs";

// One accuracy entry, as twin/stages/accuracy.py writes it. Metrics are null when the entry has a reason
// (for example "not scanned enough" or "no observed elements").
export interface EntryMetric {
  reference_layer: string;
  p50_m: number | null;
  p95_m: number | null;
  coverage: number | null;
  n: number;
  n_samples: number;
  label: string;
  reason: string;
}

// One side of an approach: the view to the left or right, along the crossing approach named in leg.
export interface SideMetric {
  leg: string;
  available_m: number | null;
  available_with_parked_m: number | null;
  status: LegStatus;
}

// One approach (viewer leg). Its status is the worse of its two sides; a null side has no crossing approach.
export interface LegMetric {
  leg: string;
  required_m: number;
  left: SideMetric | null;
  right: SideMetric | null;
  status: LegStatus;
  reason: string;
}

const RANK: Record<LegStatus, number> = { ok: 0, short: 1, indeterminate: 2 };

/** The side that sets the leg's status: the worse status, then the shorter available distance. Null if no side. */
export function worseSide(leg: LegMetric): { side: "left" | "right"; m: SideMetric } | null {
  const sides = (["left", "right"] as const).flatMap((side) => (leg[side] ? [{ side, m: leg[side] }] : []));
  if (sides.length === 0) return null;
  return sides.reduce((w, s) => {
    const by = RANK[s.m.status] - RANK[w.m.status];
    if (by !== 0) return by > 0 ? s : w;
    return (s.m.available_m ?? -1) < (w.m.available_m ?? -1) ? s : w;
  });
}

/** Both sides on one line, for a title tooltip: "L E: 104 m (104 m with parked) · R W: no crossing approach". */
export function sideDetail(leg: LegMetric): string {
  const part = (label: string, m: SideMetric | null) => {
    if (!m) return `${label}: no crossing approach`;
    const val = m.available_m === null ? "indeterminate" : `${m.available_m} m (${m.available_with_parked_m ?? "—"} m with parked)`;
    return `${label} ${m.leg}: ${val}`;
  };
  return `${part("L", leg.left)} · ${part("R", leg.right)}`;
}

export interface RunMetrics {
  run_id: string;
  stages: { name: string; method: string }[];
  params: {
    accuracy: { buffer_m: number };
    isd: { case: string; time_gap_s: number; eye_height_m: number; object_height_m: number };
  };
  // Keys below are the stage metrics the runner stores under each stage name (twin/runner.py).
  load?: { n_sweeps: number; n_points: number; n_facilities: number };
  mask?: { n_in: number; n_kept: number; n_parked: number; n_dropped_moving: number };
  align?: { xy_drift_p50_m: number | null; xy_drift_p95_m: number | null; yaw_drift_p95_deg: number | null };
  ground?: {
    rmse_m: number;
    z_disagreement_p95_m: number;
    height_valid: boolean;
    observed_core: Record<string, number>;
    not_scanned_enough: string[];
  };
  features?: { n_markings?: number; n_crosswalks?: number; n_curbs?: number };
  colour?: { edge_offset_p95_m: number | null; height_valid: boolean };
  accuracy?: { method?: string; buffer_m?: number; elements?: Partial<Record<ElementName, EntryMetric>>; facilities?: Record<string, EntryMetric> };
  isd?: { case: string; facilities: { facility: string; legs: LegMetric[] }[] };
}

export interface ProfilePoint {
  s: number; // metres along the facility core
  z: number; // ground height, metres
}

export const ELEMENT_NAMES: readonly ElementName[] = ["markings", "crosswalks", "curbs"];

/** Feature count key in the features stage metrics, per element. */
export const FEATURE_COUNT: Record<ElementName, keyof NonNullable<RunMetrics["features"]>> = {
  markings: "n_markings",
  crosswalks: "n_crosswalks",
  curbs: "n_curbs",
};

export const ELEMENT_LABEL: Record<ElementName, string> = {
  markings: "Lane markings",
  crosswalks: "Crosswalks",
  curbs: "Curbs",
};

async function getText(url: string): Promise<string> {
  const res = await fetch(url, { cache: "no-cache" });
  if (!res.ok) throw new Error(`Could not load ${url}`);
  return res.text();
}

const runs = new Map<string, Promise<RunMetrics>>();

export function loadRunMetrics(run: string): Promise<RunMetrics> {
  let p = runs.get(run);
  if (!p) {
    p = getText(`showcase/${run}/manifest.json`).then((text) => {
      const raw = JSON.parse(text) as { run_id: string; stages: RunMetrics["stages"]; params: RunMetrics["params"]; metrics: Omit<RunMetrics, "run_id" | "stages" | "params"> };
      return {
        run_id: raw.run_id,
        stages: raw.stages.map(({ name, method }) => ({ name, method })),
        params: raw.params,
        ...raw.metrics,
      };
    });
    runs.set(run, p);
  }
  return p;
}

export interface ProfileLine {
  id: string; // "facility/label", the same id as centrelines.geojson's line property
  label: string; // direction label, e.g. "N-S"
  points: ProfilePoint[];
}

/**
 * Every road line of one facility from the run's profile.csv (facility,line,s_m,z_m,n), read by column
 * name, in the order the lines first appear. Each line's points are sorted by s.
 */
export async function loadProfile(run: string, facility: string): Promise<ProfileLine[]> {
  const text = await getText(`showcase/${run}/profile.csv`);
  const [header, ...body] = text.trim().split("\n");
  const cols = header.split(",");
  const iFacility = cols.indexOf("facility");
  const iLine = cols.indexOf("line");
  const iS = cols.indexOf("s_m");
  const iZ = cols.indexOf("z_m");
  const lines = new Map<string, ProfilePoint[]>();
  for (const l of body) {
    const c = l.trim().split(",");
    if (c[iFacility] !== facility || !c[iS] || !c[iZ]) continue;
    const pts = lines.get(c[iLine]) ?? [];
    pts.push({ s: Number(c[iS]), z: Number(c[iZ]) });
    lines.set(c[iLine], pts);
  }
  return [...lines].map(([id, points]) => ({
    id,
    label: id.slice(id.indexOf("/") + 1),
    points: points.sort((a, b) => a.s - b.s),
  }));
}

/** Stage method name from the run's manifest, or null when the stage has no record. */
export function methodOf(run: RunMetrics, stage: string): string | null {
  return run.stages.find((s) => s.name === stage)?.method ?? null;
}
