// Map frame and tile maths. A frame is local metres: x east from ox, y south from top (screen-down),
// so a tile's top-left corner in the frame is also its CSS position. Tile layout is in meta.json (origin top-left).

export interface Frame {
  ox: number; // easting of the frame's left edge (EPSG:32619)
  top: number; // northing of the frame's top edge
  w: number;
  h: number;
}

export interface Rect {
  x0: number;
  y0: number;
  x1: number;
  y1: number;
}

/** Screen px per metre (k) and the screen offset of the frame origin (tx, ty). */
export interface View {
  k: number;
  tx: number;
  ty: number;
}

export interface Size {
  w: number;
  h: number;
}

export function frameOf(boxes: number[][]): Frame | null {
  if (!boxes.length) return null;
  const ox = Math.min(...boxes.map((b) => b[0]));
  const top = Math.max(...boxes.map((b) => b[3]));
  const x1 = Math.max(...boxes.map((b) => b[2]));
  const y0 = Math.min(...boxes.map((b) => b[1]));
  return { ox, top, w: x1 - ox, h: top - y0 };
}

export function localRect(bbox: number[], f: Frame): Rect {
  return { x0: bbox[0] - f.ox, y0: f.top - bbox[3], x1: bbox[2] - f.ox, y1: f.top - bbox[1] };
}

/** Fit a rect into the viewport with some padding, centred. */
export function fitView(r: Rect, size: Size, pad: number, maxK = Infinity): View {
  const rw = (r.x1 - r.x0) * pad;
  const rh = (r.y1 - r.y0) * pad;
  if (!size.w || !size.h || !rw || !rh || !Number.isFinite(rw) || !Number.isFinite(rh)) {
    return { k: 1, tx: size.w ? size.w / 2 : 0, ty: size.h ? size.h / 2 : 0 };
  }
  const k = Math.min(maxK, size.w / rw, size.h / rh);
  const cx = (r.x0 + r.x1) / 2;
  const cy = (r.y0 + r.y1) / 2;
  if (!Number.isFinite(cx) || !Number.isFinite(cy)) {
    return { k: 1, tx: size.w ? size.w / 2 : 0, ty: size.h ? size.h / 2 : 0 };
  }
  const kk = Number.isFinite(k) && k > 0 ? k : 1;
  return { k: kk, tx: size.w / 2 - kk * cx, ty: size.h / 2 - kk * cy };
}


export const TILE = 256;

export interface Tile {
  url: string;
  left: number;
  top: number;
  w: number;
  h: number;
}

/** Smallest level whose pixels are at least one per device pixel, capped at zmax. */
export function tileLevel(k: number, dpr: number, widthM: number, zmax: number): number {
  const want = (k * dpr * widthM) / TILE;
  if (!Number.isFinite(want) || want <= 0) return 0;
  return Math.min(zmax, Math.max(0, Math.ceil(Math.log2(want))));
}

/** Tiles at level z intersecting the viewport. Compat for per-run/mosaic callers; uses mosaic URL shape. */
export function visibleTiles(
  raster: string,
  run: string,
  r: Rect,
  z: number,
  v: View,
  size: Size,
): Tile[] {
  const n = 2 ** z;
  const tw = (r.x1 - r.x0) / n;
  const th = (r.y1 - r.y0) / n;
  if (!Number.isFinite(tw) || !Number.isFinite(th) || tw <= 0 || th <= 0) return [];
  const vx0 = -v.tx / v.k;
  const vx1 = (size.w - v.tx) / v.k;
  const vy0 = -v.ty / v.k;
  const vy1 = (size.h - v.ty) / v.k;
  const ix0 = Math.max(0, Math.floor((vx0 - r.x0) / tw));
  const ix1 = Math.min(n - 1, Math.floor((vx1 - r.x0) / tw));
  const iy0 = Math.max(0, Math.floor((vy0 - r.y0) / th));
  const iy1 = Math.min(n - 1, Math.floor((vy1 - r.y0) / th));
  const out: Tile[] = [];
  for (let x = ix0; x <= ix1; x++) {
    for (let y = iy0; y <= iy1; y++) {
      out.push({
        url: `showcase/tiles/${raster}/${z}/${x}/${y}.webp`,
        left: r.x0 + x * tw,
        top: r.y0 + y * th,
        w: tw,
        h: th,
      });
    }
  }
  return out;
}

export const MAX_K = 40;
export const MAX_VIEW_ZOOM = Math.log2(MAX_K);

export interface ViewState {
  target: [number, number, number];
  zoom: number;
  k?: number;
}

export type BBox = [[number, number], [number, number]];

export type TileIndex = { x: number; y: number; z: number };

export function viewStateOf(v: View, size: Size): ViewState {
  const k = Number.isFinite(v.k) && v.k > 0 ? v.k : 1;
  const target: [number, number, number] = [(size.w / 2 - v.tx) / k, (size.h / 2 - v.ty) / k, 0];
  const zoom = Math.log2(k);
  return { target, zoom, k };
}

export function viewOf(s: ViewState, size: Size): View {
  const k = 2 ** s.zoom;
  return { k, tx: size.w / 2 - k * s.target[0], ty: size.h / 2 - k * s.target[1] };
}

export function fitState(r: Rect, size: Size, pad: number, maxK?: number): ViewState {
  const view = fitView(r, size, pad, maxK ?? Infinity);
  return viewStateOf(view, size);
}

export function minZoomOf(area: Rect, size: Size): number {
  const k = fitView(area, size, 1.02).k;
  if (!Number.isFinite(k) || k <= 0) return 0;
  return Math.log2(k * 0.8);
}

export function bitmapBounds(b: BBox): [number, number, number, number] {
  return [b[0][0], b[1][1], b[1][0], b[0][1]];
}

export function normaliseTileBBox(b: unknown): BBox | null {
  if (Array.isArray(b)) {
    if (b.length === 4 && b.every((v) => typeof v === "number")) {
      return [[b[0], b[1]], [b[2], b[3]]];
    }
    if (
      b.length === 2 &&
      Array.isArray(b[0]) &&
      Array.isArray(b[1]) &&
      b[0].length === 2 &&
      b[1].length === 2 &&
      [...b[0], ...b[1]].every((v) => typeof v === "number")
    ) {
      return [[b[0][0], b[0][1]], [b[1][0], b[1][1]]];
    }
    return null;
  }
  if (b !== null && typeof b === "object") {
    const o = b as { west?: unknown; south?: unknown; east?: unknown; north?: unknown; left?: unknown; top?: unknown; right?: unknown; bottom?: unknown };
    if (
      typeof o.west === "number" &&
      typeof o.south === "number" &&
      typeof o.east === "number" &&
      typeof o.north === "number"
    ) {
      return [[o.west, o.south], [o.east, o.north]];
    }
    if (
      typeof o.left === "number" &&
      typeof o.top === "number" &&
      typeof o.right === "number" &&
      typeof o.bottom === "number"
    ) {
      // deck.gl non-geo TileLayer getTileMetadata returns {left,top,right,bottom}
      return [[o.left, o.top], [o.right, o.bottom]];
    }
  }
  return null;
}

export function tileBounds(index: TileIndex, extent: number): BBox {
  const n = 2 ** index.z;
  const s = extent / n;
  return [[index.x * s, index.y * s], [(index.x + 1) * s, (index.y + 1) * s]];
}

export interface TileRangeResult {
  z: number;
  x0: number;
  x1: number;
  y0: number;
  y1: number;
  indices: TileIndex[];
}

// Cart/ceil tile zoom; same formula as the tileset indexer.
export function tileZoomFor(viewZoom: number, extent: number, tilePx: number, dpr: number): number {
  return Math.ceil(viewZoom + Math.log2((extent * dpr) / tilePx));
}

export function tileRange(
  k: number,
  extent: number,
  tilePx: number,
  dpr: number,
  bounds: [number, number, number, number],
  zmin = 0,
  zmax = Infinity,
): TileRangeResult {
  const rawZ = tileZoomFor(Math.log2(k > 0 ? k : 1), extent, tilePx, dpr);
  const z = Math.max(zmin, Math.min(zmax, rawZ));
  const n = 2 ** z;
  const span = extent / n;
  const [minX, minY, maxX, maxY] = bounds;
  const x0 = Math.floor(minX / span);
  const x1 = Math.floor(maxX / span);
  const y0 = Math.floor(minY / span);
  const y1 = Math.floor(maxY / span);
  const indices: TileIndex[] = [];
  for (let x = x0; x <= x1; x++) {
    for (let y = y0; y <= y1; y++) {
      if (x < 0 || y < 0 || x >= n || y >= n) continue;
      indices.push({ x, y, z });
    }
  }
  return { z, x0, x1, y0, y1, indices };
}
