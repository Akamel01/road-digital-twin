/* eslint-disable @typescript-eslint/no-explicit-any */
import { TileLayer } from "@deck.gl/geo-layers";
import { BitmapLayer } from "@deck.gl/layers";
import { COORDINATE_SYSTEM } from "@deck.gl/core";
import type { Raster } from "./mapdata";
import type { MosaicMeta } from "./mosaic";
import { tileUrl, tileKeys } from "./mosaic";
import { bitmapBounds, normaliseTileBBox, tileBounds } from "./tiles";

export interface TileLayersInput {
  metas: Record<Raster, MosaicMeta>;
  rasters: Raster[];
  version: string;
  dpr: number;
}

export function tileLayers({ metas, rasters, version, dpr }: TileLayersInput) {
  const out: any[] = [];
  for (const layer of rasters) {
    const meta = metas[layer];
    if (!meta) continue;
    const extent = meta.bbox[2] - meta.bbox[0];
    const tileSize = (512 * meta.tile_px) / (extent * dpr);
    out.push(
      new TileLayer({
        id: `tile-${layer}`,
        data: tileUrl(layer, version),
        extent: [0, 0, extent, extent],
        tileSize,
        minZoom: meta.zmin,
        maxZoom: meta.zmax,
        coordinateSystem: COORDINATE_SYSTEM.CARTESIAN,
        getTileData: async (props: any) => {
          const keys = tileKeys(meta);
          if (!keys) return null;
          const { z, x, y } = props.index;
          if (!keys.has(`${z}/${x}/${y}`)) return null;
          const url = typeof props.url === "string" ? props.url : tileUrl(layer, version).replace("{z}", String(z)).replace("{x}", String(x)).replace("{y}", String(y));
          try {
            const res = await fetch(url);
            if (!res.ok) return null;
            const blob = await res.blob();
            return await createImageBitmap(blob);
          } catch {
            return null;
          }
        },
        renderSubLayers: (props: any) => {
          const p = props;
          const bbox = normaliseTileBBox(p.tile.bbox) ?? tileBounds(p.tile.index, extent);
          const bounds = bitmapBounds(bbox);
          return new BitmapLayer({
            id: `${props.id}-bitmap`,
            image: p.data,
            bounds,
            coordinateSystem: COORDINATE_SYSTEM.CARTESIAN,
            pickable: false,
          });
        },
      }),
    );
  }
  return out;
}
