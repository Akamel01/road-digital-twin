/* eslint-disable @typescript-eslint/no-explicit-any */
import { TileLayer } from "@deck.gl/geo-layers";
import { _Tileset2D as Tileset2D } from "@deck.gl/geo-layers";
import { BitmapLayer } from "@deck.gl/layers";
import { COORDINATE_SYSTEM } from "@deck.gl/core";
import type { Raster } from "./mapdata";
import type { MosaicMeta } from "./mosaic";
import { tileUrl, tileKeys } from "./mosaic";
import { bitmapBounds, normaliseTileBBox, tileBounds, tileRange } from "./tiles";

export interface TileLayersInput {
  metas: Record<Raster, MosaicMeta>;
  rasters: Raster[];
  version: string;
  dpr: number;
}

const tileKeyCache = new WeakMap<MosaicMeta, Set<string> | null>();
const tilesetCache = new WeakMap<MosaicMeta, Map<number, ReturnType<typeof makeMosaicTileset>>>();

function profOn(): boolean {
  return typeof window !== "undefined" && (window as any).__PROFILE_288 === true;
}
function pmark(name: string) { if (profOn()) performance.mark(name); }
function pmeasure(name: string, s: string, e: string) {
  if (!profOn()) return;
  try { performance.measure(name, s, e); } catch {}
}

function memoTileKeys(meta: MosaicMeta): Set<string> | null {
  if (tileKeyCache.has(meta)) return tileKeyCache.get(meta)!;
  const keys = tileKeys(meta);
  tileKeyCache.set(meta, keys);
  return keys;
}

type Pending = { resolve: (v: ImageBitmap | null) => void };
type WState = { w: Worker; busy: number; pending: Map<number, Pending> };

const WORKER_SRC = `self.onmessage=async(e)=>{const{id,url}=e.data;try{const r=await fetch(url);if(!r.ok){postMessage({id,ok:false});return}const b=await r.blob();const bmp=await createImageBitmap(b);postMessage({id,ok:true,bmp},[bmp])}catch{postMessage({id,ok:false})}}`;
let pool: WState[] | null = null;
let workerUrl: string | null = null;
let reqId = 1;

function canUseWorkers(): boolean {
  return typeof window !== "undefined" && typeof Worker !== "undefined" && typeof Blob !== "undefined";
}

function getPool(): WState[] | null {
  if (!canUseWorkers()) return null;
  if (pool) return pool;
  try {
    workerUrl = URL.createObjectURL(new Blob([WORKER_SRC], { type: "application/javascript" }));
    pool = [0, 1].map(() => {
      const w = new Worker(workerUrl!);
      const st: WState = { w, busy: 0, pending: new Map() };
      w.onmessage = (e: MessageEvent) => {
        const { id, ok, bmp } = e.data || {};
        const p = st.pending.get(id);
        if (p) {
          st.pending.delete(id);
          st.busy = Math.max(0, st.busy - 1);
          p.resolve(ok && bmp ? (bmp as ImageBitmap) : null);
        } else if (ok && bmp) {
          try { (bmp as ImageBitmap).close?.(); } catch {}
        }
      };
      w.onerror = () => {
        for (const [, p] of st.pending) p.resolve(null);
        st.pending.clear();
        st.busy = 0;
      };
      return st;
    });
    return pool;
  } catch {
    pool = null;
    return null;
  }
}

function fetchBitmapViaWorker(url: string, signal?: AbortSignal): Promise<ImageBitmap | null> | null {
  if (signal?.aborted) return Promise.resolve(null);
  const p = getPool();
  if (!p) return null;
  const st = p[0].busy <= p[1].busy ? p[0] : p[1];
  const id = reqId++;
  return new Promise((resolve) => {
    const done = (v: ImageBitmap | null) => {
      if (signal && onAbort) signal.removeEventListener("abort", onAbort);
      resolve(v);
    };
    const onAbort = signal
      ? () => {
          if (st.pending.has(id)) {
            st.pending.delete(id);
            st.busy = Math.max(0, st.busy - 1);
          }
          done(null);
        }
      : undefined;
    st.pending.set(id, { resolve: done });
    st.busy++;
    if (signal && onAbort) signal.addEventListener("abort", onAbort, { once: true });
    try {
      st.w.postMessage({ id, url });
    } catch {
      st.pending.delete(id);
      st.busy = Math.max(0, st.busy - 1);
      if (signal && onAbort) signal.removeEventListener("abort", onAbort);
      resolve(null);
    }
  });
}

async function fetchBitmapMainThread(url: string, signal?: AbortSignal): Promise<ImageBitmap | null> {
  try {
    const res = await fetch(url, { signal });
    if (!res.ok) return null;
    const blob = await res.blob();
    if (signal?.aborted) return null;
    return await createImageBitmap(blob);
  } catch {
    return null;
  }
}

function makeMosaicTileset(meta: MosaicMeta, dpr: number) {
  const extent = meta.bbox[2] - meta.bbox[0];
  return class MosaicTileset extends Tileset2D {
    getTileIndices({ viewport }: any) {
      let bounds: any;
      try {
        bounds = viewport.getBounds();
      } catch {
        return [];
      }
      if (!Array.isArray(bounds) || bounds.some((v: any) => !Number.isFinite(v))) {
        return [];
      }
      const k = 2 ** viewport.zoom;
      const { indices } = tileRange(k, extent, meta.tile_px, dpr, bounds as [number, number, number, number], meta.zmin, meta.zmax);
      return indices;
    }
    getTileMetadata(index: any) {
      const b = tileBounds(index, extent);
      return { bbox: { left: b[0][0], top: b[0][1], right: b[1][0], bottom: b[1][1] } };
    }
    getTileZoom(index: any) {
      return index.z;
    }
  };
}

export function createMosaicTileset(meta: MosaicMeta, dpr: number) {
  let byDpr = tilesetCache.get(meta);
  if (!byDpr) {
    byDpr = new Map();
    tilesetCache.set(meta, byDpr);
  }
  const cached = byDpr.get(dpr);
  if (cached) return cached;
  const cls = makeMosaicTileset(meta, dpr);
  byDpr.set(dpr, cls);
  return cls;
}

export function tileLayers({ metas, rasters, version, dpr }: TileLayersInput) {
  const out: any[] = [];
  for (const layer of rasters) {
    const meta = metas[layer];
    if (!meta) continue;
    const extent = meta.bbox[2] - meta.bbox[0];
    out.push(
      new TileLayer({
        id: `tile-${layer}`,
        data: tileUrl(layer, version),
        TilesetClass: createMosaicTileset(meta, dpr),
        extent: [0, 0, extent, extent],
        tileSize: extent,
        coordinateSystem: COORDINATE_SYSTEM.CARTESIAN,
        refinementStrategy: "never",
        maxRequests: 8,
        debounceTime: 0,
        maxCacheSize: 64,
        onTileUnload: (tile: any) => {
          const bmp = tile?.data ?? tile?.content;
          try { bmp?.close?.(); } catch {}
        },
        getTileData: async (props: any) => {
          const keys = memoTileKeys(meta);
          const idx = props.index || {};
          let z = Number(idx.z);
          if (!Number.isFinite(z)) z = 0;
          z = Math.max(meta.zmin, Math.min(meta.zmax, z));
          const { x, y } = idx;
          if (keys && !keys.has(`${z}/${x}/${y}`)) return null;
          const base = typeof props.url === "string" ? props.url : tileUrl(layer, version);
          const url = base.replace("{z}", String(z)).replace("{x}", String(x)).replace("{y}", String(y));
          const tag = `${layer}-${z}-${x}-${y}-${Math.random().toString(36).slice(2, 7)}`;
          try {
            if (props.signal?.aborted) return null;
            const viaWorker = fetchBitmapViaWorker(url, props.signal);
            if (viaWorker) {
              pmark(`tile:${tag}:worker:start`);
              const bmp = await viaWorker;
              pmark(`tile:${tag}:worker:end`);
              pmeasure(`tile:${layer}:worker`, `tile:${tag}:worker:start`, `tile:${tag}:worker:end`);
              return bmp;
            }
            pmark(`tile:${tag}:fetch:start`);
            const bmp = await fetchBitmapMainThread(url, props.signal);
            pmark(`tile:${tag}:fetch:end`);
            pmeasure(`tile:${layer}:fetch`, `tile:${tag}:fetch:start`, `tile:${tag}:fetch:end`);
            return bmp;
          } catch {
            return null;
          }
        },
        renderSubLayers: (props: any) => {
          const p = props;
          if (!p || !p.tile || p.data == null) return null;
          if (profOn()) { pmark(`tile:renderSubLayers:start`); }
          const bbox = normaliseTileBBox(p.tile.bbox) ?? tileBounds(p.tile.index, extent);
          const bounds = bitmapBounds(bbox);
          const layer = new BitmapLayer({
            id: `${props.id}-bitmap`,
            image: p.data,
            bounds,
            coordinateSystem: COORDINATE_SYSTEM.CARTESIAN,
            pickable: false,
          });
          if (profOn()) {
            pmark(`tile:renderSubLayers:end`);
            pmeasure(`tile:renderSubLayers`, `tile:renderSubLayers:start`, `tile:renderSubLayers:end`);
          }
          return layer;
        },
      }),
    );
  }
  return out;
}
