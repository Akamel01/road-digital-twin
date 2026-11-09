import type { LegMetric } from "@/lib/runmetrics";

// Loads one drive's plan overlays, facility geometry, sight-line numbers and element accuracy from the
// static bundle. Coordinates stay in EPSG:32619 metres until the map converts them to its frame.

export type Raster = "lidar" | "ortho" | "coverage";
export type ElementKey = "markings" | "crosswalks" | "curbs";
export type Point = [number, number];

export const ELEMENTS: readonly ElementKey[] = ["markings", "crosswalks", "curbs"];
export const RASTERS: readonly Raster[] = ["lidar", "ortho", "coverage"];

export function isElement(s: string | null): s is ElementKey {
  return s !== null && (ELEMENTS as readonly string[]).includes(s);
}

export interface Overlay {
  element: ElementKey;
  closed: boolean; // polygon (crosswalks) or open line
  points: Point[];
}

export interface Leg {
  approach: string;
  line: Point[]; // the leg line, from the facility core outwards
  eye: Point; // eye point on the leg (setback)
}

export interface FacilityGeo {
  id: string;
  ring: Point[];
  legs: Leg[];
}



export interface DriveData {
  lines: Overlay[];
  facilities: FacilityGeo[];
  // Element P95 distance to the HD map, from the run's manifest. Missing elements are left out.
  p95: Partial<Record<ElementKey, number>>;
  // Sight-distance numbers from the manifest: legs[facility id][approach].
  legs: Record<string, Record<string, LegMetric>>;
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

async function getJson<T>(url: string): Promise<T> {
  const res = await fetch(url, { cache: "no-cache" });
  if (!res.ok) throw new Error(`Could not load ${url}`);
  return (await res.json()) as T;
}

interface Geometry {
  type: string;
  coordinates: unknown;
}

interface GeoJson {
  features: { properties: Record<string, unknown>; geometry: Geometry }[];
}

interface Manifest {
  metrics: {
    accuracy?: { elements?: Record<string, { p95_m: number }> };
    isd?: { facilities?: { facility: string; legs: LegMetric[] }[] };
  };
}

const pt = (c: unknown): Point => {
  const [x, y] = c as number[];
  return [x, y];
};

export async function loadDrive(run: string): Promise<DriveData> {
  const [geo, man] = await Promise.all([
    getJson<GeoJson>(`showcase/${run}/twin.geojson`),
    getJson<Manifest>(`showcase/${run}/manifest.json`),
  ]);
  const lines: Overlay[] = [];
  const facilities: FacilityGeo[] = [];
  for (const f of geo.features) {
    const layer = f.properties.layer;
    const g = f.geometry;
    if (layer === "facilities" && g.type === "Polygon") {
      const legs = ((f.properties.legs as { approach: string; geometry: Geometry }[]) ?? []).map((l) => {
        const eye = ((f.properties.eye_points as { approach: string; geometry: Geometry }[]) ?? []).find(
          (e) => e.approach === l.approach,
        );
        return { approach: l.approach, line: (l.geometry.coordinates as unknown[]).map(pt), eye: eye ? pt(eye.geometry.coordinates) : null };
      });
      facilities.push({
        id: String(f.properties.id),
        ring: ((g.coordinates as unknown[][])[0]).map(pt),
        legs: legs.flatMap((l) => (l.eye ? [{ approach: l.approach, line: l.line, eye: l.eye }] : [])),
      });
    } else if (layer === "markings" || layer === "crosswalks" || layer === "curbs") {
      const closed = g.type === "Polygon";
      if (!closed && g.type !== "LineString") continue;
      const coords = (closed ? (g.coordinates as unknown[][])[0] : g.coordinates) as unknown[];
      lines.push({ element: layer, closed, points: coords.map(pt) });
    }
  }
  const p95: Partial<Record<ElementKey, number>> = {};
  for (const e of ELEMENTS) {
    const v = man.metrics.accuracy?.elements?.[e]?.p95_m;
    if (typeof v === "number") p95[e] = v;
  }
  const legs: DriveData["legs"] = {};
  for (const f of man.metrics.isd?.facilities ?? []) {
    legs[f.facility] = Object.fromEntries(f.legs.map((l) => [l.leg, l]));
  }
  return { lines, facilities, p95, legs };
}

export interface Centreline {
  id: string; // "facility/label", the same id as profile.csv's line column
  label: string; // direction label, e.g. "N-S"
  points: Point[];
}

/** One facility's road centrelines in one drive, from centrelines.geojson. Empty when the bundle has none. */
export async function loadCentrelines(run: string, facility: string): Promise<Centreline[]> {
  const geo = await getJson<GeoJson>(`showcase/${run}/centrelines.geojson`);
  return geo.features
    .filter((f) => f.properties.facility === facility)
    .map((f) => ({
      id: String(f.properties.line),
      label: String(f.properties.label),
      points: (f.geometry.coordinates as unknown[]).map(pt),
    }));
}

export function loadRasterMeta(run: string, raster: Raster): Promise<RasterMeta> {
  return getJson<RasterMeta>(`showcase/tiles/${run}/${raster}/meta.json`);
}
