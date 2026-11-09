"use client";

import { useEffect, useState } from "react";
import { loadProfile, loadRunMetrics, type ProfileLine, type ProfilePoint } from "@/lib/runmetrics";
import type { AreaFacility } from "@/lib/showcase";

const W = 1000; // viewBox width; the SVG stretches to the strip
const H = 60;

interface Loaded {
  key: string; // run and facility the result belongs to
  lines?: ProfileLine[];
  heightOff?: boolean;
  error?: string;
}

/**
 * Ground z along one road line of the open facility, from its best drive. `line` is the selected line's id;
 * when it is unset or not in this facility, the first line shows. Descriptive only (spec R1).
 */
export default function Profile({ facility, line }: { facility: AreaFacility | null; line: string | null }) {
  const run = facility?.best_run ?? null;
  const fid = facility?.id ?? null;
  const [state, setState] = useState<Loaded | null>(null);

  useEffect(() => {
    if (!run || !fid) return;
    const key = `${run}|${fid}`;
    let live = true;
    Promise.all([loadRunMetrics(run), loadProfile(run, fid)]).then(
      ([m, lines]) => {
        if (live) setState({ key, lines, heightOff: m.ground?.height_valid === false });
      },
      (e: unknown) => {
        if (live) setState({ key, error: e instanceof Error ? e.message : String(e) });
      },
    );
    return () => {
      live = false;
    };
  }, [run, fid]);

  const title = facility ? `Vertical profile · ${facility.name} · descriptive` : "Vertical profile";
  if (!facility || !run || !fid) {
    return (
      <section className="prof glass">
        <div className="over">{title}</div>
        <div className="empty">Open a facility to see its vertical profile</div>
      </section>
    );
  }

  if (facility.not_scanned_enough) {
    return (
      <section className="prof glass">
        <div className="over">{title}</div>
        <div className="empty">Not scanned enough: no profile is shown for this facility</div>
      </section>
    );
  }
  const current = state && state.key === `${run}|${fid}` ? state : null;
  if (!current) {
    return (
      <section className="prof glass">
        <div className="over">{title}</div>
        <div className="empty">Loading profile…</div>
      </section>
    );
  }
  if (current.error || !current.lines) {
    return (
      <section className="prof glass">
        <div className="over">{title}</div>
        <div className="empty">No profile in this drive&apos;s bundle</div>
      </section>
    );
  }
  if (current.heightOff) {
    return (
      <section className="prof glass">
        <div className="over">{title}</div>
        <div className="empty">indeterminate (height): heights disagree between sweeps</div>
      </section>
    );
  }
  const sel = current.lines.find((l) => l.id === line) ?? current.lines[0];
  if (!sel) {
    return (
      <section className="prof glass">
        <div className="over">{title}</div>
        <div className="empty">No profile points for this facility</div>
      </section>
    );
  }
  return <Chart title={`Vertical profile · ${facility.name} · ${sel.label} · descriptive`} rows={sel.points} />;
}

function Chart({ title, rows }: { title: string; rows: ProfilePoint[] }) {
  if (rows.length < 2) {
    return (
      <section className="prof glass">
        <div className="over">{title}</div>
        <div className="empty">No profile points for this facility</div>
      </section>
    );
  }
  const s0 = rows[0].s;
  const s1 = rows[rows.length - 1].s;
  const zs = rows.map((r) => r.z);
  const zMin = Math.min(...zs);
  const zMax = Math.max(...zs);
  const span = zMax - zMin || 1;
  const X = (s: number) => 4 + ((s - s0) / (s1 - s0 || 1)) * (W - 8);
  const Y = (z: number) => H - 6 - ((z - zMin) / span) * (H - 14);
  const d = rows.map((r, i) => `${i ? "L" : "M"}${X(r.s).toFixed(1)} ${Y(r.z).toFixed(1)}`).join(" ");
  const len = s1 - s0;
  const grade = len > 0 ? ((rows[rows.length - 1].z - rows[0].z) / len) * 100 : null;
  const gradeText = grade === null ? "—" : `${grade > 0 ? "+" : ""}${grade.toFixed(1)}%`;

  return (
    <section className="prof glass">
      <div className="over">{title}</div>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        width="100%"
        height={H}
        preserveAspectRatio="none"
        role="img"
        aria-label={`Ground height along ${len.toFixed(0)} metres, ${gradeText} average grade`}
      >
        <path d={d} fill="none" stroke="#fff" strokeWidth={1.6} vectorEffect="non-scaling-stroke" />
      </svg>
      <div className="axis num">
        <span>0 m</span>
        <span>
          {len.toFixed(0)} m · avg grade {gradeText}
        </span>
      </div>
    </section>
  );
}
