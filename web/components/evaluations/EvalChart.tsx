import { fmt } from "@/lib/latest";
import { approachStyle, type EvalRun, type Headline, seriesByApproach, yDomain } from "@/lib/evaluations";
import styles from "../latest/latest.module.css";
import local from "./evaluations.module.css";

const W = 220;
const H = 64;

export default function EvalChart({
  spec,
  bar,
  runs,
}: {
  spec: Headline;
  bar?: number;
  runs: EvalRun[];
}) {
  const series = seriesByApproach(runs, spec.key);
  const allValues = series.flatMap((s) => s.points.map((p) => p.v));
  if (bar !== undefined) allValues.push(bar);
  const domain = yDomain(allValues, bar, spec.log);

  const w = (v: number) => (spec.log ? Math.log10(v) : v);
  const x = (i: number) => (runs.length < 2 ? W / 2 : 6 + (i / (runs.length - 1)) * (W - 12));
  const y = (v: number, lo: number, hi: number) =>
    H - 4 - ((w(v) - w(lo)) / (w(hi) - w(lo))) * (H - 8);

  if (series.length === 0) {
    return (
      <figure className={styles.trend}>
        <figcaption>
          <span>{spec.label}</span>
        </figcaption>
        <p className={styles.note}>not measured</p>
      </figure>
    );
  }
  if (domain === null) {
    return (
      <figure className={styles.trend}>
        <figcaption>
          <span>{spec.label}</span>
        </figcaption>
        <p className={styles.note}>not measured</p>
      </figure>
    );
  }

  const { lo, hi } = domain;
  const first = runs[0];
  const last = runs[runs.length - 1];

  const ariaLabel = `${spec.label} by run (oldest → newest): ${series.length} approaches, ${bar === undefined ? "no pass bar defined" : `pass bar ${spec.dir === "up" ? "≥" : "≤"} ${fmt(bar)} ${spec.unit}`}, ${spec.log ? "log" : "linear"} scale`;

  return (
    <figure className={styles.trend}>
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={ariaLabel}>
        {bar !== undefined && (
          <line x1={0} x2={W} y1={y(bar, lo, hi)} y2={y(bar, lo, hi)} className={styles.thr} />
        )}
        {series.map((s) => {
          const { token: colour, dash } = approachStyle(runs, s.approach);
          const pts = s.points;
          return (
            <g key={s.approach}>
              {pts.length >= 2 && (
                <polyline
                  className={styles.line}
                  style={{ stroke: colour, strokeDasharray: dash }}
                  points={pts.map((p) => `${x(p.x)},${y(p.v, lo, hi)}`).join(" ")}
                />
              )}
              {pts.map((p, idx) => (
                <circle
                  key={idx}
                  cx={x(p.x)}
                  cy={y(p.v, lo, hi)}
                  r={idx === pts.length - 1 ? 3.2 : 2}
                  className={styles.dot}
                  style={{ fill: colour }}
                />
              ))}
            </g>
          );
        })}
      </svg>
      <figcaption>
        <span>{spec.label}</span>
        <small>
          runs oldest → newest{first && last ? ` (${first.date} → ${last.date})` : ""} · {runs.length} runs
        </small>
      </figcaption>
      <small>
        {bar === undefined ? "no pass bar defined" : `pass bar ${spec.dir === "up" ? "≥" : "≤"} ${fmt(bar)} ${spec.unit}`}
        {spec.log ? " · log scale" : ""}
      </small>
      <ul className={local.legend}>
        {series.map((s) => {
          const { token, dash } = approachStyle(runs, s.approach);
          const lastPt = s.points[s.points.length - 1];
          return (
            <li key={s.approach}>
              <svg viewBox="0 0 16 6" aria-hidden="true">
                <line x1="0" y1="3" x2="16" y2="3" stroke={token} strokeWidth="2" strokeDasharray={dash} />
              </svg>
              {s.approach}
              <b>
                {fmt(lastPt.v)} {spec.unit}
              </b>
            </li>
          );
        })}
      </ul>
    </figure>
  );
}
