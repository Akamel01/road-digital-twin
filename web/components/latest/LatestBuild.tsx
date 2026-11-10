"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Crown } from "@/components/TopBar";
import { type Cloud, fmt, loadCloud, loadScorecard, loadTrend, type Scorecard, type TrendPoint } from "@/lib/latest";
import CloudView from "./CloudView";
import LivingMark from "./LivingMark";
import Trend from "./Trend";
import styles from "./latest.module.css";

const LEGAL =
  "Derived from nuScenes (CC BY-NC-SA 4.0). Street names © OpenStreetMap contributors (ODbL). Non-commercial research demo.";

function when(iso: string): string {
  return `${iso.slice(0, 10)} ${iso.slice(11, 16)} UTC`;
}

function Chip({ status }: { status: string }) {
  const cls = status === "go" ? styles.ok : status === "no-go" ? styles.bad : styles.muted;
  return <span className={`${styles.chip} ${cls}`}>{status === "go" ? "GO" : status === "no-go" ? "NO-GO" : "not measured"}</span>;
}

export default function LatestBuild() {
  const [card, setCard] = useState<Scorecard | null>(null);
  const [trend, setTrend] = useState<TrendPoint[]>([]);
  const [cloud, setCloud] = useState<Cloud | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    loadScorecard()
      .then((c) => {
        setCard(c);
        loadCloud(c.cloud, c.published_at).then(setCloud, (e: unknown) => setError(e instanceof Error ? e.message : String(e)));
      }, (e: unknown) => setError(e instanceof Error ? e.message : String(e)));
    loadTrend().then(setTrend);
  }, []);

  return (
    <div className={styles.page}>
      <header className={styles.top}>
        <div className={styles.brand}>
          <Crown />
          Road digital twin
        </div>
        <b className={styles.title}>Latest build</b>
        <Link className={styles.back} href="/">
          Published twin
        </Link>
      </header>

      {!card && (
        <div className={styles.wait} role="status">
          <LivingMark state={error ? "waiting" : "loading"} size={56} />
          <p>{error ?? "Loading the latest build…"}</p>
        </div>
      )}

      {card && (
        <main className={styles.main}>
          <section className={`${styles.banner} ${card.gate_passed ? styles.bannerOk : styles.bannerWarn}`} aria-label="Gate status">
            <span className={styles.flag}>{card.gate_passed ? "Gate-passed" : "Not gate-passed"}</span>
            <p>
              {card.gate_passed
                ? "Every gate is GO for this build."
                : "This is the newest build of the area, shown as it is. It has not passed the gates, so it is not the published twin."}
            </p>
            <small>
              Area {card.area} · built {when(card.built_at)} · gates v{card.gates_version} · shown {when(card.published_at)}
            </small>
          </section>

          <section className={`${styles.panel} glass`} aria-labelledby="h-cloud">
            <h2 id="h-cloud" className="over">
              Area viewer
            </h2>
            <div className={styles.stage}>
              {cloud ? (
                <CloudView cloud={cloud} card={card} />
              ) : (
                <div className={styles.wait} role="status">
                  <LivingMark state={error ? "waiting" : "loading"} size={48} />
                  <p>{error ?? "Loading the point cloud…"}</p>
                </div>
              )}
            </div>
            <small className={styles.note}>
              Top-down view of the merged cloud of {card.drives.length} drives, thinned for the web to{" "}
              {card.cloud.n_points.toLocaleString("en-US")} of {card.cloud.n_total.toLocaleString("en-US")} points (
              {card.cloud.voxel_m} m grid, {(card.cloud.bytes / 1e6).toFixed(1)} MB). Drag to pan, scroll or pinch to zoom.
              Extracted features come with the area feature stage and are not in this build yet.
            </small>
          </section>

          <section className={`${styles.panel} glass`} aria-labelledby="h-score">
            <h2 id="h-score" className="over">
              Gate scorecard
            </h2>
            <div className={styles.tableWrap}>
              <table className={styles.table}>
                <thead>
                  <tr>
                    <th>Gate</th>
                    <th>Metric</th>
                    <th className={styles.num}>Value</th>
                    <th className={styles.num}>Threshold</th>
                    <th>Result</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(card.gates).flatMap(([id, g]) =>
                    g.checks.map((c, i) => (
                      <tr key={c.metric}>
                        {i === 0 && (
                          <th scope="row" rowSpan={g.checks.length}>
                            <b>{id}</b> {g.name}
                          </th>
                        )}
                        <td>
                          <code>{c.metric}</code>
                        </td>
                        <td className={styles.num}>{fmt(c.value)}</td>
                        <td className={styles.num}>
                          {c.op} {fmt(c.threshold)}
                        </td>
                        <td>
                          <Chip status={c.status} />
                        </td>
                      </tr>
                    )),
                  )}
                </tbody>
              </table>
            </div>
          </section>

          <section className={`${styles.panel} glass`} aria-labelledby="h-trend">
            <h2 id="h-trend" className="over">
              Trend over builds
            </h2>
            <Trend gates={card.gates} trend={trend} />
          </section>

          <section className={`${styles.panel} glass`} aria-labelledby="h-drives">
            <h2 id="h-drives" className="over">
              Drives in this build
            </h2>
            <div className={styles.tableWrap}>
              <table className={styles.table}>
                <thead>
                  <tr>
                    <th>Scene</th>
                    <th>Date</th>
                    <th>Role</th>
                    <th className={styles.num}>Points</th>
                    <th className={styles.num}>Fitness</th>
                    <th className={styles.num}>RMSE m</th>
                  </tr>
                </thead>
                <tbody>
                  {card.drives.map((d) => (
                    <tr key={d.index}>
                      <th scope="row">{d.scene}</th>
                      <td>{d.date}</td>
                      <td>{d.role}</td>
                      <td className={styles.num}>{d.n_points?.toLocaleString("en-US")}</td>
                      <td className={styles.num}>{fmt(d.fitness)}</td>
                      <td className={styles.num}>{fmt(d.rmse_m)}</td>
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
