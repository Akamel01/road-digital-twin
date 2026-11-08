"use client";

import { useEffect, useState } from "react";
import Summary from "@/components/Summary";
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
}

// The right column: the pipeline summary card, then the inspector (or a bar when the summary is maximised).
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

  if (sumMax) {
    return (
      <>
        {summary}
        <MiniBar
          title={facility ? facility.name : areaName}
          detail={facility ? `${typeLabel(facility.type)} · ${element ? "element details" : "facility details"}` : `${area.facilities.length} facilities · area details`}
          onRestore={() => onSumMax(false)}
        />
      </>
    );
  }

  return (
    <>
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
    </>
  );
}
