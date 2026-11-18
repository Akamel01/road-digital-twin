import { frameOf, type Frame } from "./tiles";
import { getJson } from "./mapdata";
import type { Raster } from "./mapdata";

export type MosaicRaster = Raster;
export const MOSAIC_RASTERS: readonly Raster[] = ["lidar", "ortho", "height", "coverage"];

export interface MosaicMeta {
  crs: string;
  bbox: [number, number, number, number];
  tile_px: number;
  zmin: number;
  zmax: number;
  cell_m_at_zmax: number;
  tiles?: [number, number, number][];
}

export async function loadMosaics(): Promise<Record<Raster, MosaicMeta>> {
  const entries = await Promise.all(
    MOSAIC_RASTERS.map(async (r) => [r, await getJson<MosaicMeta>(`showcase/tiles/${r}/meta.json`)] as const),
  );
  return Object.fromEntries(entries) as Record<Raster, MosaicMeta>;
}

export async function loadTileVersion(): Promise<string> {
  try {
    const data = await getJson<{ tile_version?: unknown }>("showcase/publish_report.json");
    return typeof data?.tile_version === "string" && data.tile_version !== "" ? data.tile_version : "";
  } catch {
    return "";
  }
}

export function tileUrl(layer: Raster, version: string): string {
  const base = `showcase/tiles/${layer}/{z}/{x}/{y}.webp`;
  return version === "" ? base : `${base}?v=${encodeURIComponent(version)}`;
}

let warnedMissingTiles = false;
export function tileKeys(meta: MosaicMeta): Set<string> | null {
  if (!meta.tiles) {
    if (!warnedMissingTiles) {
      console.warn("mosaic: meta.tiles absent; tile key set unavailable");
      warnedMissingTiles = true;
    }
    return null;
  }
  const set = new Set<string>();
  for (const [z, x, y] of meta.tiles) set.add(`${z}/${x}/${y}`);
  return set;
}

export function mosaicFrame(metas: Record<Raster, MosaicMeta>): Frame | null {
  const layers = MOSAIC_RASTERS.filter((r) => metas[r]);
  if (layers.length === 0) return null;
  const first = metas[layers[0]].bbox;
  for (const r of layers) {
    const b = metas[r].bbox;
    for (let i = 0; i < 4; i++) {
      if (Math.abs(b[i] - first[i]) > 1e-3) {
        throw new Error(`mosaicFrame: bbox mismatch for ${r}: ${b} vs ${first}`);
      }
    }
  }
  if (Math.abs((first[2] - first[0]) - (first[3] - first[1])) > 0.01) {
    throw new Error(`mosaicFrame: non-square bbox: ${first}`);
  }
  return frameOf([first]);
}

// Installed @deck.gl/geo-layers computes the tile level in getTileIndices:
//   geospatial -> Math.round(viewport.zoom + Math.log2(512 / tileSize) + zoomOffset)
//   cartesian  -> Math.ceil(viewport.zoom + zoomOffset)
// Tileset2D.getTileZoom itself returns index.z. We use the round form with
// tileSize = 512 * tilePx / (extent * dpr), so 512 / tileSize = extent * dpr / tilePx.
export function tileZoomFor(viewZoom: number, extent: number, tilePx: number, dpr: number): number {
  return Math.ceil(viewZoom + Math.log2((extent * dpr) / tilePx));
}
