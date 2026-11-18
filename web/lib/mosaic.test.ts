import { describe, it, expect } from "vitest";
import { tileUrl, tileKeys, mosaicFrame, tileZoomFor } from "./mosaic";
import type { MosaicMeta } from "./mosaic";

describe("mosaic", () => {
  it("tileUrl appends ?v only when non-empty", () => {
    expect(tileUrl("lidar", "a1b2")).toMatch(/\?v=a1b2$/);
    expect(tileUrl("lidar", "")).not.toContain("?v");
  });

  it("tileKeys builds set, null when absent", () => {
    const meta: MosaicMeta = {
      crs: "EPSG:32619", bbox: [0, 0, 10, 10], tile_px: 256, zmin: 0, zmax: 1, cell_m_at_zmax: 1,
      tiles: [[0, 0, 0], [1, 1, 1]],
    };
    const s = tileKeys(meta)!;
    expect(s).toBeInstanceOf(Set);
    expect(s.has("0/0/0")).toBe(true);
    expect(s.has("1/1/1")).toBe(true);
    const big: MosaicMeta = { ...meta, tiles: Array.from({ length: 20001 }, (_, i) => [0, i, 0] as [number, number, number]) };
    expect(tileKeys(big)!.size).toBe(20001);
    const none: MosaicMeta = { crs: "x", bbox: [0, 0, 10, 10], tile_px: 256, zmin: 0, zmax: 1, cell_m_at_zmax: 1 };
    expect(tileKeys(none)).toBeNull();
  });

  it("mosaicFrame accepts shifted bbox within tolerance", () => {
    const base: MosaicMeta = { crs: "x", bbox: [0, 0, 10, 10], tile_px: 256, zmin: 0, zmax: 1, cell_m_at_zmax: 1 };
    const shifted: MosaicMeta = { ...base, bbox: [0.0009, 0, 10.0009, 10] };
    const metas = { lidar: base, ortho: shifted, height: base, coverage: base };
    const f = mosaicFrame(metas);
    expect(f).not.toBeNull();
  });

  it("mosaicFrame accepts non-square within 0.01", () => {
    const base: MosaicMeta = { crs: "x", bbox: [0, 0, 10, 10.009], tile_px: 256, zmin: 0, zmax: 1, cell_m_at_zmax: 1 };
    const metas = { lidar: base, ortho: base, height: base, coverage: base };
    const f = mosaicFrame(metas);
    expect(f).not.toBeNull();
  });

  it("mosaicFrame throws on 2e-3 shift", () => {
    const base: MosaicMeta = { crs: "x", bbox: [0, 0, 10, 10], tile_px: 256, zmin: 0, zmax: 1, cell_m_at_zmax: 1 };
    const shifted: MosaicMeta = { ...base, bbox: [0.002, 0, 10.002, 10] };
    const metas = { lidar: base, ortho: shifted, height: base, coverage: base };
    expect(() => mosaicFrame(metas)).toThrow();
  });

  it("mosaicFrame throws on 2e-2 non-square", () => {
    const base: MosaicMeta = { crs: "x", bbox: [0, 0, 10, 10.02], tile_px: 256, zmin: 0, zmax: 1, cell_m_at_zmax: 1 };
    const metas = { lidar: base, ortho: base, height: base, coverage: base };
    expect(() => mosaicFrame(metas)).toThrow();
  });

  it("tileZoomFor numeric", () => {
    expect(tileZoomFor(0.669, 555, 256, 1)).toBe(2);
    expect(tileZoomFor(Math.log2(40), 555, 256, 1)).toBe(6);
    expect(tileZoomFor(0, 555, 256, 2)).toBe(2);
  });
});
