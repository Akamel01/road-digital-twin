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
  software?: boolean;
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

type UploadItem = {
  bmp: ImageBitmap;
  resolve: (v: ImageBitmap | null) => void;
  signal?: AbortSignal;
  settled: boolean;
};
const uploadQueue: UploadItem[] = [];
let uploadRaf: number | null = null;

function drainUploadQueue() {
  uploadRaf = null;
  let released = 0;
  while (released < 2 && uploadQueue.length) {
    const it = uploadQueue.shift()!;
    if (it.settled) continue;
    it.settled = true;
    if (it.signal?.aborted) {
      try { it.bmp.close?.(); } catch {}
      it.resolve(null);
    } else {
      it.resolve(it.bmp);
    }
    released++;
  }
  for (let i = uploadQueue.length - 1; i >= 0; i--) {
    const it = uploadQueue[i];
    if (!it.signal?.aborted) continue;
    uploadQueue.splice(i, 1);
    if (!it.settled) {
      it.settled = true;
      try { it.bmp.close?.(); } catch {}
      it.resolve(null);
    }
  }
  if (uploadQueue.length) {
    if (typeof requestAnimationFrame === "function") {
      uploadRaf = requestAnimationFrame(drainUploadQueue);
    } else {
      setTimeout(drainUploadQueue, 16);
    }
  }
}

function staggerBitmapUpload(bmp: ImageBitmap, signal?: AbortSignal): Promise<ImageBitmap | null> {
  if (signal?.aborted) {
    try { bmp.close?.(); } catch {}
    return Promise.resolve(null);
  }
  return new Promise((resolve) => {
    const item: UploadItem = { bmp, resolve, signal, settled: false };
    uploadQueue.push(item);
    if (signal) {
      signal.addEventListener(
        "abort",
        () => {
          if (item.settled) return;
          item.settled = true;
          const idx = uploadQueue.indexOf(item);
          if (idx >= 0) uploadQueue.splice(idx, 1);
          try { item.bmp.close?.(); } catch {}
          resolve(null);
        },
        { once: true },
      );
    }
    if (uploadRaf == null) {
      if (typeof requestAnimationFrame === "function") {
        uploadRaf = requestAnimationFrame(drainUploadQueue);
      } else {
        setTimeout(drainUploadQueue, 16);
      }
    }
  });
}

const WORKER_SRC = `self.onmessage=async(e)=>{const{id,buf,rw,rh}=e.data;try{const src=new Blob([buf]);const opts=(rw&&rh)?{resizeWidth:rw,resizeHeight:rh,resizeQuality:'low'}:undefined;const bmp=opts?await createImageBitmap(src,opts):await createImageBitmap(src);postMessage({id,ok:true,bmp},[bmp])}catch(err){postMessage({id,ok:false,err:String(err&&err.message||err)})}}`;
function noteTileErr(msg: unknown){try{if(typeof window!=="undefined"){const w=window as any;w.__tileWorkerErrors=(w.__tileWorkerErrors||[]);w.__tileWorkerErrors.push(String(msg));}}catch{}}
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
      w.onerror = (ev) => {
        noteTileErr("worker error: " + (ev && (ev as any).message || "unknown"));
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

function decodeBitmapViaWorker(buf: ArrayBuffer, signal?: AbortSignal, resize?: { rw: number; rh: number }): Promise<ImageBitmap | null> | null {
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
    st.pending.set(id, {
      resolve: (v) => {
        if (!v) noteTileErr("worker decode returned null");
        done(v);
      },
    });
    st.busy++;
    if (signal && onAbort) signal.addEventListener("abort", onAbort, { once: true });
    try {
      st.w.postMessage({ id, buf, rw: resize?.rw, rh: resize?.rh }, [buf]);
    } catch (err) {
      st.pending.delete(id);
      st.busy = Math.max(0, st.busy - 1);
      if (signal && onAbort) signal.removeEventListener("abort", onAbort);
      noteTileErr("worker postMessage failed: " + String((err as any)?.message || err));
      resolve(null);
    }
  });
}

async function decodeBitmapMainThread(buf: ArrayBuffer, signal?: AbortSignal, resize?: { rw: number; rh: number }): Promise<ImageBitmap | null> {
  try {
    if (signal?.aborted) return null;
    const src = new Blob([buf]);
    if (resize) {
      return await createImageBitmap(src, { resizeWidth: resize.rw, resizeHeight: resize.rh, resizeQuality: "low" });
    }
    return await createImageBitmap(src);
  } catch (err) {
    noteTileErr("main-thread decode failed: " + String((err as any)?.message || err));
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
      const b = bounds as [number, number, number, number];
      const w = b[2] - b[0];
      const h = b[3] - b[1];
      const mx = (Number.isFinite(w) && w > 0 ? w : 0) * 0.5;
      const my = (Number.isFinite(h) && h > 0 ? h : 0) * 0.5;
      const expanded: [number, number, number, number] = [
        Math.max(0, b[0] - mx),
        Math.max(0, b[1] - my),
        Math.min(extent, b[2] + mx),
        Math.min(extent, b[3] + my),
      ];
      const k = 2 ** viewport.zoom;
      const { indices } = tileRange(k, extent, meta.tile_px, dpr, expanded, meta.zmin, meta.zmax);
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

export function tileLayers({ metas, rasters, version, dpr, software }: TileLayersInput) {
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
            pmark(`tile:${tag}:fetch:start`);
            const res = await fetch(url, { signal: props.signal });
            pmark(`tile:${tag}:fetch:end`);
            pmeasure(`tile:${layer}:fetch`, `tile:${tag}:fetch:start`, `tile:${tag}:fetch:end`);
            if (!res.ok) {
              noteTileErr(`tile fetch ${res.status} ${url}`);
              return null;
            }
            const buf = await res.arrayBuffer();
            if (props.signal?.aborted) return null;
            const resize = software ? { rw: 128, rh: 128 } : undefined;
            let bmp: ImageBitmap | null = null;
            const viaWorker = decodeBitmapViaWorker(buf, props.signal, resize);
            if (viaWorker) {
              pmark(`tile:${tag}:worker:start`);
              bmp = await viaWorker;
              pmark(`tile:${tag}:worker:end`);
              pmeasure(`tile:${layer}:worker`, `tile:${tag}:worker:start`, `tile:${tag}:worker:end`);
            } else {
              bmp = await decodeBitmapMainThread(buf, props.signal, resize);
            }
            if (!bmp) return null;
            return await staggerBitmapUpload(bmp, props.signal);
          } catch (err) {
            if (!(props.signal?.aborted)) noteTileErr(`tile load failed ${url}: ${String((err as any)?.message || err)}`);
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
            textureParameters: { minFilter: "linear", magFilter: "linear" },
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
