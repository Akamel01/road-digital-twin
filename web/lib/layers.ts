import type { Raster } from "./mapdata";

export type Layer = "height" | "lidar" | "ortho" | "markings" | "crosswalks" | "curbs";
export type Analysis = "accuracy" | "safety" | "coverage";
export type Layers = Record<Layer, boolean>;

export const DEFAULT_LAYERS: Layers = {
  height: false,
  lidar: true,
  ortho: false,
  markings: true,
  crosswalks: true,
  curbs: true,
};

export const TRIO: readonly Layer[] = ["height", "ortho", "lidar"];

export function applyTrioToggle(prev: Layers, k: Layer): Layers {
  if (!TRIO.includes(k)) return { ...prev, [k]: !prev[k] };
  const nextOn = !prev[k];
  if (!nextOn) return { ...prev, [k]: false };
  return {
    ...prev,
    height: k === "height",
    ortho: k === "ortho",
    lidar: k === "lidar",
  };
}

export function applySafetyLayers(prev: Layers): Layers {
  return { ...prev, ortho: true, lidar: false, height: false };
}

export function rastersFor(layers: Layers, analysis: Analysis | null): Raster[] {
  const out: Raster[] = [];
  for (const r of ["height", "ortho", "lidar"] as Layer[]) {
    if (layers[r]) { out.push(r as Raster); break; }
  }
  if (analysis === "coverage") out.push("coverage");
  return out;
}
