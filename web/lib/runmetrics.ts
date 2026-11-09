// Run-level numbers for the right column and the profile strip, read from each drive's manifest.json and
// profile.csv in the showcase bundle. Every value comes from the run; nothing here is estimated.
// Loads are cached per run, so the rail and the profile strip share one fetch.

export type LegStatus = "ok" | "short" | "indeterminate";
export type ElementName = "markings" | "crosswalks" | "curbs";

export interface EntryMetric {
  reference_layer: string;
  p50_m: number;
  p95_m: number;
  coverage: number;
  n: number;
  label: string;
}

export interface LegMetric {
  leg: string;
  required_m: number;
  available_m: number | null;
  available_with_parked_m: number | null;
  status: LegStatus;
  reason: string;
}

export interface RunMetrics {
  run_id: string;
  stages: { name: string; method: string }[];
  params: {
    accuracy: { buffer_m: number };
    isd: { case: string; time_gap_s: number; eye_height_m: number; object_height_m: number };
  };
  load?: { points: number; sweeps: number; facilities: number };
  mask?: { kept: number; removed: number; parked: number };
  align?: { x_drift_m: number; y_drift_m: number };
  ground?: { rmse_m: number; z_disagreement_p95_m: number; height_valid: boolean };
  features?: Partial<Record<ElementName, number>>;
  observed_core?: Record<string, number>;
  accuracy?: { elements?: Partial<Record<ElementName, EntryMetric>>; facilities?: Record<string, EntryMetric> };
  isd?: { case: string; facilities: { facility: string; legs: LegMetric[] }[] };
}

export interface ProfilePoint {
  s: number; // metres along the facility core
  z: number; // ground height, metres
}

export const ELEMENT_NAMES: readonly ElementName[] = ["markings", "crosswalks", "curbs"];

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

/**
 * The profile rows for one facility from the run's profile.csv (facility,line,s_m,z_m,n), read by column
 * name. A facility can have several road lines; this returns the first one. The line picker is a later ticket.
 */
export async function loadProfile(run: string, facility: string): Promise<ProfilePoint[]> {
  const text = await getText(`showcase/${run}/profile.csv`);
  const [header, ...body] = text.trim().split("\n");
  const cols = header.split(",");
  const iFacility = cols.indexOf("facility");
  const iLine = cols.indexOf("line");
  const iS = cols.indexOf("s_m");
  const iZ = cols.indexOf("z_m");
  const rows = body.map((l) => l.trim().split(",")).filter((c) => c[iFacility] === facility);
  const first = rows.length ? rows[0][iLine] : null;
  const out: ProfilePoint[] = [];
  for (const c of rows) {
    if (c[iLine] !== first || !c[iS] || !c[iZ]) continue;
    out.push({ s: Number(c[iS]), z: Number(c[iZ]) });
  }
  return out.sort((a, b) => a.s - b.s);
}

/** Stage method name from the run's manifest, or null when the stage has no record. */
export function methodOf(run: RunMetrics, stage: string): string | null {
  return run.stages.find((s) => s.name === stage)?.method ?? null;
}
