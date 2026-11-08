import { type AreaFacility, type AreaIndex, typeLabel } from "@/lib/showcase";

interface Props {
  area: AreaIndex;
  facility: AreaFacility | null;
  element: string | null;
  onOpenFacility: (id: string) => void;
  onUp: (level: "area" | "facility") => void;
}

export default function Rail({ area, facility, element, onOpenFacility, onUp }: Props) {
  return (
    <>
      <section className="sum glass" aria-label="Pipeline summary">
        <div className="over">Pipeline summary</div>
        Arrives in 12c.
      </section>
      <aside className="insp" aria-label="Inspector">
        {!facility && <AreaPanel area={area} onOpenFacility={onOpenFacility} />}
        {facility && !element && <FacilityPanel facility={facility} onUp={onUp} />}
        {facility && element && (
          <ElementPanel facility={facility} element={element} onUp={onUp} />
        )}
      </aside>
    </>
  );
}

function AreaPanel({
  area,
  onOpenFacility,
}: {
  area: AreaIndex;
  onOpenFacility: (id: string) => void;
}) {
  return (
    <>
      <div className="over">Area</div>
      <h2>Showcase area</h2>
      <p>
        {area.drives.length} drives · {area.facilities.length} facilities
      </p>
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
                <span className="num">{Math.round(f.observed_core * 100)}%</span>
              )}
            </button>
          </li>
        ))}
      </ul>
    </>
  );
}

function FacilityPanel({
  facility,
  onUp,
}: {
  facility: AreaFacility;
  onUp: (level: "area" | "facility") => void;
}) {
  return (
    <>
      <button type="button" className="back" onClick={() => onUp("area")}>
        ‹ Area
      </button>
      <div className="over" style={{ marginTop: 10 }}>
        {typeLabel(facility.type)} · {facility.id}
      </div>
      <h2>{facility.name}</h2>
      {facility.not_scanned_enough ? (
        <>
          <span className="tag warn">not scanned enough</span>
          <p>Under half of the core is observed. No metrics are shown for this facility.</p>
        </>
      ) : (
        <p className="num">
          {Math.round(facility.observed_core * 100)}% of core observed · {facility.runs.length}{" "}
          {facility.runs.length === 1 ? "drive" : "drives"}
        </p>
      )}
      <p>Plan metrics and elements arrive in 12c. Element view: add ?e=&lt;id&gt; to the URL.</p>
    </>
  );
}

function ElementPanel({
  facility,
  element,
  onUp,
}: {
  facility: AreaFacility;
  element: string;
  onUp: (level: "area" | "facility") => void;
}) {
  return (
    <>
      <button type="button" className="back" onClick={() => onUp("facility")}>
        ‹ {facility.name}
      </button>
      <div className="over" style={{ marginTop: 10 }}>
        Element
      </div>
      <h2>{element}</h2>
      <p>Element details arrive in 12c.</p>
    </>
  );
}
