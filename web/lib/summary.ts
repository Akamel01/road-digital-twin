// Pipeline summary: the five steps, each with one headline figure. Area scope sums the drives; facility scope
// reads the facility's best drive. Missing numbers show "—" rather than a made-up value.
import { ELEMENT_NAMES, FEATURE_COUNT, type RunMetrics } from "@/lib/runmetrics";
import type { AreaFacility, AreaIndex } from "@/lib/showcase";

export interface Fig {
  value: string;
  label: string;
}

export interface Step {
  title: string;
  text: string; // what the step does, from the spec's methods
  figs: Fig[]; // figs[0] is the headline figure on the compact card
}

export const STEP_TITLES = ["Raw sweeps", "Aligned twin", "Features", "Accuracy", "Safety check"] as const;

const dash = "—";

export function fmt(v: number | null | undefined, dp: number): string {
  return v === null || v === undefined || Number.isNaN(v) ? dash : v.toFixed(dp);
}

const fmtInt = (v: number | null | undefined) => (v === null || v === undefined ? dash : Math.round(v).toLocaleString("en-US"));
const pct = (v: number | null | undefined) => (v === null || v === undefined ? dash : `${Math.round(v * 100)}%`);

function sum(values: (number | null | undefined)[]): number | null {
  const known = values.filter((v): v is number => typeof v === "number");
  return known.length ? known.reduce((a, b) => a + b, 0) : null;
}

function mean(values: number[]): number | null {
  return values.length ? values.reduce((a, b) => a + b, 0) / values.length : null;
}

export function areaSteps(area: AreaIndex, runs: Record<string, RunMetrics>): Step[] {
  const loaded = area.drives.flatMap((d) => (runs[d.run_id] ? [runs[d.run_id]] : []));
  const sweeps = sum(loaded.map((r) => r.load?.n_sweeps));
  const drifts = loaded.flatMap((r) => (typeof r.align?.xy_drift_p95_m === "number" ? [r.align.xy_drift_p95_m] : []));
  const observed = mean(area.facilities.map((f) => f.observed_core));
  const validHeight = loaded.filter((r) => r.ground?.height_valid === true).length;
  const features = (name: (typeof ELEMENT_NAMES)[number]) => sum(loaded.map((r) => r.features?.[FEATURE_COUNT[name]]));
  const worstP95 = loaded.flatMap((r) =>
    ELEMENT_NAMES.flatMap((e) => {
      const p = r.accuracy?.elements?.[e]?.p95_m;
      return p == null ? [] : [p];
    }),
  );
  const legsOf = (f: AreaFacility) => {
    const run = f.best_run ? runs[f.best_run] : undefined;
    return run?.isd?.facilities.find((x) => x.facility === f.id)?.legs ?? [];
  };
  const shortLegs = sum(area.facilities.map((f) => legsOf(f).filter((l) => l.status === "short").length));
  const facsShort = area.facilities.filter((f) => legsOf(f).some((l) => l.status === "short")).length;
  const elementsFound = sum([features("markings"), features("crosswalks"), features("curbs")]);
  const case_ = loaded.find((r) => r.isd)?.isd?.case ?? dash;

  return [
    {
      title: STEP_TITLES[0],
      text: "Moving and parked vehicles are masked out before alignment.",
      figs: [
        { value: fmtInt(sweeps), label: "sweeps" },
        { value: String(area.drives.length), label: "drives" },
      ],
    },
    {
      title: STEP_TITLES[1],
      text: "Each drive is aligned to the dataset poses. Ground heights are checked between sweeps.",
      figs: [
        { value: pct(observed), label: "core observed, mean" },
        { value: fmt(mean(drifts), 2), label: "m mean drift" },
        { value: `${validHeight}/${area.drives.length}`, label: "drives height valid" },
      ],
    },
    {
      title: STEP_TITLES[2],
      text: "Lane markings from lidar return strength, crosswalks and curbs from the height step at the road edge.",
      figs: [
        { value: fmtInt(elementsFound), label: "elements found" },
        { value: fmtInt(features("crosswalks")), label: "crosswalks" },
        { value: fmtInt(features("markings")), label: "marking runs" },
      ],
    },
    {
      title: STEP_TITLES[3],
      text: "One-way distance from each extracted element to the HD map. Curbs are map-conditioned.",
      figs: [{ value: worstP95.length ? fmt(Math.max(...worstP95), 2) : dash, label: "m P95, worst element" }],
    },
    {
      title: STEP_TITLES[4],
      text: `Sight distance per leg, AASHTO ${case_}, with and without parked vehicles.`,
      figs: [
        { value: fmtInt(shortLegs), label: "legs short" },
        { value: String(facsShort), label: "facilities with a short leg" },
      ],
    },
  ];
}

export function facilitySteps(f: AreaFacility, run: RunMetrics | undefined): Step[] {
  const notScanned = f.not_scanned_enough;
  const entry = notScanned ? undefined : run?.accuracy?.facilities?.[f.id];
  const elements = notScanned ? undefined : run?.accuracy?.elements;
  const elementsN = elements ? sum(ELEMENT_NAMES.map((e) => elements[e]?.n)) : null;
  const legs = notScanned ? [] : run?.isd?.facilities.find((x) => x.facility === f.id)?.legs ?? [];
  const short = legs.filter((l) => l.status === "short").length;
  const heightOff = run?.ground?.height_valid === false;
  const heightLine = heightOff
    ? { value: "indeterminate (height)", label: "heights disagree between sweeps" }
    : { value: fmt(run?.ground?.z_disagreement_p95_m, 3), label: "m height disagreement, P95" };

  return [
    {
      title: STEP_TITLES[0],
      text: "Every drive that passed this facility contributes sweeps.",
      figs: [
        { value: String(f.runs.length), label: f.runs.length === 1 ? "drive over this facility" : "drives over this facility" },
        { value: fmtInt(run?.load?.n_sweeps), label: "sweeps in best drive" },
      ],
    },
    {
      title: STEP_TITLES[1],
      text: heightOff
        ? "Heights disagree between sweeps, so height results are withheld."
        : "Ground heights agree between sweeps within the QA limit. Ground observed is the share of the core seen cleanly.",
      figs: [{ value: pct(f.observed_core), label: "ground observed" }, heightLine],
    },
    {
      title: STEP_TITLES[2],
      text: "Features are the elements the plan extracted from the drive.",
      figs: [{ value: fmtInt(elementsN), label: "elements found in drive" }],
    },
    {
      title: STEP_TITLES[3],
      text: "P95 distance to the HD map for this facility, from its drive.",
      figs: [{ value: fmt(entry?.p95_m, 2), label: "m P95, this facility" }],
    },
    {
      title: STEP_TITLES[4],
      text: run?.isd ? `Sight distance per leg, AASHTO ${run.isd.case}.` : "Sight distance per leg.",
      figs: [
        legs.length
          ? { value: String(short), label: `legs short of ${legs.length}` }
          : { value: dash, label: "no sight lines for this facility" },
      ],
    },
  ];
}
