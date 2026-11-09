"use client";

import { ELEMENT_LABEL, ELEMENT_NAMES, FEATURE_COUNT, methodOf, type EntryMetric, type LegMetric, type RunMetrics } from "@/lib/runmetrics";
import { typeLabel, type AreaFacility, type AreaIndex } from "@/lib/showcase";
import { fmt, type Step } from "@/lib/summary";

const FILES: [string, string][] = [
  ["Plan PDF", "plan.pdf"],
  ["Plan DXF", "plan.dxf"],
  ["Profile PDF", "profile.pdf"],
  ["Profile DXF", "profile.dxf"],
  ["LAZ", "twin.laz"],
  ["GeoJSON", "twin.geojson"],
  ["Manifest", "manifest.json"],
];

const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);
const pct = (v: number | null | undefined) => (v == null ? "—" : Math.round(v * 100));

export function LegTag({ leg, heightOff }: { leg: LegMetric; heightOff: boolean }) {
  if (leg.status === "ok") return <span className="tag ok">meets</span>;
  if (leg.status === "short") return <span className="tag bad">short</span>;
  return <span className="tag ind">{heightOff ? "indeterminate (height)" : "indeterminate"}</span>;
}

// Area level: claims from the summary's figures, facility index from 12a.
export function AreaPanel({
  area,
  name,
  steps,
  onOpenFacility,
}: {
  area: AreaIndex;
  name: string;
  steps: Step[];
  onOpenFacility: (id: string) => void;
}) {
  // Steps 2 and 4 carry the area figures: [observed, drift, valid height] and [worst P95].
  const [observed, drift, valid] = steps[1].figs;
  const worst = steps[3].figs[0];
  return (
    <>
      <div className="over">Area</div>
      <h2>{name}</h2>
      <p>
        {area.drives.length} drives · {area.facilities.length} facilities
      </p>
      <div className="lead">
        <div className="big num">
          {worst.value}
          <small> m</small>
        </div>
        <div className="sub">P95 plan error, worst element,<br />vs the nuScenes HD map</div>
      </div>
      <div className="claims num">
        <div>
          <b>{observed.value}%</b>
          <span>ground observed</span>
        </div>
        <div>
          <b>{valid.value}</b>
          <span>valid height</span>
        </div>
        <div>
          <b>{drift.value} m</b>
          <span>mean drift</span>
        </div>
        <div>
          <b>Unknown</b>
          <span>absolute georef.</span>
        </div>
      </div>
      <div className="sec over">Facilities</div>
      <ul className="idx">
        {area.facilities.map((f) => (
          <li key={f.id}>
            <button type="button" onClick={() => onOpenFacility(f.id)}>
              <span className="ty">{f.id}</span>
              <span className="nm">
                {f.name}
                <small>{typeLabel(f.type)}</small>
              </span>
              {f.not_scanned_enough ? (
                <span className="tag warn">not scanned enough</span>
              ) : (
                <span className="num">{pct(f.observed_core)}%</span>
              )}
            </button>
          </li>
        ))}
      </ul>
    </>
  );
}

// Facility level: back, height and coverage tags, accuracy table, sight-line table, downloads, jump list.
export function FacilityPanel({
  area,
  facility,
  run,
  onUp,
  onOpenFacility,
  onOpenElement,
}: {
  area: AreaIndex;
  facility: AreaFacility;
  run: RunMetrics | undefined;
  onUp: (level: "area" | "facility") => void;
  onOpenFacility: (id: string) => void;
  onOpenElement: (e: string) => void;
}) {
  const heightOff = run?.ground?.height_valid === false;
  const notScanned = facility.not_scanned_enough;
  const legs = notScanned ? [] : run?.isd?.facilities.find((x) => x.facility === facility.id)?.legs ?? [];
  const elements = notScanned ? undefined : run?.accuracy?.elements;
  const own = notScanned ? undefined : run?.accuracy?.facilities?.[facility.id];

  return (
    <>
      <button type="button" className="back" onClick={() => onUp("area")}>
        ‹ Area
      </button>
      <div className="over" style={{ marginTop: 10 }}>
        {typeLabel(facility.type)} · {facility.id}
      </div>
      <h2>{facility.name}</h2>
      <div className="chips-row">
        {notScanned ? (
          <span className="tag warn">not scanned enough</span>
        ) : run?.ground ? (
          heightOff ? (
            <span className="tag warn">indeterminate (height)</span>
          ) : (
            <span className="tag ok">height valid</span>
          )
        ) : null}
        {!notScanned && <span className="tag ind">{pct(facility.observed_core)}% observed</span>}
        {facility.type === "access_point" && <span className="tag ind">map-derived</span>}
      </div>
      {notScanned ? (
        <p>Under half of the core is observed. No metrics are shown for this facility.</p>
      ) : !run ? (
        <p>Loading drive numbers…</p>
      ) : (
        <>
          <div className="sec over">Plan accuracy vs HD map</div>
          <table className="num">
            <thead>
              <tr>
                <th>Element</th>
                <th>P50</th>
                <th>P95</th>
                <th>Cover</th>
                <th>n</th>
              </tr>
            </thead>
            <tbody>
              {ELEMENT_NAMES.map((e) => {
                const m: EntryMetric | undefined = elements?.[e];
                return (
                  <tr key={e}>
                    <td>
                      <button type="button" className="rowbtn" onClick={() => onOpenElement(e)}>
                        {ELEMENT_LABEL[e]}
                      </button>
                      <small>{m ? `${m.reference_layer}${m.label ? " · " + m.label : ""}` : "not measured"}</small>
                    </td>
                    <td>{fmt(m?.p50_m, 2)}</td>
                    <td>{fmt(m?.p95_m, 2)}</td>
                    <td>{m ? `${pct(m.coverage)}%` : "—"}</td>
                    <td>{m?.n ?? "—"}</td>
                  </tr>
                );
              })}
              {own && (
                <tr className="own">
                  <td>
                    This facility
                    <small>{`${own.reference_layer}${own.label ? " · " + own.label : ""}`}</small>
                  </td>
                  <td>{fmt(own.p50_m, 2)}</td>
                  <td>{fmt(own.p95_m, 2)}</td>
                  <td>{pct(own.coverage)}%</td>
                  <td>{own.n}</td>
                </tr>
              )}
            </tbody>
          </table>
          <p className="note">Element rows are measured over the whole drive, {facility.best_run ?? "no run"}.</p>
          {legs.length > 0 && (
            <>
              <div className="sec over">
                Sight distance · {run?.isd?.case} · {legs[0].required_m} m required
              </div>
              <table className="num">
                <thead>
                  <tr>
                    <th>Leg</th>
                    <th>Avail.</th>
                    <th>Parked</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {legs.map((l) => (
                    <tr key={l.leg}>
                      <td>
                        <button type="button" className="rowbtn" onClick={() => onOpenElement(`isd-${l.leg}`)}>
                          {cap(l.leg)}
                        </button>
                      </td>
                      <td>{l.available_m ?? "—"}</td>
                      <td>{l.available_with_parked_m ?? "—"}</td>
                      <td>
                        <LegTag leg={l} heightOff={heightOff} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}
        </>
      )}
      {facility.best_run && (
        <>
          <div className="sec over">Downloads · best drive</div>
          <div className="dls">
            {FILES.map(([label, file]) => (
              <a key={file} className="btn" href={`showcase/${facility.best_run}/${file}`} download>
                {label}
              </a>
            ))}
          </div>
        </>
      )}
      <Jump area={area} current={facility.id} onOpenFacility={onOpenFacility} />
    </>
  );
}

// Element level: the number, its chips, and the trace of the stages that produced it.
type Row = [stage: string, method: string | null, detail: string];

export function ElementPanel({
  area,
  facility,
  run,
  element,
  onUp,
  onOpenFacility,
}: {
  area: AreaIndex;
  facility: AreaFacility;
  run: RunMetrics | undefined;
  element: string;
  onUp: (level: "area" | "facility") => void;
  onOpenFacility: (id: string) => void;
}) {
  const back = (
    <button type="button" className="back" onClick={() => onUp("facility")}>
      ‹ {facility.name}
    </button>
  );
  if (!run) return <>{back}<p>Loading drive numbers…</p></>;

  const heightOff = run.ground?.height_valid === false;
  // The stages every number passes through, shared by element and sight-line traces.
  const upstream = (): Row[] => [
    ["load", methodOf(run, "load"), `${run.load?.n_sweeps ?? "—"} sweeps in this drive`],
    [
      "ground",
      methodOf(run, "ground"),
      `z disagreement P95 ${fmt(run.ground?.z_disagreement_p95_m, 3)} m · ${heightOff ? "indeterminate (height)" : "height valid"}`,
    ],
    [
      "align",
      methodOf(run, "align"),
      `xy drift P95 ${fmt(run.align?.xy_drift_p95_m, 3)} m vs dataset poses`,
    ],
  ];
  const trace = (rows: Row[]) => (
    <>
      <div className="sec over">Where this number comes from</div>
      <ol className="trace">
        {rows.map(([stage, method, detail]) => (
          <li key={stage}>
            <b>
              {stage}
              {method ? ` · ${method}` : " · not run"}
            </b>
            <span>{detail}</span>
          </li>
        ))}
      </ol>
    </>
  );

  if (element.startsWith("isd-")) {
    const isd = run.isd;
    const leg = isd?.facilities.find((x) => x.facility === facility.id)?.legs.find((l) => `isd-${l.leg}` === element);
    if (!isd || !leg) return <>{back}<p>No sight line for this element in this drive.</p></>;
    return (
      <>
        {back}
        <div className="over" style={{ marginTop: 10 }}>Sight line</div>
        <h2>{cap(leg.leg)} leg</h2>
        <div>
          <LegTag leg={leg} heightOff={heightOff} />
        </div>
        <div className="lead">
          <div className="big num">
            {leg.available_m ?? "—"}
            <small>{leg.available_m === null ? "" : " m"}</small>
          </div>
          <div className="sub">
            {leg.status === "indeterminate"
              ? `Indeterminate: ${leg.reason}`
              : `available · ${leg.available_with_parked_m ?? "—"} m with parked cars · ${leg.required_m} m required`}
          </div>
        </div>
        <div className="chips">
          <span className="chip">AASHTO {isd.case}</span>
          <span className="chip">time gap {run.params.isd.time_gap_s} s</span>
          <span className="chip">eye {run.params.isd.eye_height_m} m</span>
          <span className="chip">object {run.params.isd.object_height_m} m</span>
        </div>
        {trace([
          ["isd", methodOf(run, "isd"), `${leg.required_m} m required for ${isd.case}`],
          ["mask", methodOf(run, "mask"), `${run.mask?.n_parked ?? "—"} parked-vehicle points kept apart`],
          ...upstream(),
        ])}
        <Jump area={area} current={facility.id} onOpenFacility={onOpenFacility} />
      </>
    );
  }

  const name = ELEMENT_NAMES.find((e) => e === element);
  const m: EntryMetric | undefined = name ? run.accuracy?.elements?.[name] : undefined;
  if (!name || !m) return <>{back}<p>No accuracy numbers for this element in this drive.</p></>;
  return (
    <>
      {back}
      <div className="over" style={{ marginTop: 10 }}>Plan accuracy</div>
      <h2>{ELEMENT_LABEL[name]}</h2>
      {m.label && (
        <div>
          <span className="tag warn">{m.label}</span>
        </div>
      )}
      <div className="lead">
        <div className="big num">
          {fmt(m.p95_m, 2)}
          <small> m</small>
        </div>
        <div className="sub">
          P95 · P50 {fmt(m.p50_m, 2)} m · {pct(m.coverage)}% of reference covered
        </div>
      </div>
      <div className="chips">
        <span className="chip">ref: {m.reference_layer}</span>
        <span className="chip">{m.n} elements</span>
        <span className="chip">buffer {run.params.accuracy.buffer_m} m</span>
      </div>
      {trace([
        ["accuracy", methodOf(run, "accuracy"), `one-way distance from each extracted vertex to ${m.reference_layer}`],
        ["features", methodOf(run, "features"), `${run.features?.[FEATURE_COUNT[name]] ?? "—"} features in this drive`],
        ...upstream(),
      ])}
      <Jump area={area} current={facility.id} onOpenFacility={onOpenFacility} />
    </>
  );
}

// The jump list: every facility, the open one marked.
export function Jump({
  area,
  current,
  onOpenFacility,
}: {
  area: AreaIndex;
  current: string;
  onOpenFacility: (id: string) => void;
}) {
  return (
    <div className="jump" aria-label="Facilities">
      {area.facilities.map((f) => (
        <button
          key={f.id}
          type="button"
          title={f.name}
          aria-current={f.id === current ? "true" : undefined}
          onClick={() => onOpenFacility(f.id)}
        >
          {f.id}
        </button>
      ))}
    </div>
  );
}

export function MiniBar({ title, detail, onRestore }: { title: string; detail: string; onRestore: () => void }) {
  return (
    <button type="button" className="mini light" onClick={onRestore} aria-label={`Show details: ${title}`}>
      <div>
        <b>{title}</b>
        <br />
        <span>{detail}</span>
      </div>
      <svg viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth={1.6} aria-hidden="true">
        <path d="M3 4.5l3 3 3-3" />
      </svg>
    </button>
  );
}
