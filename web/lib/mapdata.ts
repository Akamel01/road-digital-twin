// Loads one drive's plan overlays, element accuracy and raster tile metadata from the static bundle.
// Coordinates stay in EPSG:32619 metres until the map converts them to its frame.

export type Raster = "lidar" | "ortho" | "coverage";
export type ElementKey = "markings" | "crosswalks" | "curbs";

export const ELEMENTS: readonly ElementKey[] = ["markings", "crosswalks", "curbs"];
export const RASTERS: readonly Raster[] = ["lidar", "ortho", "coverage"];

export function isElement(s: string | null): s is ElementKey {
  return s !== null && (ELEMENTS as readonly string[]).includes(s);
}

export interface Line {
  element: ElementKey;
  points: [number, number][];
}

export interface DriveData {
  lines: Line[];
  // Element P95 distance to the HD map, from the run's manifest. Missing elements are left out.
  p95: Partial<Record<ElementKey, number>>;
}

export interface RasterMeta {
  bbox: number[];
  zmax: number;
}

// Error bands from the mockup: <= 0.20 m green, <= 0.40 m amber, above that red.
export const ERR_COL = { good: "#9CC7A4", fair: "#E0A94F", poor: "#E0704F" } as const;

export function errCol(e: number): string {
  return e <= 0.2 ? ERR_COL.good : e <= 0.4 ? ERR_COL.fair : ERR_COL.poor;
}

const KIND: Record<string, ElementKey> = { marking: "markings", crosswalk: "crosswalks", curb: "curbs" };

async function getJson<T>(url: string): Promise<T> {
  const res = await fetch(url, { cache: "no-cache" });
  if (!res.ok) throw new Error(`Could not load ${url}`);
  return (await res.json()) as T;
}

interface GeoJson {
  features: { properties: { kind?: string }; geometry: { type: string; coordinates: number[][] } }[];
}

interface Manifest {
  metrics: { accuracy?: { elements?: Record<string, { p95_m: number }> } };
}

export async function loadDrive(run: string): Promise<DriveData> {
  const [geo, man] = await Promise.all([
    getJson<GeoJson>(`showcase/${run}/twin.geojson`),
    getJson<Manifest>(`showcase/${run}/manifest.json`),
  ]);
  const lines: Line[] = [];
  for (const f of geo.features) {
    const element = KIND[f.properties.kind ?? ""];
    if (!element || f.geometry.type !== "LineString") continue;
    lines.push({
      element,
      points: f.geometry.coordinates.map(([x, y]): [number, number] => [x, y]),
    });
  }
  const p95: Partial<Record<ElementKey, number>> = {};
  for (const e of ELEMENTS) {
    const v = man.metrics.accuracy?.elements?.[e]?.p95_m;
    if (typeof v === "number") p95[e] = v;
  }
  return { lines, p95 };
}

export function loadRasterMeta(run: string, raster: Raster): Promise<RasterMeta> {
  return getJson<RasterMeta>(`showcase/tiles/${run}/${raster}/meta.json`);
}
