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
  METRIC_INFO,
  isBest,
  fmtValue,
  type EvalRegistry,
  ticketUrl,
  dirText,
  PASS_BAR_MEANING,
} from "@/lib/evaluations";
import { fmt } from "@/lib/latest";

const LEGAL =
  "Derived from nuScenes (CC BY-NC-SA 4.0). Street names © OpenStreetMap contributors (ODbL). Non-commercial research demo.";

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
              Pass bar: PSNR ≥ {fmtValue("psnr", data.pass_bar.psnr_min)} dB · road depth p95 ≤{" "}
              {fmtValue("road_depth_p95_m", data.pass_bar.road_depth_p95_max_m)} m
            </p>
            <div className={local.headlines}>
              {HEADLINE.map((spec) => {
                const best = bestRun(data.runs, spec.key, spec.dir);
                const bar = barValue(spec, data.pass_bar);
                return (
                  <div key={spec.key} className={local.headline}>
                    <span>
                      {spec.name} · {dirText(spec.dir)}
                    </span>
                    <b>{best ? `${fmtValue(spec.key, best.value)} ${spec.unit}`.trim() : "not measured"}</b>
                    <span>{best ? runLabel(best.run) : "no run has this metric"}</span>
                    <small>
                      {best ? (
                        <a className={local.ticketLink} href={ticketUrl(best.run.ticket)} target="_blank" rel="noreferrer">
                          #{best.run.ticket}
                        </a>
                      ) : (
                        ""
                      )}
                    </small>
                    <span className={local.gap}>
                      {best ? gapText(best.value, bar, spec.key) : ""}
                    </span>
                    <small className={local.gap}>{spec.meaning}</small>
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

          <section className={`${styles.panel} glass`} aria-labelledby="h-glossary">
            <h2 id="h-glossary" className="over">
              How to read this
            </h2>
            <dl className={local.glossary}>
              {METRIC_KEYS.map((k) => {
                const info = METRIC_INFO[k];
                return (
                  <div key={k} className={local.glossaryItem}>
                    <dt>
                      {info.name} · {dirText(info.dir)}
                    </dt>
                    <dd>{info.meaning}</dd>
                  </div>
                );
              })}
              <div className={local.glossaryItem}>
                <dt>Pass bar · both bars must pass</dt>
                <dd>{PASS_BAR_MEANING}</dd>
              </div>
            </dl>
          </section>

          <section className={`${styles.panel} glass`} aria-labelledby="h-trends">
            <h2 id="h-trends" className="over">
              Trends
            </h2>
            <div className={local.trendsGrid}>
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
            <div className={local.tableScroll}>
              <table className={local.compareTable}>
                <thead>
                  <tr>
                    <th className={local.stickyFirst}>Approach</th>
                    <th>Latest run</th>
                    {METRIC_KEYS.map((k) => {
                      const info = METRIC_INFO[k];
                      return (
                        <th key={k} className={local.num}>
                          <span className={local.headerName}>{info.header}</span>
                          <small className={local.headerMeaning}>{info.meaning}</small>
                          <small className={local.headerDir}>{dirText(info.dir)}</small>
                        </th>
                      );
                    })}
                  </tr>
                </thead>
                <tbody>
                  {(() => {
                    const rows = latestByApproach(data.runs);
                    return rows.map((row) => (
                      <tr key={row.id}>
                        <td className={local.stickyFirst}>
                          {row.approach}
                          {row.variant && <small> {row.variant}</small>}
                          <br />
                          <small>#{row.ticket}</small>
                        </td>
                        <td title={row.id} className={local.wrapNormal}>
                          {row.variant || row.approach}
                        </td>
                        {METRIC_KEYS.map((k) => {
                          const v = metricValue(row, k);
                          const dir = METRIC_INFO[k].dir;
                          const columnVals = rows.map((r) => metricValue(r, k));
                          const best = isBest(v, columnVals, dir);
                          return (
                            <td key={k} className={local.num}>
                              {v === undefined ? (
                                <span className={styles.muted}>not measured</span>
                              ) : (
                                <span className={best ? local.best : undefined}>{fmtValue(k, v)}</span>
                              )}
                            </td>
                          );
                        })}
                      </tr>
                    ));
                  })()}
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
                      <td className={local.nowrap}>{r.date}</td>
                      <td>
                        <code>{r.id}</code> {r.approach} {r.variant}
                      </td>
                      <td>
                        <a className={local.ticketLink} href={ticketUrl(r.ticket)} target="_blank" rel="noreferrer">
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
