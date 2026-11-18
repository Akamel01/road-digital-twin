import { describe, it, expect } from "vitest";
import { DEFAULT_LAYERS, TRIO, applyTrioToggle, applySafetyLayers, rastersFor } from "./layers";

describe("layers", () => {
  it("trio exclusivity: each on clears others", () => {
    for (const k of TRIO) {
      const off = { ...DEFAULT_LAYERS, height: false, lidar: false, ortho: false };
      const next = applyTrioToggle(off, k);
      expect(next[k]).toBe(true);
      for (const o of TRIO) if (o !== k) expect(next[o]).toBe(false);
    }
  });
  it("toggling on trio member off clears it", () => {
    const base = { ...DEFAULT_LAYERS, lidar: true, height: false, ortho: false };
    const off = applyTrioToggle(base, "lidar");
    expect(off.lidar).toBe(false);
  });
  it("toggling ortho/height with lidar on yields only that one", () => {
    const base = { ...DEFAULT_LAYERS, lidar: true, height: false, ortho: false };
    const o = applyTrioToggle(base, "ortho");
    expect(o).toMatchObject({ ortho: true, lidar: false, height: false });
    const h = applyTrioToggle(base, "height");
    expect(h).toMatchObject({ height: true, lidar: false, ortho: false });
  });
  it("applySafetyLayers yields ortho only among trio", () => {
    const r = applySafetyLayers({ ...DEFAULT_LAYERS, lidar: true });
    expect(r.ortho).toBe(true);
    expect(r.lidar).toBe(false);
    expect(r.height).toBe(false);
  });
  it("rastersFor order and coverage", () => {
    expect(rastersFor({ height: false, lidar: true, ortho: false, markings: true, crosswalks: true, curbs: true }, null)).toEqual(["lidar"]);
    expect(rastersFor({ height: true, lidar: false, ortho: false, markings: true, crosswalks: true, curbs: true }, "coverage")).toEqual(["height", "coverage"]);
  });
  it("never two trio rasters", () => {
    const layers = { height: true, lidar: true, ortho: true, markings: true, crosswalks: true, curbs: true };
    const r = rastersFor(layers, null);
    const trioCount = r.filter((x) => ["height", "ortho", "lidar"].includes(x)).length;
    expect(trioCount).toBeLessThanOrEqual(1);
  });
  it("element toggles do not change trio", () => {
    const base = { ...DEFAULT_LAYERS };
    const next = applyTrioToggle(base, "markings");
    expect(next.height).toBe(base.height);
    expect(next.lidar).toBe(base.lidar);
    expect(next.ortho).toBe(base.ortho);
  });
});
