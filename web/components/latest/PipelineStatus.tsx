import type { Health } from "@/lib/latest";
import { fmt } from "@/lib/latest";
import styles from "./latest.module.css";

function uptime(s: number | null): string {
  if (s == null) return "down";
  return s >= 86400 ? `${Math.floor(s / 86400)} d` : s >= 3600 ? `${Math.floor(s / 3600)} h` : `${Math.floor(s / 60)} min`;
}

function arrow(m: { op: string; trend: number[] }): string {
  const t = m.trend;
  if (t.length < 2) return "·";
  const d = t[t.length - 1] - t[0];
  if (d === 0) return "→";
  return (d < 0) === (m.op === "<=") ? "↑ better" : "↓ worse";
}

export default function PipelineStatus({ health }: { health: Health }) {
  const metrics = Object.entries(health.progress.metrics);
  const ratchet = health.progress.g2_ratchet;
  const gpu = health.gpu;
  return (
    <section className={`${styles.panel} glass`} aria-labelledby="h-pipe">
      <h2 id="h-pipe" className="over">
        Pipeline status
      </h2>
      <p className={styles.note}>Updated {health.updated.slice(0, 10)} {health.updated.slice(11, 16)} UTC</p>
      <div className={styles.tableWrap}>
        <table className={styles.table}>
          <tbody>
            {Object.entries(health.processes).map(([n, p]) => (
              <tr key={n}>
                <th scope="row">{n}</th>
                <td>{p.alive ? <span className={`${styles.chip} ${styles.ok}`}>running</span> : <span className={`${styles.chip} ${styles.bad}`}>down</span>}</td>
                <td className={styles.num}>{uptime(p.uptime_s)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className={styles.tableWrap}>
        <table className={styles.table}>
          <thead>
            <tr>
              <th>Tier</th>
              <th className={styles.num}>Runs / 24 h</th>
              <th className={styles.num}>Job hours</th>
              <th>Last finished</th>
              <th>Last failure</th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(health.tiers).map(([n, t]) => (
              <tr key={n}>
                <th scope="row">{n}</th>
                <td className={styles.num}>{t.runs}</td>
                <td className={styles.num}>{fmt(t.job_hours)}</td>
                <td>{t.finished ? t.finished.slice(0, 16).replace("T", " ") : "·"}</td>
                <td>{t.failed ? t.failed.at.slice(0, 16).replace("T", " ") : "·"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {metrics.length > 0 && (
        <div className={styles.tableWrap}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th>Gate metric</th>
                <th className={styles.num}>Latest</th>
                <th className={styles.num}>Best</th>
                <th>Trend ({health.progress.builds} builds)</th>
              </tr>
            </thead>
            <tbody>
              {metrics.map(([name, m]) => (
                <tr key={name}>
                  <th scope="row">
                    <b>{m.gate}</b> <code>{name}</code>
                  </th>
                  <td className={styles.num}>{fmt(m.latest)}</td>
                  <td className={styles.num}>{fmt(m.best)}</td>
                  <td>{arrow(m)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <small className={styles.note}>
        {ratchet && <>G2 ratchet at {ratchet.threshold} m, {ratchet.passing_in_a_row} of 3 passing in a row. </>}
        Queue {health.queue.running} running, {health.queue.pending} pending. Idle {Math.round(health.idle_min.all)} min.
        Free disk {fmt(health.disk_free_gb["/"])} GB root, {fmt(health.disk_free_gb["/data"])} GB data.
        {gpu.vram_used_mb != null && <> GPU {Math.round(gpu.vram_used_mb)} of {Math.round(gpu.vram_total_mb ?? 0)} MB, lease {gpu.lease}.</>}
        {Object.keys(health.paused).length > 0 && <> Paused sources: {Object.keys(health.paused).join(", ")}.</>}
        {" "}{health.throughput.runs_per_hour} runs per hour.
      </small>
    </section>
  );
}
