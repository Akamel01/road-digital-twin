// Client + types for the developer label API (/api/r/labels/*, /api/w/labels/*).
// Types mirror twin/contracts.py SiteMeta and LabelFeature; keep in sync.

import { getJson, postJson, putJson } from "@/lib/devapi";

export interface SiteMeta {
  id: string;
  role: "dev" | "audit";
  polygon: Record<string, unknown>;
  version: number;
  approved_by: string | null;
  approved_at: string | null;
  crs: "EPSG:32619";
  created_at: string;
  source_area: string;
  frozen: boolean;
  control?: "signalised" | "stop_controlled" | "uncontrolled" | "mid_block" | null;
  notes?: string | null;
}

export interface LabelFeature {
  id: string;
  element: "marking" | "crosswalk" | "curb" | "curb_ramp";
  type:
    | "solid_line"
    | "dashed_line"
    | "edge_line"
    | "stop_line"
    | "arrow"
    | "text"
    | "zebra"
    | "parallel"
    | "curb"
    | "curb_ramp"
    | "double_line"
    | "ladder"
    | "continental"
    | "transverse";
  origin: "drafted" | "operator";
  height_m?: number | null;
  kind?: string | null;
  width_m?: number | null;
  run_length_m?: number | null;
  running_slope_pct?: number | null;
  cross_slope_pct?: number | null;
  flare_slope_pct?: number | null;
  gutter_step_m?: number | null;
  running_slope_status?: string | null;
  cross_slope_status?: string | null;
  flare_slope_status?: string | null;
  gutter_step_status?: string | null;
  status?: string | null;
  nearest_crosswalk_m?: number | null;
  crosswalk_id?: string | null;
  n_points?: number | null;
  source_feature_id?: string | null;
  source_file?: string | null;
  source_marking_type?: string | null;
  evidence?: string | null;
}

export interface GeoJsonGeometry {
  type: string;
  coordinates: unknown;
}

export interface GeoJsonFeature<P = LabelFeature> {
  type: "Feature";
  geometry: GeoJsonGeometry | null;
  properties: P;
}

export interface GeoJsonFeatureCollection<P = LabelFeature> {
  type: "FeatureCollection";
  features: GeoJsonFeature<P>[];
}

function enc(site: string): string {
  return encodeURIComponent(site);
}

export const loadSites = (): Promise<string[]> =>
  getJson<string[]>("/api/r/labels/sites");

export const loadSite = (site: string): Promise<SiteMeta> =>
  getJson<SiteMeta>(`/api/r/labels/${enc(site)}`);

export const loadLabels = (
  site: string,
): Promise<GeoJsonFeatureCollection<LabelFeature>> =>
  getJson<GeoJsonFeatureCollection<LabelFeature>>(`/api/r/labels/${enc(site)}/labels`);

export const saveLabels = (
  site: string,
  version: number,
  labels: GeoJsonFeatureCollection<LabelFeature>,
): Promise<SiteMeta> =>
  putJson<SiteMeta>(`/api/w/labels/${enc(site)}/labels`, {
    version,
    feature_collection: labels,
  });

export const approve = (
  site: string,
  approvedBy: string,
): Promise<SiteMeta> =>
  postJson<SiteMeta>(`/api/w/labels/${enc(site)}/approve`, {
    approved_by: approvedBy,
  });

export const newVersion = (site: string): Promise<SiteMeta> =>
  postJson<SiteMeta>(`/api/w/labels/${enc(site)}/new-version`);
