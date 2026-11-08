// Map frame and tile maths. A frame is local metres: x east from ox, y south from top (screen-down),
// so a tile's top-left corner in the frame is also its CSS position. Tile layout is in meta.json (origin top-left).

export const TILE = 256;

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

export interface Tile {
  url: string;
  left: number;
  top: number;
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

/** Smallest level whose pixels are at least one per device pixel, capped at zmax. */
export function tileLevel(k: number, dpr: number, widthM: number, zmax: number): number {
  const want = (k * dpr * widthM) / TILE;
  return Math.min(zmax, Math.max(0, Math.ceil(Math.log2(want))));
}

/** Fit a rect into the viewport with some padding, centred. */
export function fitView(r: Rect, size: Size, pad: number, maxK = Infinity): View {
  const k = Math.min(maxK, size.w / ((r.x1 - r.x0) * pad), size.h / ((r.y1 - r.y0) * pad));
  const cx = (r.x0 + r.x1) / 2;
  const cy = (r.y0 + r.y1) / 2;
  return { k, tx: size.w / 2 - k * cx, ty: size.h / 2 - k * cy };
}

/** Tiles at level z that intersect the viewport. Only these get requested. */
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
  const vx0 = -v.tx / v.k;
  const vx1 = (size.w - v.tx) / v.k;
  const vy0 = -v.ty / v.k;
  const vy1 = (size.h - v.ty) / v.k;
  if (vx1 < r.x0 || vx0 > r.x1 || vy1 < r.y0 || vy0 > r.y1) return [];
  const clamp = (i: number) => Math.min(n - 1, Math.max(0, i));
  const ix0 = clamp(Math.floor((vx0 - r.x0) / tw));
  const ix1 = clamp(Math.floor((vx1 - r.x0) / tw));
  const iy0 = clamp(Math.floor((vy0 - r.y0) / th));
  const iy1 = clamp(Math.floor((vy1 - r.y0) / th));
  const out: Tile[] = [];
  for (let x = ix0; x <= ix1; x++) {
    for (let y = iy0; y <= iy1; y++) {
      out.push({
        url: `showcase/tiles/${run}/${raster}/${z}/${x}/${y}.webp`,
        left: r.x0 + x * tw,
        top: r.y0 + y * th,
        w: tw,
        h: th,
      });
    }
  }
  return out;
}
