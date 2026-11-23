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
  METRIC_INFO,
  axisTicks,
  fmtValue,
  dirText,
  PASS_BAR_MEANING,
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

  it("METRIC_INFO keys", () => {
    expect([...Object.keys(METRIC_INFO)].sort()).toEqual([...METRIC_KEYS].sort());
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
    expect(Object.fromEntries(res.map((r) => [r.approach, r.id]))).toMatchObject({
      "recon-core gsplat": "reconcore-baseline",
      OmniRe: "omnire-30k",
      SplatAD: "splatad-35k",
      "OmniRe 3-drive fusion": "omnire-fuse3",
    });
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

  it("seriesByApproach keeps gaps (no zero fill)", () => {
    const runs: any[] = [
      { approach: "A", metrics: { psnr: 1 } },
      { approach: "A", metrics: {} },
      { approach: "A", metrics: { psnr: 3 } },
    ];
    const s = seriesByApproach(runs, "psnr" as any);
    expect(s[0].points).toEqual([
      { x: 0, v: 1 },
      { x: 2, v: 3 },
    ]);
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
    expect(lidar?.value).toBe(0.028);
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
    expect(gapText(22.2646, 26, "psnr" as any)).toBe("3.7 dB short of bar");
    expect(gapText(1.4095, 0.05, "road_depth_p95_m" as any)).toBe("1.36 m over bar");
    expect(gapText(5, undefined, "psnr" as any)).toBe("no bar");
  });

  it("METRIC_INFO coverage", () => {
    expect(Object.keys(METRIC_INFO).length).toBe(10);
    for (const k of METRIC_KEYS) {
      const info = METRIC_INFO[k];
      expect(typeof info.name).toBe("string");
      expect(info.name.length).toBeGreaterThan(0);
      expect(typeof info.meaning).toBe("string");
      expect(info.meaning.length).toBeGreaterThan(0);
      expect(typeof info.unit).toBe("string");
      expect(info.dir === "up" || info.dir === "down").toBe(true);
      expect(typeof info.log).toBe("boolean");
    }
    expect(METRIC_INFO.psnr.name).toBe("Image match (PSNR)");
    expect(METRIC_INFO.lidar_ground_p50_m.meaning).toContain("more than 10°");
    expect(dirText("up")).toBe("higher is better ↑");
    expect(dirText("down")).toBe("lower is better ↓");
    expect(PASS_BAR_MEANING).toContain("26.0 dB");
  });

  it("HEADLINE barKey values", () => {
    expect(HEADLINE[0].barKey).toBe("psnr_min");
    expect(HEADLINE[1].barKey).toBe("road_depth_p95_max_m");
    expect(HEADLINE[2].barKey).toBeUndefined();
  });

  it("seriesByApproach date sort and tie-break", () => {
    const runs: any[] = [
      { date: "2026-01-03", approach: "A", metrics: { psnr: 1 } },
      { date: "2026-01-01", approach: "A", metrics: { psnr: 2 } },
      { date: "2026-01-02", approach: "A", metrics: { psnr: 3 } },
      { date: "2026-01-02", approach: "A", metrics: { psnr: 4 } },
    ];
    const s = seriesByApproach(runs, "psnr" as any);
    expect(s[0].points.map((p: any) => p.x)).toEqual([1, 2, 3, 0]);
  });

  it("fmtValue", () => {
    expect(fmtValue("psnr" as any, 22.2646)).toBe("22.3");
    expect(fmtValue("ssim" as any, 0.5865)).toBe("0.587");
    expect(fmtValue("road_depth_p95_m" as any, 118.7642)).toBe("118.76");
    expect(fmtValue("road_depth_p95_m" as any, 1.4095)).toBe("1.41");
    expect(fmtValue("road_depth_p95_m" as any, 0.028)).toBe("0.028");
    expect(fmtValue("road_depth_p95_m" as any, 0.05)).toBe("0.050");
    expect(fmtValue("psnr" as any, 0)).toBe("0.0");
    expect(fmtValue("psnr" as any, undefined)).toBe("not measured");
  });

  it("axisTicks", () => {
    const lin = axisTicks(0, 10, false);
    expect(lin.length).toBe(4);
    expect(lin[0]).toBe(0);
    expect(lin[3]).toBe(10);
    const log = axisTicks(0.01, 100, true);
    expect(log.length).toBe(4);
    expect(log.every((v) => v > 0)).toBe(true);
    expect(log[0]).toBeCloseTo(0.01, 5);
  });

  it("series date order", () => {
    const s = seriesByApproach(seed.runs as any, "psnr" as any);
    for (const ser of s) {
      const xs = ser.points.map((p) => p.x);
      // x indices should be non-decreasing by run date
      const dates = xs.map((x) => (seed.runs as any)[x].date);
      const sorted = [...dates].sort();
      expect(dates).toEqual(sorted);
    }
  });

  it("isPassing", () => {
    const passing = { metrics: { psnr: 27, road_depth_p95_m: 0.04 } };
    expect(isPassing(passing as any, seed.pass_bar as any)).toBe(true);
    const failing = seed.runs[0];
    expect(isPassing(failing as any, seed.pass_bar as any)).toBe(false);
    expect(isPassing({ metrics: { psnr: 27 } } as any, seed.pass_bar as any)).toBe(false);
    expect(isPassing({ metrics: { psnr: 27, road_depth_p95_m: 0 } } as any, seed.pass_bar as any)).toBe(false);
    expect(isPassing({ metrics: { psnr: 27, road_depth_p95_m: 0.04 } } as any, seed.pass_bar as any)).toBe(true);
    const over = { metrics: { psnr: 27, road_depth_p95_m: 1 } };
    expect(isPassing(over as any, seed.pass_bar as any)).toBe(false);
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
    expect(withBar!.hi >= 0.05).toBe(true);
    expect(withBar!.lo < 0.05).toBe(true);
  });
});

describe("live file smoke", () => {
  it("shape", () => {
    const live = JSON.parse(
      readFileSync(new URL("../../docs/evals/recon-v2-results.json", import.meta.url), "utf8")
    );
    expect(live.pass_bar).toBeDefined();
    expect(typeof live.pass_bar.psnr_min).toBe("number");
    expect(typeof live.pass_bar.road_depth_p95_max_m).toBe("number");
    expect(live.pass_bar.psnr_min).toBe(26);
    expect(live.pass_bar.road_depth_p95_max_m).toBe(0.05);
    expect(Array.isArray(live.runs)).toBe(true);
    expect(live.runs.length).toBeGreaterThanOrEqual(7);
    for (const r of live.runs) {
      expect(typeof r.id).toBe("string");
      expect(typeof r.metrics).toBe("object");
    }
  });
});
