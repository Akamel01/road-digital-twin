"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { BrandLockup } from "@/components/TopBar";
import LivingMark from "../latest/LivingMark";
import styles from "../latest/latest.module.css";
import local from "./evaluations.module.css";
import EvalChart from "./EvalChart";
import {
  HEADLINE,
  isPassing,
  latestByApproach,
  loadEvaluations,
  metricValue,
  runLabel,
  verdict,
  bestRun,
  gapText,
  barValue,
  formatCount,
  METRIC_KEYS,
  isBest,
  type EvalRegistry,
  type MetricKey,
  ticketUrl,
} from "@/lib/evaluations";
import { fmt } from "@/lib/latest";

const LEGAL =
  "Derived from nuScenes (CC BY-NC-SA 4.0). Street names © OpenStreetMap contributors (ODbL). Non-commercial research demo.";

const METRIC_HEADERS: Record<MetricKey, string> = {
  psnr: "PSNR (dB)",
  ssim: "SSIM",
  road_depth_p50_m: "Road p50 (m)",
  road_depth_p95_m: "Road p95 (m)",
  sidewalk_depth_p50_m: "Sidewalk p50 (m)",
  sidewalk_depth_p95_m: "Sidewalk p95 (m)",
  lidar_all_p50_m: "LiDAR p50 (m)",
  lidar_all_p95_m: "LiDAR p95 (m)",
  lidar_ground_p50_m: "LiDAR ground p50 (m)",
  lidar_ground_p95_m: "LiDAR ground p95 (m)",
};

const DIR_UP = new Set<MetricKey>(["psnr", "ssim"]);

export default function Evaluations() {
  const [data, setData] = useState<EvalRegistry | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    loadEvaluations()
      .then(setData)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)));
  }, []);

  return (
    <div className={styles.page} id="eval-page">
      <header className={local.top}>
        <BrandLockup />
        <b className={local.title}>Evaluations</b>
        <Link className={local.nav} href="/latest">
          Latest build
        </Link>
      </header>

      {!data && (
        <div className={styles.wait} role="status">
          <LivingMark state={error ? "waiting" : "loading"} size={56} />
          <p>{error ?? "Loading evaluation results…"}</p>
        </div>
      )}

      {data && (
        <main className={styles.main}>
          <section className={`${styles.panel} glass`} aria-labelledby="h-brief">
            <h2 id="h-brief" className="over">
              Briefing
            </h2>
            <p className={local.gap}>
              Pass bar: PSNR ≥ {fmt(data.pass_bar.psnr_min)} dB · road depth p95 ≤{" "}
              {fmt(data.pass_bar.road_depth_p95_max_m)} m
            </p>
            <div className={local.headlines}>
              {HEADLINE.map((spec) => {
                const best = bestRun(data.runs, spec.key, spec.dir);
                const bar = barValue(spec, data.pass_bar);
                return (
                  <div key={spec.key} className={local.headline}>
                    <span>{spec.label}</span>
                    <b>{best ? `${fmt(best.value)} ${spec.unit}` : "not measured"}</b>
                    <span>{best ? runLabel(best.run) : "no run has this metric"}</span>
                    <small>{best ? `#${best.run.ticket}` : ""}</small>
                    <span className={local.gap}>
                      {best ? gapText(best.value, bar, spec.dir, spec.unit) : ""}
                    </span>
                  </div>
                );
              })}
            </div>
            <p
              className={`${styles.banner} ${
                data.runs.some((r) => isPassing(r, data.pass_bar)) ? styles.bannerOk : styles.bannerWarn
              }`}
            >
              {verdict(data)}
            </p>
            <p className={local.gap}>
              {data.runs.length} runs · {latestByApproach(data.runs).length} approaches
            </p>
          </section>

          <section className={`${styles.panel} glass`} aria-labelledby="h-trends">
            <h2 id="h-trends" className="over">
              Trends
            </h2>
            <div className={styles.trends}>
              {HEADLINE.map((spec) => (
                <EvalChart
                  key={spec.key}
                  spec={spec}
                  bar={barValue(spec, data.pass_bar)}
                  runs={data.runs}
                />
              ))}
            </div>
          </section>

          <section className={`${styles.panel} glass`} aria-labelledby="h-compare">
            <h2 id="h-compare" className="over">
              Approach comparison
            </h2>
            <div className={styles.tableWrap}>
              <table className={styles.table}>
                <thead>
                  <tr>
                    <th>Approach</th>
                    <th>Latest run</th>
                    {METRIC_KEYS.map((k) => (
                      <th key={k} className={styles.num}>
                        {METRIC_HEADERS[k]}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {latestByApproach(data.runs).map((row) => {
                    return (
                      <tr key={row.id}>
                        <td>
                          {row.approach}
                          {row.variant && <small> {row.variant}</small>}
                          <br />
                          <small>#{row.ticket}</small>
                        </td>
                        <td>
                          <code>{row.id}</code>
                        </td>
                        {METRIC_KEYS.map((k) => {
                          const v = metricValue(row, k);
                          const dir = DIR_UP.has(k) ? "up" : "down";
                          const columnVals = latestByApproach(data.runs).map((r) => metricValue(r, k));
                          const best = isBest(v, columnVals, dir);
                          return (
                            <td key={k} className={styles.num}>
                              {v === undefined ? (
                                <span className={styles.muted}>not measured</span>
                              ) : (
                                <span className={best ? local.best : undefined}>{fmt(v)}</span>
                              )}
                            </td>
                          );
                        })}
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </section>

          <section className={`${styles.panel} glass`} aria-labelledby="h-runs">
            <h2 id="h-runs" className="over">
              All runs
            </h2>
            <div className={styles.tableWrap}>
              <table className={styles.table}>
                <thead>
                  <tr>
                    <th>Date</th>
                    <th>Run</th>
                    <th>Ticket</th>
                    <th>Iterations</th>
                    <th>Train min</th>
                    <th>Cap</th>
                    <th>Eval set</th>
                    <th>Notes</th>
                  </tr>
                </thead>
                <tbody>
                  {[...data.runs].reverse().map((r) => (
                    <tr key={r.id}>
                      <td>{r.date}</td>
                      <td>
                        <code>{r.id}</code> {r.approach} {r.variant}
                      </td>
                      <td>
                        <a href={ticketUrl(r.ticket)} target="_blank" rel="noreferrer">
                          #{r.ticket}
                        </a>
                      </td>
                      <td className={styles.num}>{formatCount(r.iterations)}</td>
                      <td className={styles.num}>{r.train_minutes === null ? "-" : fmt(r.train_minutes)}</td>
                      <td className={styles.num}>
                        {r.gaussian_cap === null ? "-" : formatCount(r.gaussian_cap)}
                      </td>
                      <td>{r.eval_set}</td>
                      <td>{r.notes === "" ? "-" : r.notes}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          <footer className={styles.legal}>{LEGAL}</footer>
        </main>
      )}
    </div>
  );
}


