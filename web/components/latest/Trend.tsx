import type { Gate, TrendPoint } from "@/lib/latest";
import { fmt } from "@/lib/latest";
import styles from "./latest.module.css";

const W = 220;
const H = 64;

function Chart({ metric, op, threshold, trend }: { metric: string; op: string; threshold: number; trend: TrendPoint[] }) {
  const pts = trend.map((t, i) => ({ i, v: t.metrics[metric] })).filter((p) => typeof p.v === "number");
  const vals = [...pts.map((p) => p.v), threshold];
  let lo = Math.min(...vals);
  let hi = Math.max(...vals);
  if (hi === lo) hi = lo + 1;
  const pad = (hi - lo) * 0.12;
  lo -= pad;
  hi += pad;
  const x = (i: number) => (trend.length < 2 ? W / 2 : 6 + (i / (trend.length - 1)) * (W - 12));
  const y = (v: number) => H - 4 - ((v - lo) / (hi - lo)) * (H - 8);
  const last = pts[pts.length - 1];
  const pass = op === "<=" ? last.v <= threshold : last.v >= threshold;
  return (
    <figure className={styles.trend}>
      <figcaption>
        <span>{metric}</span>
        <b className={pass ? styles.ok : styles.bad}>{fmt(last.v)}</b>
      </figcaption>
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`${metric} over ${trend.length} builds, now ${fmt(last.v)}, threshold ${op} ${fmt(threshold)}`}>
        <line x1="0" x2={W} y1={y(threshold)} y2={y(threshold)} className={styles.thr} />
        <polyline points={pts.map((p) => `${x(p.i)},${y(p.v)}`).join(" ")} className={styles.line} />
        {pts.map((p) => (
          <circle key={p.i} cx={x(p.i)} cy={y(p.v)} r={p.i === last.i ? 3.2 : 2} className={pass || p.i !== last.i ? styles.dot : styles.dotBad} />
        ))}
      </svg>
      <small>
        threshold {op} {fmt(threshold)} · {pts.length} {pts.length === 1 ? "build" : "builds"}
      </small>
    </figure>
  );
}

export default function Trend({ gates, trend }: { gates: Record<string, Gate>; trend: TrendPoint[] }) {
  const checks = Object.entries(gates).flatMap(([id, g]) => g.checks.map((c) => ({ id, ...c })));
  const seen = checks.filter((c) => trend.some((t) => typeof t.metrics[c.metric] === "number"));
  const unseen = checks.filter((c) => !seen.includes(c));
  return (
    <>
      <div className={styles.trends}>
        {seen.map((c) => (
          <Chart key={c.metric} metric={c.metric} op={c.op} threshold={c.threshold} trend={trend} />
        ))}
      </div>
      {trend.length < 2 && <p className={styles.note}>Trends start with this build and fill in as the pipeline evaluates new builds.</p>}
      {unseen.length > 0 && (
        <p className={styles.note}>Not measured in any build yet: {unseen.map((c) => c.metric).join(", ")}.</p>
      )}
    </>
  );
}
