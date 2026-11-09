"use client";

import { useEffect, useState, type ReactNode } from "react";
import Summary from "@/components/Summary";
import SheetHead, { type Sheet } from "@/components/SheetHead";
import { AreaPanel, ElementPanel, FacilityPanel, MiniBar } from "@/components/Inspector";
import { loadRunMetrics, type RunMetrics } from "@/lib/runmetrics";
import { type AreaFacility, type AreaIndex, typeLabel } from "@/lib/showcase";
import { areaSteps, facilitySteps } from "@/lib/summary";

interface Props {
  area: AreaIndex;
  areaName: string;
  facility: AreaFacility | null;
  element: string | null;
  sumMax: boolean;
  onSumMax: (on: boolean) => void;
  onOpenFacility: (id: string) => void;
  onOpenElement: (e: string) => void;
  onUp: (level: "area" | "facility") => void;
  phone: boolean; // phone: this column is the bottom sheet, with its peek line on top and the profile strip under the inspector
  sheet: Sheet;
  onSheet: (s: Sheet) => void;
  profile: ReactNode;
}

// The right column: the pipeline summary card, then the inspector (or a bar when the summary is maximised).
// On tablet and desktop it is the side panel. On phone the same parts stack inside the bottom sheet.
export default function Rail({
  area,
  areaName,
  facility,
  element,
  sumMax,
  onSumMax,
  onOpenFacility,
  onOpenElement,
  onUp,
  phone,
  sheet,
  onSheet,
  profile,
}: Props) {
  // Every drive's manifest, loaded once. A drive that fails to load leaves its numbers as "—".
  const [runs, setRuns] = useState<Record<string, RunMetrics>>({});
  useEffect(() => {
    let live = true;
    Promise.allSettled(area.drives.map((d) => loadRunMetrics(d.run_id))).then((results) => {
      if (!live) return;
      const out: Record<string, RunMetrics> = {};
      results.forEach((r, i) => {
        if (r.status === "fulfilled") out[area.drives[i].run_id] = r.value;
      });
      setRuns(out);
    });
    return () => {
      live = false;
    };
  }, [area]);

  const best = facility?.best_run ? runs[facility.best_run] : undefined;
  const steps = facility ? facilitySteps(facility, best) : areaSteps(area, runs);

  const summary = (
    <Summary
      scope={facility ? facility.id : "area"}
      steps={steps}
      expanded={sumMax}
      onExpanded={onSumMax}
    />
  );

  // The peek line shows the same headline figure as the summary's step 4: P95 accuracy.
  const head = phone ? (
    <SheetHead title={facility ? facility.name : areaName} figure={steps[3].figs[0]} sheet={sheet} onSheet={onSheet} />
  ) : null;

  if (sumMax) {
    return (
      <>
        {head}
        {summary}
        <MiniBar
          title={facility ? facility.name : areaName}
          detail={facility ? `${typeLabel(facility.type)} · ${element ? "element details" : "facility details"}` : `${area.facilities.length} facilities · area details`}
          onRestore={() => onSumMax(false)}
        />
        {profile}
      </>
    );
  }

  return (
    <>
      {head}
      {summary}
      <aside className="insp light" aria-label="Inspector">
        {!facility && (
          <AreaPanel area={area} name={areaName} steps={steps} onOpenFacility={onOpenFacility} />
        )}
        {facility && !element && (
          <FacilityPanel
            area={area}
            facility={facility}
            run={best}
            onUp={onUp}
            onOpenFacility={onOpenFacility}
            onOpenElement={onOpenElement}
          />
        )}
        {facility && element && (
          <ElementPanel
            area={area}
            facility={facility}
            run={best}
            element={element}
            onUp={onUp}
            onOpenFacility={onOpenFacility}
          />
        )}
      </aside>
      {profile}
    </>
  );
}
