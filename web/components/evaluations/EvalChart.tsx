import {
  approachStyle,
  type EvalRun,
  type Headline,
  seriesByApproach,
  yDomain,
  axisTicks,
  fmtValue,
  dirText,
  METRIC_INFO,
} from "@/lib/evaluations";
import local from "./evaluations.module.css";

const W = 720;
const H = 280;
const M = { top: 24, right: 40, bottom: 44, left: 88 };

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

  const info = METRIC_INFO[spec.key];
  const ticks = domain ? axisTicks(domain.lo, domain.hi, spec.log) : [];

  const x = (i: number) =>
    runs.length < 2 ? (W - M.left - M.right) / 2 + M.left : M.left + (i / (runs.length - 1)) * (W - M.left - M.right);
  const y = (v: number, lo: number, hi: number) =>
    M.top + (H - M.top - M.bottom) - ((spec.log ? Math.log10(v) : v) - (spec.log ? Math.log10(lo) : lo)) / ((spec.log ? Math.log10(hi) : hi) - (spec.log ? Math.log10(lo) : lo)) * (H - M.top - M.bottom);

  if (series.length === 0 || domain === null) {
    return (
      <figure className={local.chart}>
        <figcaption className={local.chartTitle}>{info.name} · {dirText(info.dir)}</figcaption>
        <p className={local.chartNote}>not measured</p>
      </figure>
    );
  }

  const { lo, hi } = domain;
  const ariaLabel = `${info.name} by run (oldest → newest): ${series.length} approaches, ${bar === undefined ? "no pass bar defined" : `pass bar ${spec.dir === "up" ? "≥" : "≤"} ${fmtValue(spec.key, bar)} ${spec.unit}`}, ${spec.log ? "log" : "linear"} scale`;

  return (
    <figure className={local.chart}>
      <figcaption className={local.chartCaption}>
        <span className={local.chartTitle}>{info.name} · {dirText(info.dir)}</span>
        <small className={local.chartMeaning}>{info.meaning}</small>
        <small className={local.chartMeta}>
          {bar === undefined ? "no pass bar defined" : `bar ${fmtValue(spec.key, bar)} ${spec.unit}`} · {spec.log ? "log scale" : "linear scale"} · runs oldest → newest
        </small>
      </figcaption>
      <svg className={local.chartSvg} viewBox={`0 0 ${W} ${H}`} role="img" aria-label={ariaLabel}>
        {ticks.map((t, i) => (
          <g key={i}>
            <line x1={M.left} x2={W - M.right} y1={y(t, lo, hi)} y2={y(t, lo, hi)} className={local.gridLine} />
            <text x={M.left - 6} y={y(t, lo, hi) + 3} textAnchor="end" className={local.axisText}>
              {fmtValue(spec.key, t)}
              {spec.unit ? ` ${spec.unit}` : ""}
            </text>
          </g>
        ))}
        {bar !== undefined && (
          <g>
            <line x1={M.left} x2={W - M.right} y1={y(bar, lo, hi)} y2={y(bar, lo, hi)} className={local.barLine} />
            <text x={W - M.right} y={y(bar, lo, hi) - 4} textAnchor="end" className={local.barLabel}>
              bar {fmtValue(spec.key, bar)} {spec.unit}
            </text>
          </g>
        )}
        {series.map((s) => {
          const { token: colour, dash } = approachStyle(runs, s.approach);
          const pts = s.points;
          return (
            <g key={s.approach}>
              {pts.length >= 2 && (
                <polyline
                  className={local.seriesLine}
                  style={{ stroke: colour, strokeDasharray: dash }}
                  points={pts.map((p) => `${x(p.x)},${y(p.v, lo, hi)}`).join(" ")}
                />
              )}
              {pts.map((p, idx) => (
                <circle
                  key={idx}
                  cx={x(p.x)}
                  cy={y(p.v, lo, hi)}
                  r={idx === pts.length - 1 ? 4 : 3}
                  className={local.seriesDot}
                  style={{ fill: colour }}
                >
                  <title>{runs[p.x]?.date}</title>
                </circle>
              ))}
            </g>
          );
        })}
        {runs.map((r, i) => (
          <g key={r.id}>
            <line x1={x(i)} x2={x(i)} y1={H - M.bottom} y2={H - M.bottom + 4} className={local.tick} />
            <text x={x(i)} y={H - M.bottom + 16} textAnchor="middle" className={local.axisText}>
              {r.date.slice(5)}
              <title>{r.date}</title>
            </text>
          </g>
        ))}
      </svg>
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
                {fmtValue(spec.key, lastPt.v)} {spec.unit}
              </b>
            </li>
          );
        })}
      </ul>
      <small className={local.chartMeta}>oldest → newest</small>
    </figure>
  );
}
