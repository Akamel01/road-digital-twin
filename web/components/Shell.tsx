"use client";

import { useCallback, useEffect, useState, useSyncExternalStore } from "react";
import MapView from "@/components/MapView";
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

  // Esc goes up one level: element to facility, facility to area.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key !== "Escape" || isTyping(e.target) || e.metaKey || e.ctrlKey || e.altKey) return;
      if (element && facility) up("facility");
      else if (facility) up("area");
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [element, facility, up]);

  return (
    <div className="app">
      <TopBar
        areaName={AREA_NAME}
        facility={facility}
        element={element}
        onUp={up}
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
              onElement={(e) => {
                if (facility) go({ f: facility.id, e });
              }}
            />
          ) : (
            <p>Loading map…</p>
          )}
          <div className="legal">{LEGAL}</div>
        </div>
        <div className="glass strip" aria-label="Vertical profile">
          Profile strip arrives in 12c.
        </div>
      </main>
      <div className="rail">
        {area ? (
          <Rail
            area={area}
            facility={facility}
            element={element}
            onOpenFacility={(id) => go({ f: id })}
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
