import { fmt } from "./latest";

export const METRIC_KEYS = [
  "psnr",
  "ssim",
  "road_depth_p50_m",
  "road_depth_p95_m",
  "sidewalk_depth_p50_m",
  "sidewalk_depth_p95_m",
  "lidar_all_p50_m",
  "lidar_all_p95_m",
  "lidar_ground_p50_m",
  "lidar_ground_p95_m",
] as const;

export type MetricKey = (typeof METRIC_KEYS)[number];

export interface EvalRun {
  id: string;
  date: string;
  approach: string;
  variant: string;
  ticket: number;
  iterations: number;
  train_minutes: number | null;
  gaussian_cap: number | null;
  eval_set: string;
  notes: string;
  metrics: Partial<Record<MetricKey, number>>;
}

export interface PassBar {
  psnr_min: number;
  road_depth_p95_max_m: number;
}

export interface EvalRegistry {
  pass_bar: PassBar;
  runs: EvalRun[];
}

export interface Headline {
  key: MetricKey;
  label: string;
  unit: string;
  dir: "up" | "down";
  log: boolean;
  barKey?: "psnr_min" | "road_depth_p95_max_m";
}

export const HEADLINE: readonly Headline[] = [
  { key: "psnr", label: "PSNR", unit: "dB", dir: "up", log: false, barKey: "psnr_min" },
  { key: "road_depth_p95_m", label: "Road depth p95", unit: "m", dir: "down", log: true, barKey: "road_depth_p95_max_m" },
  { key: "lidar_ground_p50_m", label: "LiDAR ground p50", unit: "m", dir: "down", log: true },
];

export const TOKENS: readonly string[] = [
  "var(--feat-cross)",
  "var(--sight)",
  "var(--fac)",
  "var(--pa-accent)",
  "var(--feat-mark)",
];

export const DASHES: readonly string[] = ["none", "6 3", "2 3", "9 3 2 3", "4 2"];

export function barValue(spec: Headline, bar: PassBar): number | undefined {
  if (!spec.barKey) return undefined;
  return spec.barKey === "psnr_min" ? bar.psnr_min : bar.road_depth_p95_max_m;
}

export function metricValue(run: EvalRun, key: MetricKey): number | undefined {
  const v = run.metrics[key];
  if (typeof v !== "number" || !Number.isFinite(v)) return undefined;
  if (key.endsWith("_m") && v <= 0) return undefined;
  return v;
}

export function runLabel(run: EvalRun): string {
  return run.variant ? `${run.approach} ${run.variant}` : run.approach;
}

export function fmtMetric(v: number | undefined): string {
  if (v === undefined) return "not measured";
  return fmt(v);
}

export function formatCount(n: number): string {
  return n.toLocaleString("en-US");
}

export function approachOrder(runs: EvalRun[]): string[] {
  const out: string[] = [];
  for (const r of runs) {
    if (!out.includes(r.approach)) out.push(r.approach);
  }
  return out;
}

export function approachStyle(runs: EvalRun[], approach: string): { token: string; dash: string } {
  const i = approachOrder(runs).indexOf(approach) % TOKENS.length;
  return { token: TOKENS[i], dash: DASHES[i] };
}

export function latestByApproach(runs: EvalRun[]): EvalRun[] {
  const map = new Map<string, EvalRun>();
  for (const r of runs) map.set(r.approach, r);
  return [...map.values()];
}

export function seriesByApproach(
  runs: EvalRun[],
  key: MetricKey
): { approach: string; points: { x: number; v: number }[] }[] {
  const map = new Map<string, { x: number; v: number }[]>();
  const order: string[] = [];
  runs.forEach((r, i) => {
    const v = metricValue(r, key);
    if (v === undefined) return;
    if (!map.has(r.approach)) {
      map.set(r.approach, []);
      order.push(r.approach);
    }
    map.get(r.approach)!.push({ x: i, v });
  });
  // first-appearance order over all runs, not just those with points
  const fa = approachOrder(runs);
  const result: { approach: string; points: { x: number; v: number }[] }[] = [];
  for (const a of fa) {
    const pts = map.get(a);
    if (pts && pts.length > 0) result.push({ approach: a, points: pts });
  }
  // drop empty already; keep order stable even if fa differs from insertion
  void order;
  return result;
}

export function bestRun(
  runs: EvalRun[],
  key: MetricKey,
  dir: "up" | "down"
): { run: EvalRun; value: number } | null {
  let best: { run: EvalRun; value: number } | null = null;
  for (const r of runs) {
    const v = metricValue(r, key);
    if (v === undefined) continue;
    if (best === null) {
      best = { run: r, value: v };
    } else if (dir === "up" ? v > best.value : v < best.value) {
      best = { run: r, value: v };
    }
  }
  return best;
}

export function gapText(value: number, bar: number | undefined, dir: "up" | "down", unit: string): string {
  if (bar === undefined) return "no bar";
  if (dir === "up") {
    if (value < bar) return `${fmt(bar - value)} ${unit} short of bar`;
    return `meets bar (+${fmt(value - bar)} ${unit})`;
  }
  if (value > bar) return `${fmt(value - bar)} ${unit} over bar`;
  return `meets bar (-${fmt(bar - value)} ${unit})`;
}

export function isPassing(run: EvalRun, bar: PassBar): boolean {
  const psnr = metricValue(run, "psnr");
  const depth = metricValue(run, "road_depth_p95_m");
  if (psnr === undefined || depth === undefined) return false;
  return psnr >= bar.psnr_min && depth <= bar.road_depth_p95_max_m;
}

export function verdict(reg: EvalRegistry): string {
  const runs = reg.runs;
  if (runs.length === 0) return "No evaluation runs recorded yet.";
  const passing = runs.filter((r) => isPassing(r, reg.pass_bar)).length;
  const prefix = passing > 0 ? `${passing} of ${runs.length} runs pass; ` : "No approach passes yet; ";
  const clauses: string[] = [];
  const psnrBest = bestRun(runs, "psnr", "up");
  if (psnrBest) {
    clauses.push(`best PSNR ${fmt(psnrBest.value)} dB (${runLabel(psnrBest.run)}) vs ${fmt(reg.pass_bar.psnr_min)} dB bar`);
  }
  const depthBest = bestRun(runs, "road_depth_p95_m", "down");
  if (depthBest) {
    clauses.push(`best road depth p95 ${fmt(depthBest.value)} m (${runLabel(depthBest.run)}) vs ${fmt(reg.pass_bar.road_depth_p95_max_m)} m bar`);
  }
  if (clauses.length === 0) return prefix + "no metrics recorded";
  return prefix + clauses.join(" · ");
}

export function isBest(value: number | undefined, values: (number | undefined)[], dir: "up" | "down"): boolean {
  if (value === undefined) return false;
  const finite = values.filter((v): v is number => typeof v === "number" && Number.isFinite(v));
  if (finite.length === 0) return false;
  const target = dir === "up" ? Math.max(...finite) : Math.min(...finite);
  return value === target;
}

export function yDomain(
  values: number[],
  bar: number | undefined,
  log: boolean
): { lo: number; hi: number } | null {
  const cand: number[] = [];
  for (const v of values) {
    if (typeof v === "number" && Number.isFinite(v)) cand.push(v);
  }
  if (bar !== undefined && Number.isFinite(bar)) cand.push(bar);
  if (log) {
    const filtered = cand.filter((v) => v > 0);
    if (filtered.length === 0) return null;
    cand.length = 0;
    cand.push(...filtered);
  }
  if (cand.length === 0) return null;
  const w = (v: number) => (log ? Math.log10(v) : v);
  let wLo = Math.min(...cand.map(w));
  let wHi = Math.max(...cand.map(w));
  if (wLo === wHi) {
    if (log) {
      wLo -= 1;
      wHi += 1;
    } else {
      wHi = wLo + 1;
    }
  }
  const pad = (wHi - wLo) * 0.12;
  wLo -= pad;
  wHi += pad;
  if (log) {
    return { lo: 10 ** wLo, hi: 10 ** wHi };
  }
  return { lo: wLo, hi: wHi };
}

export function ticketUrl(ticket: number): string {
  return `https://github.com/Akamel01/road-digital-twin/issues/${ticket}`;
}

export function loadEvaluations(): Promise<EvalRegistry> {
  return fetch("/evals/recon-v2-results.json").then((r) => {
    if (!r.ok) throw new Error(`failed to load evaluations: ${r.status}`);
    return r.json() as Promise<EvalRegistry>;
  });
}
