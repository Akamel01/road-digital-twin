import { describe, it, expect } from "vitest";
import {
  MAX_K,
  MAX_VIEW_ZOOM,
  viewStateOf,
  viewOf,
  fitState,
  minZoomOf,
  bitmapBounds,
  normaliseTileBBox,
  tileBounds,
} from "./tiles";

describe("tiles bridge", () => {
  it("round trips viewState for k in {0.5,3,40}", () => {
    for (const k of [0.5, 3, 40]) {
      const v = { k, tx: -12.5, ty: 7.25 };
      const size = { w: 800, h: 600 };
      const s = viewStateOf(v, size);
      expect(s.zoom).toBeCloseTo(Math.log2(k));
      const back = viewOf(s, size);
      expect(back.k).toBeCloseTo(k);
      expect(back.tx).toBeCloseTo(v.tx);
      expect(back.ty).toBeCloseTo(v.ty);
    }
  });

  it("fitState area", () => {
    const s = fitState({ x0: 0, y0: 0, x1: 100, y1: 100 }, { w: 800, h: 600 }, 1.02);
    expect((s.k ?? 2 ** s.zoom)).toBeCloseTo(5.8824, 3);
    expect(s.target).toEqual([50, 50, 0]);
  });

  it("facility fit caps at MAX_K", () => {
    const s = fitState({ x0: 0, y0: 0, x1: 2, y1: 2 }, { w: 1440, h: 900 }, 1.5, MAX_K);
    expect(s.k ?? 2 ** s.zoom).toBe(40);
    expect(s.zoom).toBe(Math.log2(40));
  });

  it("minZoomOf", () => {
    expect(minZoomOf({ x0: 0, y0: 0, x1: 100, y1: 100 }, { w: 800, h: 600 })).toBeCloseTo(2.2345, 3);
  });

  it("bitmapBounds", () => {
    expect(bitmapBounds([[0, 0], [256, 256]])).toEqual([0, 256, 256, 0]);
    expect(bitmapBounds([[10, 20], [30, 40]])).toEqual([10, 40, 30, 20]);
  });

  it("normaliseTileBBox flat", () => {
    expect(normaliseTileBBox([10, 20, 30, 40])).toEqual([[10, 20], [30, 40]]);
  });
  it("normaliseTileBBox nested", () => {
    expect(normaliseTileBBox([[10, 20], [30, 40]])).toEqual([[10, 20], [30, 40]]);
  });
  it("normaliseTileBBox object", () => {
    expect(normaliseTileBBox({ west: 10, south: 20, east: 30, north: 40 })).toEqual([[10, 20], [30, 40]]);
  });
  it("normaliseTileBBox null cases", () => {
    expect(normaliseTileBBox(null)).toBeNull();
    expect(normaliseTileBBox([1, 2])).toBeNull();
  });

  it("tileBounds", () => {
    expect(tileBounds({ x: 1, y: 0, z: 1 }, 100)).toEqual([[50, 0], [100, 50]]);
    expect(tileBounds({ x: 0, y: 1, z: 1 }, 100)).toEqual([[0, 50], [50, 100]]);
  });

  it("MAX_VIEW_ZOOM", () => {
    expect(MAX_VIEW_ZOOM).toBe(Math.log2(40));
  });
});
