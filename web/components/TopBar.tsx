import type { AreaFacility } from "@/lib/showcase";

// Crown mark: copied from prototypes/plan-view/index.html (CROWN). Source of truth: papyrus-home#37.
export function Crown() {
  return (
    <svg
      viewBox="0 0 64 64"
      fill="none"
      stroke="#e2a93b"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M32 61L32 28.862" strokeWidth={2.356} />
      <path
        d="M32 36.449Q31.219 32.327 27.541 30.311Q28.321 34.433 32 36.449M32 36.449Q35.679 34.433 36.459 30.311Q32.781 32.327 32 36.449"
        strokeWidth={1.456}
      />
      <path
        d="M32 28.862L15.931 17.188M32 28.862L20.325 12.793M32 28.862L25.862 9.972M32 28.862L32 9M32 28.862L38.138 9.972M32 28.862L43.675 12.793M32 28.862L48.069 17.188"
        strokeWidth={0.9}
      />
      <path
        d="M15.931 17.188L20.325 12.793L25.862 9.972L32 9L38.138 9.972L43.675 12.793L48.069 17.188"
        strokeWidth={1.456}
      />
    </svg>
  );
}

interface Props {
  areaName: string;
  facility: AreaFacility | null;
  element: string | null;
  onUp: (level: "area" | "facility") => void;
}

export default function TopBar({ areaName, facility, element, onUp }: Props) {
  return (
    <header className="top">
      <div className="brand">
        <Crown />
        Road digital twin
      </div>
      <nav className="crumbs" aria-label="Location">
        {facility ? (
          <>
            <button type="button" onClick={() => onUp("area")}>
              {areaName}
            </button>
            <i>›</i>
            {element ? (
              <>
                <button type="button" onClick={() => onUp("facility")}>
                  {facility.name}
                </button>
                <i>›</i>
                <b aria-current="location">{element}</b>
              </>
            ) : (
              <b aria-current="location">{facility.name}</b>
            )}
          </>
        ) : (
          <b aria-current="location">{areaName}</b>
        )}
      </nav>
    </header>
  );
}
