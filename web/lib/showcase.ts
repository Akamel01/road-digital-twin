// Types mirror twin/contracts.py (AreaIndex). Keep in sync with that file.

export type FacilityType = "intersection" | "segment" | "access_point";

export interface Drive {
  run_id: string;
  scene_token: string;
  name: string;
  bbox: number[] | null; // minx, miny, maxx, maxy in EPSG:32619 metres
}

export interface AreaFacility {
  id: string;
  type: FacilityType;
  name: string;
  best_run: string | null;
  runs: string[];
  observed_core: number;
  not_scanned_enough: boolean;
}

export interface AreaIndex {
  drives: Drive[];
  facilities: AreaFacility[];
}

const TYPE_LABEL: Record<FacilityType, string> = {
  intersection: "Intersection",
  segment: "Segment",
  access_point: "Access point",
};

export function typeLabel(t: FacilityType): string {
  return TYPE_LABEL[t];
}

export const SHOWCASE_MISSING =
  "Showcase bundle not found. Run web/scripts/fake-showcase.sh to copy it into web/public/showcase/.";

/** Loads area.json from the static bundle. Relative URL, so it works under any path the export is served from. */
export async function loadArea(): Promise<AreaIndex> {
  const res = await fetch("showcase/area.json", { cache: "no-cache" });
  if (!res.ok) throw new Error(SHOWCASE_MISSING);
  return (await res.json()) as AreaIndex;
}

/** Written by `twin site publish` (twin/site.py). Absent in a local fake showcase. */
export interface SiteStatus {
  run_id: string;
  published_at: string; // ISO time
  verdict: string; // go / no-go
  gates_version: number;
}

export async function loadStatus(): Promise<SiteStatus | null> {
  try {
    const res = await fetch("showcase/status.json", { cache: "no-cache" });
    return res.ok ? ((await res.json()) as SiteStatus) : null;
  } catch {
    return null;
  }
}
