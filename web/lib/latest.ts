// Shapes written by twin/site.py (latest_payload). Served from /latest-build/.

export interface GateCheck {
  metric: string;
  op: "<=" | ">=";
  threshold: number;
  value: number | null;
  status: string; // go | no-go | not measured
}

export interface Gate {
  name: string;
  status: string;
  checks: GateCheck[];
}

export interface CloudMeta {
  n_points: number;
  n_total: number;
  voxel_m: number;
  origin: number[];
  span: number[];
  bytes: number;
}

export interface DriveRow {
  index: number;
  scene: string;
  date: string;
  n_points: number;
  role: string;
  fitness: number | null;
  rmse_m: number | null;
}

export interface Scorecard {
  area: string;
  built_at: string;
  published_at: string;
  run_id: string;
  verdict: string;
  gate_passed: boolean;
  gates_version: number;
  gates: Record<string, Gate>;
  cloud: CloudMeta;
  drives: DriveRow[];
}

export interface TrendPoint {
  built_at: string;
  verdict: string;
  metrics: Record<string, number>;
}

export interface Cloud {
  n: number;
  x: Uint16Array;
  y: Uint16Array;
  z: Uint16Array;
  drive: Uint8Array;
}

// Absolute paths: the page lives at /latest, the data at /latest-build.
export async function loadScorecard(): Promise<Scorecard> {
  const res = await fetch("/latest-build/scorecard.json", { cache: "no-cache" });
  if (!res.ok) throw new Error("No latest build has been published yet.");
  return (await res.json()) as Scorecard;
}

export async function loadTrend(): Promise<TrendPoint[]> {
  const res = await fetch("/latest-build/trend.json", { cache: "no-cache" });
  return res.ok ? ((await res.json()) as TrendPoint[]) : [];
}

/** cloud.bin: n uint16 x, n uint16 y, n uint16 z, n uint8 drive (little endian), n = meta.n_points. */
export async function loadCloud(meta: CloudMeta, version: string): Promise<Cloud> {
  const res = await fetch(`/latest-build/cloud.bin?v=${encodeURIComponent(version)}`);
  if (!res.ok) throw new Error("Point cloud not found.");
  const buf = await res.arrayBuffer();
  const n = meta.n_points;
  if (buf.byteLength !== 7 * n) throw new Error("Point cloud has the wrong size.");
  return {
    n,
    x: new Uint16Array(buf, 0, n),
    y: new Uint16Array(buf, 2 * n, n),
    z: new Uint16Array(buf, 4 * n, n),
    drive: new Uint8Array(buf, 6 * n, n),
  };
}

export function fmt(v: number | null): string {
  if (v === null) return "-";
  const a = Math.abs(v);
  return a !== 0 && (a < 0.001 || a >= 10000) ? v.toExponential(2) : String(Math.round(v * 1e4) / 1e4);
}

// Shape written by twin/health.py (public()). Optional: older bundles have no health.json.
export interface Health {
  updated: string;
  processes: Record<string, { alive: boolean; uptime_s: number | null; restarts_1h: number }>;
  queue: { running: number; pending: number };
  tiers: Record<string, { queued: string | null; finished: string | null; failed: { at: string } | null; runs: number; job_hours: number }>;
  idle_min: { cpu: number; gpu: number; queue: number; all: number };
  paused: Record<string, string>;
  disk_free_gb: Record<string, number | null>;
  gpu: { vram_used_mb: number | null; vram_total_mb: number | null; lease: string };
  progress: {
    builds: number;
    g2_ratchet: { threshold: number; passing_in_a_row: number } | null;
    metrics: Record<string, { gate: string; op: string; threshold: number; latest: number; best: number; trend: number[] }>;
  };
  throughput: { runs_per_hour: number };
}

export async function loadHealth(): Promise<Health | null> {
  const res = await fetch("/latest-build/health.json", { cache: "no-cache" });
  return res.ok ? ((await res.json()) as Health) : null;
}
