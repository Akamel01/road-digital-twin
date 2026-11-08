"use client";

import { useCallback, useEffect, useState, useSyncExternalStore } from "react";
import MapView from "@/components/MapView";
import Profile from "@/components/Profile";
import Rail from "@/components/Rail";
import TopBar from "@/components/TopBar";
import { type AreaIndex, loadArea } from "@/lib/showcase";
import { parseRoute, type Route, routeUrl } from "@/lib/route";

const AREA_NAME = "Showcase area";
const LEGAL =
  "Derived from nuScenes (CC BY-NC-SA 4.0). Street names © OpenStreetMap contributors (ODbL). Non-commercial research demo.";

// The URL is the store: the route is read from location.search on every render.
function subscribe(onChange: () => void) {
  window.addEventListener("popstate", onChange);
  return () => window.removeEventListener("popstate", onChange);
}
const getSearch = () => window.location.search;
const getServerSearch = () => "";

function isTyping(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  return target.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName);
}

export default function Shell() {
  const search = useSyncExternalStore(subscribe, getSearch, getServerSearch);
  const [area, setArea] = useState<AreaIndex | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [railCollapsed, setRailCollapsed] = useState(false); // the \ shortcut and the top-bar button
  const [sumMax, setSumMax] = useState(false); // pipeline summary maximised: the inspector shrinks to a bar

  useEffect(() => {
    loadArea().then(setArea, (e: unknown) => setError(e instanceof Error ? e.message : String(e)));
  }, []);

  // Navigate by writing the URL and notifying the store. Adds a history entry, so Back works.
  const go = useCallback((next: Route) => {
    window.history.pushState(null, "", routeUrl(next));
    window.dispatchEvent(new PopStateEvent("popstate"));
  }, []);

  // A route that names an unknown facility is treated as the area level.
  const route = parseRoute(search);
  const facility = area?.facilities.find((f) => f.id === route.f) ?? null;
  const element = facility && route.e ? route.e : null;

  const up = useCallback(
    (level: "area" | "facility") => {
      if (level === "area") go({});
      else if (facility) go({ f: facility.id });
    },
    [go, facility],
  );

  // Opening an element (from the map or the inspector) shows its numbers, so the summary shrinks back.
  const openElement = useCallback(
    (e: string) => {
      if (!facility) return;
      setSumMax(false);
      go({ f: facility.id, e });
    },
    [facility, go],
  );

  // Keys: \ toggles the rail. Esc shrinks a maximised summary first, then goes up one level
  // (element to facility, facility to area).
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (isTyping(e.target) || e.metaKey || e.ctrlKey || e.altKey) return;
      if (e.key === "\\") {
        setRailCollapsed((c) => !c);
        return;
      }
      if (e.key !== "Escape") return;
      if (sumMax) setSumMax(false);
      else if (element && facility) up("facility");
      else if (facility) up("area");
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [element, facility, up, sumMax]);

  return (
    <div className={railCollapsed ? "app collapsed" : "app"}>
      <TopBar
        areaName={AREA_NAME}
        facility={facility}
        element={element}
        onUp={up}
        railCollapsed={railCollapsed}
        onToggleRail={() => setRailCollapsed((c) => !c)}
      />
      <main className="main">
        <div className="vp" role="region" aria-label="Map">
          {error ? (
            <p role="alert">{error}</p>
          ) : area ? (
            <MapView
              area={area}
              facility={facility}
              element={element}
              onFacility={(id) => go({ f: id })}
              onElement={openElement}
            />
          ) : (
            <p>Loading map…</p>
          )}
          <div className="legal">{LEGAL}</div>
        </div>
        <div className="strip">
          <Profile facility={facility} />
        </div>
      </main>
      <div className="rail">
        {area ? (
          <Rail
            area={area}
            areaName={AREA_NAME}
            facility={facility}
            element={element}
            sumMax={sumMax}
            onSumMax={setSumMax}
            onOpenFacility={(id) => go({ f: id })}
            onOpenElement={openElement}
            onUp={up}
          />
        ) : (
          <aside className="insp">
            <p>{error ?? "Loading showcase…"}</p>
          </aside>
        )}
      </div>
    </div>
  );
}
