/* eslint-disable @typescript-eslint/no-explicit-any */
import { readFileSync } from "node:fs";
import { describe, it, expect } from "vitest";
import {
  METRIC_KEYS,
  HEADLINE,
  barValue,
  metricValue,
  approachOrder,
  approachStyle,
  latestByApproach,
  seriesByApproach,
  bestRun,
  gapText,
  isPassing,
  verdict,
  isBest,
  yDomain,
  fmtMetric,
  formatCount,
  TOKENS,
  DASHES,
} from "./evaluations";

const seed = JSON.parse(
  readFileSync(new URL("../../tests/fixtures/evals_seed.json", import.meta.url), "utf8")
) as { pass_bar: { psnr_min: number; road_depth_p95_max_m: number }; runs: any[] };

const expected = JSON.parse(
  readFileSync(new URL("../../tests/fixtures/evals_expected.json", import.meta.url), "utf8")
) as { verdict: string };

describe("evaluations lib", () => {
  it("METRIC_KEYS matches first-appearance order from seed", () => {
    const seen: string[] = [];
    for (const r of seed.runs) {
      for (const k of Object.keys(r.metrics)) {
        if (!seen.includes(k)) seen.push(k);
      }
    }
    expect([...METRIC_KEYS]).toEqual(seen);
  });

  it("HEADLINE contract", () => {
    const mapped = HEADLINE.map((h) => [h.key, h.log, h.barKey ?? null, h.dir]);
    expect(mapped).toEqual([
      ["psnr", false, "psnr_min", "up"],
      ["road_depth_p95_m", true, "road_depth_p95_max_m", "down"],
      ["lidar_ground_p50_m", true, null, "down"],
    ]);
    expect(barValue(HEADLINE[0], seed.pass_bar as any)).toBe(26);
    expect(barValue(HEADLINE[1], seed.pass_bar as any)).toBe(0.05);
    expect(barValue(HEADLINE[2], seed.pass_bar as any)).toBeUndefined();
  });

  it("latestByApproach", () => {
    const res = latestByApproach(seed.runs as any);
    expect(res.length).toBe(4);
    expect(res.map((r) => r.approach)).toEqual([
      "recon-core gsplat",
      "OmniRe",
      "SplatAD",
      "OmniRe 3-drive fusion",
    ]);
  });

  it("approachOrder + approachStyle", () => {
    const order = approachOrder(seed.runs as any);
    expect(order).toEqual(["recon-core gsplat", "OmniRe", "SplatAD", "OmniRe 3-drive fusion"]);
    const st = approachStyle(seed.runs as any, "SplatAD");
    expect(st.token).toBe(TOKENS[2]);
    expect(st.dash).toBe(DASHES[2]);
    expect(st.token).not.toMatch(/--ok|--warn|--danger/);
    expect(st.dash).not.toBe("none");
  });

  it("seriesByApproach x indices", () => {
    const s = seriesByApproach(seed.runs as any, "psnr" as any);
    const byApp = Object.fromEntries(s.map((x) => [x.approach, x.points.map((p) => p.x)]));
    expect(byApp["OmniRe"]).toEqual([1, 2, 3]);
    expect(byApp["recon-core gsplat"]).toEqual([0]);
    expect(byApp["SplatAD"]).toEqual([4, 5]);
    expect(byApp["OmniRe 3-drive fusion"]).toEqual([6]);
  });

  it("seriesByApproach lidar ground has 3 series (recon-core absent) but approachOrder still index2", () => {
    const s = seriesByApproach(seed.runs as any, "lidar_ground_p50_m" as any);
    expect(s.length).toBe(3);
    expect(s.map((x) => x.approach)).not.toContain("recon-core gsplat");
    const st = approachStyle(seed.runs as any, "SplatAD");
    expect(st.token).toBe(TOKENS[2]);
  });

  it("bestRun", () => {
    const psnr = bestRun(seed.runs as any, "psnr" as any, "up");
    expect(psnr?.run.id).toBe("splatad-35k");
    expect(psnr?.value).toBe(22.2646);
    const depth = bestRun(seed.runs as any, "road_depth_p95_m" as any, "down");
    expect(depth?.run.id).toBe("omnire-30k");
    expect(depth?.value).toBe(1.4095);
    const lidar = bestRun(seed.runs as any, "lidar_ground_p50_m" as any, "down");
    expect(lidar?.run.id).toBe("splatad-35k");
  });

  it("metricValue", () => {
    const run: any = { metrics: { road_depth_p95_m: 0, psnr: 0 } };
    expect(metricValue(run, "road_depth_p95_m" as any)).toBeUndefined();
    expect(metricValue(run, "psnr" as any)).toBe(0);
    const neg: any = { metrics: { road_depth_p95_m: -1 } };
    expect(metricValue(neg, "road_depth_p95_m" as any)).toBeUndefined();
    const absent: any = { metrics: {} };
    expect(metricValue(absent, "psnr" as any)).toBeUndefined();
  });

  it("isBest", () => {
    expect(isBest(5, [1, 5, 3], "up")).toBe(true);
    expect(isBest(5, [1, 5, 5], "up")).toBe(true);
    expect(isBest(undefined, [1, 2], "up")).toBe(false);
    expect(isBest(1, [], "up")).toBe(false);
  });

  it("fmtMetric", () => {
    expect(fmtMetric(undefined)).toBe("not measured");
    expect(fmtMetric(0)).toBe("0");
  });

  it("formatCount", () => {
    expect(formatCount(1000000)).toBe("1,000,000");
  });

  it("gapText", () => {
    expect(gapText(22.2646, 26, "up", "dB")).toBe("3.7354 dB short of bar");
    expect(gapText(1.4095, 0.05, "down", "m")).toBe("1.3595 m over bar");
    expect(gapText(5, undefined, "up", "m")).toBe("no bar");
  });

  it("isPassing", () => {
    const passing = { metrics: { psnr: 27, road_depth_p95_m: 0.04 } };
    expect(isPassing(passing as any, seed.pass_bar as any)).toBe(true);
    const failing = seed.runs[0];
    expect(isPassing(failing as any, seed.pass_bar as any)).toBe(false);
  });

  it("verdict", () => {
    expect(verdict(seed as any)).toBe(expected.verdict);
    expect(verdict({ pass_bar: seed.pass_bar, runs: [] } as any)).toBe("No evaluation runs recorded yet.");
    const passingReg = {
      pass_bar: seed.pass_bar,
      runs: [{ ...seed.runs[0], metrics: { psnr: 27, road_depth_p95_m: 0.04 } }],
    };
    expect(verdict(passingReg as any).startsWith("1 of 1 runs pass; ")).toBe(true);
  });

  it("yDomain", () => {
    const d1 = yDomain([0.028], undefined, true);
    expect(d1).not.toBeNull();
    expect(d1!.lo > 0 && d1!.lo < 0.028 && d1!.hi > 0.028 && d1!.lo < d1!.hi).toBe(true);
    const d2 = yDomain([118.7642], undefined, true);
    expect(d2!.lo > 0 && d2!.lo < 118.7642 && d2!.hi > 118.7642 && d2!.lo < d2!.hi).toBe(true);
    const d3 = yDomain([0.028, 118.7642], undefined, true);
    expect(d3!.lo > 0 && d3!.lo < d3!.hi).toBe(true);
    expect(yDomain([0, -1], undefined, true)).toBeNull();
    const lin = yDomain([5], undefined, false);
    expect(lin!.lo < 5 && lin!.hi > 5 && lin!.lo < lin!.hi).toBe(true);
    const withBar = yDomain([0.028], 0.05, true);
    expect(withBar!.lo > 0).toBe(true);
  });
});

describe("live file smoke", () => {
  it("shape", () => {
    const live = JSON.parse(
      readFileSync(new URL("../../docs/evals/recon-v2-results.json", import.meta.url), "utf8")
    );
    expect(live.pass_bar).toBeDefined();
    expect(Array.isArray(live.runs)).toBe(true);
    expect(live.runs.length).toBeGreaterThanOrEqual(7);
    for (const r of live.runs) {
      expect(typeof r.id).toBe("string");
      expect(typeof r.metrics).toBe("object");
    }
  });
});
