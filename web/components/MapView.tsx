"use client";

import { useEffect, useMemo, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import MapPanel, { type Analysis, type Layer, type Layers } from "@/components/MapPanel";
import {
  errCol,
  isElement,
  loadDrive,
  loadRasterMeta,
  RASTERS,
  type DriveData,
  type ElementKey,
  type FacilityGeo,
  type Point,
  type Raster,
  type RasterMeta,
} from "@/lib/mapdata";
import { sightsOf, type Sight } from "@/lib/sight";
import { typeLabel, type AreaFacility, type AreaIndex } from "@/lib/showcase";
import {
  fitView,
  frameOf,
  localRect,
  tileLevel,
  visibleTiles,
  type Frame,
  type Rect,
  type Size,
  type Tile,
  type View,
} from "@/lib/tiles";

const MAX_K = 40; // screen px per metre
const DEFAULT_LAYERS: Layers = { lidar: true, ortho: false, markings: true, crosswalks: true, curbs: true };

interface LoadedDrive {
  run: string;
  data: DriveData;
  meta: Record<Raster, RasterMeta>;
}

interface StoredView extends View {
  key: string; // the fit key the view was set under; a new fit key drops it
}

interface GeoEntry {
  geo: FacilityGeo;
  drive: LoadedDrive;
}

async function loadAll(run: string): Promise<LoadedDrive> {
  const [data, metas] = await Promise.all([
    loadDrive(run),
    Promise.all(RASTERS.map((r) => loadRasterMeta(run, r))),
  ]);
  const meta = Object.fromEntries(RASTERS.map((r, i) => [r, metas[i]])) as Record<Raster, RasterMeta>;
  return { run, data, meta };
}

const toLocal = (f: Frame, p: Point): Point => [p[0] - f.ox, f.top - p[1]];

function rectOf(pts: Point[]): Rect {
  const xs = pts.map((p) => p[0]);
  const ys = pts.map((p) => p[1]);
  return { x0: Math.min(...xs), y0: Math.min(...ys), x1: Math.max(...xs), y1: Math.max(...ys) };
}

const ptsAttr = (pts: Point[]) => pts.map(([x, y]) => `${x},${y}`).join(" ");

interface Props {
  area: AreaIndex;
  facility: AreaFacility | null;
  element: string | null;
  onFacility: (id: string) => void;
  onElement: (e: string) => void;
}

export default function MapView({ area, facility, element, onFacility, onElement }: Props) {
  const [loaded, setLoaded] = useState<LoadedDrive[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [layers, setLayers] = useState<Layers>(DEFAULT_LAYERS);
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [size, setSize] = useState<Size>({ w: 0, h: 0 });
  const [view, setView] = useState<StoredView | null>(null);
  const [fly, setFly] = useState(false);
  const [dragging, setDragging] = useState(false);
  const panRef = useRef<HTMLDivElement>(null);
  const drag = useRef<{ x: number; y: number; view: View; moved: number } | null>(null);

  const frame = useMemo(
    () => frameOf(area.drives.flatMap((d) => (d.bbox ? [d.bbox] : []))),
    [area],
  );

  useEffect(() => {
    let live = true;
    Promise.all(area.drives.map((d) => loadAll(d.run_id))).then(
      (drives) => {
        if (live) setLoaded(drives);
      },
      (e: unknown) => {
        if (live) setError(e instanceof Error ? e.message : String(e));
      },
    );
    return () => {
      live = false;
    };
  }, [area]);

  useEffect(() => {
    const el = panRef.current;
    if (!el) return;
    // Measure now, then on every change. Some browsers skip the observer's first callback.
    const measure = () => setSize({ w: el.clientWidth, h: el.clientHeight });
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // Each facility's geometry comes from its best drive (first run that has it).
  const geoIndex = useMemo(() => {
    const m = new Map<string, GeoEntry>();
    for (const f of area.facilities) {
      for (const run of [f.best_run, ...f.runs]) {
        const drive = loaded?.find((d) => d.run === run);
        const geo = drive?.data.facilities.find((g) => g.id === f.id);
        if (drive && geo) {
          m.set(f.id, { geo, drive });
          break;
        }
      }
    }
    return m;
  }, [area, loaded]);

  // The view is refit whenever the facility or the viewport size changes. A user pan or zoom
  // stores a view under the current key, so it survives until the next refit.
  const areaRect: Rect | null = frame && { x0: 0, y0: 0, x1: frame.w, y1: frame.h };
  const runRect = (run: string | null): Rect | null => {
    const b = area.drives.find((d) => d.run_id === run)?.bbox;
    return frame && b ? localRect(b, frame) : null;
  };
  const facEntry = facility ? geoIndex.get(facility.id) : undefined;
  const facRect = frame && facEntry ? rectOf(facEntry.geo.ring.map((p) => toLocal(frame, p))) : null;
  const target = facRect ?? (facility ? runRect(facility.best_run) : null) ?? areaRect;
  const fitKey = `${facility?.id ?? ""}|${size.w}x${size.h}`;
  const fitted = target && size.w && size.h ? fitView(target, size, facility ? 1.5 : 1.02, MAX_K) : null;
  const cur = view && view.key === fitKey ? view : fitted;
  const minK = areaRect && size.w && size.h ? fitView(areaRect, size, 1.02).k * 0.8 : 0;

  function commit(next: View, animate = false) {
    setFly(animate);
    setView({ ...next, key: fitKey });
    if (animate) window.setTimeout(() => setFly(false), 320);
  }

  // Wheel needs passive:false to stop the page scrolling. No deps: it re-binds with the latest view.
  useEffect(() => {
    const el = panRef.current;
    if (!el || !cur) return;
    function onWheel(e: WheelEvent) {
      e.preventDefault();
      const r = el!.getBoundingClientRect();
      const mx = e.clientX - r.left;
      const my = e.clientY - r.top;
      const k = Math.min(MAX_K, Math.max(minK, cur!.k * Math.exp(-e.deltaY * 0.0015)));
      commit({ k, tx: mx - ((mx - cur!.tx) * k) / cur!.k, ty: my - ((my - cur!.ty) * k) / cur!.k });
    }
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  });

  function zoomBy(m: number) {
    if (!cur) return;
    const cx = size.w / 2;
    const cy = size.h / 2;
    const k = Math.min(MAX_K, Math.max(minK, cur.k * m));
    commit({ k, tx: cx - ((cx - cur.tx) * k) / cur.k, ty: cy - ((cy - cur.ty) * k) / cur.k }, true);
  }

  function fitAll() {
    if (target && size.w && size.h) commit(fitView(target, size, facility ? 1.5 : 1.02, MAX_K), true);
  }

  function onPointerDown(e: ReactPointerEvent) {
    if (!cur) return;
    drag.current = { x: e.clientX, y: e.clientY, view: cur, moved: 0 };
    setDragging(true);
  }

  function onPointerMove(e: ReactPointerEvent) {
    const d = drag.current;
    if (!d) return;
    const dx = e.clientX - d.x;
    const dy = e.clientY - d.y;
    d.moved = Math.max(d.moved, Math.hypot(dx, dy));
    commit({ k: d.view.k, tx: d.view.tx + dx, ty: d.view.ty + dy });
  }

  // A press that did not move is a click. It opens a facility (area level) or selects an element (facility level).
  function onPointerUp(e: ReactPointerEvent) {
    const d = drag.current;
    drag.current = null;
    setDragging(false);
    if (!d || d.moved > 4 || !(e.target instanceof Element)) return;
    const hit = e.target.closest("[data-el],[data-fac]");
    if (!hit) return;
    const fac = hit.getAttribute("data-fac");
    if (fac && !facility) {
      onFacility(fac);
      return;
    }
    const el = hit.getAttribute("data-el");
    if (el && facility) {
      if (isElement(el)) setAnalysis("accuracy"); // the map shows the analysis behind the number
      else if (el.startsWith("isd-")) setAnalysis("safety");
      onElement(el);
    }
  }

  function toggleLayer(k: Layer) {
    setLayers((v) => ({ ...v, [k]: !v[k] }));
  }

  function pickAnalysis(a: Analysis) {
    setAnalysis((prev) => (prev === a ? null : a));
    if (a === "safety") setLayers((v) => ({ ...v, ortho: true, lidar: false }));
  }

  const dpr = typeof window === "undefined" ? 1 : window.devicePixelRatio;

  const tiles: { tile: Tile; opacity: number }[] = [];
  if (cur && frame && loaded) {
    const rasters: Raster[] = [];
    if (layers.lidar) rasters.push("lidar");
    if (layers.ortho) rasters.push("ortho");
    if (analysis === "coverage") rasters.push("coverage");
    for (const r of rasters) {
      for (const d of loaded) {
        const meta = d.meta[r];
        const rect = localRect(meta.bbox, frame);
        const z = tileLevel(cur.k, dpr, rect.x1 - rect.x0, meta.zmax);
        for (const tile of visibleTiles(r, d.run, rect, z, cur, size)) {
          tiles.push({ tile, opacity: r === "lidar" && layers.ortho ? 0.3 : 1 });
        }
      }
    }
  }

  // Vector overlays: at area level every drive, at facility level only the drives that cover it.
  const shown = loaded?.filter((d) => !facility || facility.runs.includes(d.run)) ?? [];
  const overlays =
    frame &&
    shown.flatMap((d) =>
      d.data.lines
        .filter((l) => layers[l.element])
        .map((l, i) => ({
          key: `${d.run}-${i}`,
          el: l.element,
          closed: l.closed,
          p95: d.data.p95[l.element],
          pts: ptsAttr(l.points.map((p) => toLocal(frame, p))),
        })),
    );

  function overlayStyle(el: ElementKey, closed: boolean, p95: number | undefined) {
    const sel = element === el;
    const dimmed = element !== null && !sel;
    const accuracy = analysis === "accuracy" && p95 !== undefined ? errCol(p95) : null;
    const stroke = accuracy ?? (el === "markings" ? "var(--feat-mark)" : el === "curbs" ? "var(--feat-curb)" : "var(--feat-cross)");
    let width = el === "markings" ? 1.2 : el === "curbs" ? 1.4 : 1.2;
    if (accuracy) width = 2;
    if (sel) width += closed ? 1 : 1.2;
    return {
      stroke,
      width,
      fill: closed ? stroke : "none",
      fillOpacity: closed ? (sel ? 0.35 : 0.18) : 0,
      dash: el === "curbs" && !closed ? "5 3" : undefined,
      opacity: dimmed ? 0.4 : 1,
    };
  }

  // Sight lines, from the facility's best drive. Area level draws all facilities; facility level draws its own.
  const k = cur?.k ?? 1;
  const sights: { key: string; facId: string; s: Sight }[] = [];
  if (frame && analysis === "safety") {
    for (const f of area.facilities) {
      if (facility && f.id !== facility.id) continue;
      const entry = geoIndex.get(f.id);
      if (!entry) continue;
      for (const s of sightsOf(entry.geo, entry.drive.data.legs[f.id])) {
        sights.push({ key: `${f.id}-${s.approach}`, facId: f.id, s });
      }
    }
  }

  const scaleM = cur ? [5, 10, 20, 50, 100, 200].find((v) => v * cur.k >= 60) ?? 200 : 0;

  const areaFacilities = frame
    ? area.facilities.flatMap((f) => {
        const entry = geoIndex.get(f.id);
        return entry ? [{ f, ring: entry.geo.ring.map((p) => toLocal(frame, p)) }] : [];
      })
    : [];

  return (
    <>
      <div
        ref={panRef}
        className={`pan${dragging ? " drag" : ""}`}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerLeave={() => {
          drag.current = null;
          setDragging(false);
        }}
      >
        <svg className={`world${fly ? " fly" : ""}`} width={size.w} height={size.h} aria-label="Plan map">
          {cur && frame && (
            <g style={{ transform: `translate(${cur.tx}px, ${cur.ty}px) scale(${cur.k})` }}>
              {tiles.map(({ tile, opacity }) => (
                <image
                  key={tile.url}
                  href={tile.url}
                  x={tile.left}
                  y={tile.top}
                  width={tile.w}
                  height={tile.h}
                  opacity={opacity}
                  preserveAspectRatio="none"
                />
              ))}
              {frame && (
                <>
              {!facility &&
                areaFacilities.map(({ f, ring }) => (
                  <polygon
                    key={`fac-${f.id}`}
                    className="fac"
                    data-fac={f.id}
                    points={ptsAttr(ring)}
                    stroke="var(--fac)"
                    strokeWidth={1.4}
                    strokeDasharray="5 4"
                    vectorEffect="non-scaling-stroke"
                  />
                ))}
              {!facility &&
                areaFacilities.map(({ f, ring }) => {
                  const r = rectOf(ring);
                  return (
                    <text
                      key={`lbl-${f.id}`}
                      className="flabel"
                      x={r.x0}
                      y={r.y0 - 2 / k}
                      fontSize={12 / k}
                    >
                      {`${f.id} · ${typeLabel(f.type)}`}
                    </text>
                  );
                })}
              {facility && facEntry && (
                <polygon
                  points={ptsAttr(facEntry.geo.ring.map((p) => toLocal(frame, p)))}
                  fill="none"
                  stroke="var(--fac)"
                  strokeWidth={1}
                  strokeDasharray="3 4"
                  opacity={0.6}
                  vectorEffect="non-scaling-stroke"
                />
              )}
              {overlays &&
                overlays.map((o) => {
                  const s = overlayStyle(o.el, o.closed, o.p95);
                  if (o.closed) {
                    return (
                      <polygon
                        key={o.key}
                        points={o.pts}
                        fill={s.fill}
                        fillOpacity={s.fillOpacity}
                        stroke={s.stroke}
                        strokeWidth={s.width}
                        opacity={s.opacity}
                        vectorEffect="non-scaling-stroke"
                      />
                    );
                  }
                  return (
                    <polyline
                      key={o.key}
                      points={o.pts}
                      fill="none"
                      stroke={s.stroke}
                      strokeWidth={s.width}
                      strokeDasharray={s.dash}
                      opacity={s.opacity}
                      vectorEffect="non-scaling-stroke"
                    />
                  );
                })}
              {sights.map(({ key, s }) => {
                const el = `isd-${s.approach}`;
                const sel = element === el;
                const dimmed = element !== null && !sel;
                const eye = toLocal(frame, s.eye);
                const end = s.end && toLocal(frame, s.end);
                return (
                  <g key={key} opacity={dimmed ? 0.35 : 1}>
                    <circle cx={eye[0]} cy={eye[1]} r={4 / k} fill="var(--sight)" />
                    {end ? (
                      <>
                        <line
                          x1={eye[0]}
                          y1={eye[1]}
                          x2={end[0]}
                          y2={end[1]}
                          stroke="var(--sight)"
                          strokeWidth={sel ? 2.6 : 1.5}
                          vectorEffect="non-scaling-stroke"
                        />
                        {s.status === "short" && (
                          <circle
                            cx={end[0]}
                            cy={end[1]}
                            r={5 / k}
                            fill="none"
                            stroke="var(--danger)"
                            strokeWidth={2}
                            vectorEffect="non-scaling-stroke"
                          />
                        )}
                      </>
                    ) : (
                      // Indeterminate: a dashed white stub from the eye, as in the mockup.
                      <line
                        x1={eye[0]}
                        y1={eye[1]}
                        x2={eye[0]}
                        y2={eye[1] + 50}
                        stroke="rgb(255 255 255 / .7)"
                        strokeWidth={1.4}
                        strokeDasharray="2 4"
                        vectorEffect="non-scaling-stroke"
                      />
                    )}
                    {facility && (
                      <line
                        className="hit"
                        data-el={el}
                        x1={eye[0]}
                        y1={eye[1]}
                        x2={end ? end[0] : eye[0]}
                        y2={end ? end[1] : eye[1] + 50}
                        strokeWidth={10}
                        vectorEffect="non-scaling-stroke"
                      />
                    )}
                  </g>
                );
              })}
              {facility &&
                overlays &&
                overlays.map((o) =>
                  o.closed ? (
                    <polygon key={`hit-${o.key}`} className="hitpoly" data-el={o.el} points={o.pts} />
                  ) : (
                    <polyline
                      key={`hit-${o.key}`}
                      className="hit"
                      data-el={o.el}
                      points={o.pts}
                      strokeWidth={10}
                      vectorEffect="non-scaling-stroke"
                    />
                  ),
                )}
                </>
              )}
            </g>
          )}
        </svg>
      </div>

      {frame && (
        <MapPanel
          layers={layers}
          onLayer={toggleLayer}
          analysis={analysis}
          onAnalysis={pickAnalysis}
          note={analysis === "safety" && sights.length === 0 ? "No sight lines for this view." : undefined}
        />
      )}
      {frame && (
        <div className="zoom glass">
          <button type="button" onClick={() => zoomBy(1.6)} aria-label="Zoom in">+</button>
          <button type="button" onClick={() => zoomBy(1 / 1.6)} aria-label="Zoom out">−</button>
          <button type="button" onClick={fitAll} aria-label="Fit" style={{ fontSize: 13 }}>⤢</button>
        </div>
      )}
      {cur && (
        <div className="scale">
          {scaleM} m<i style={{ width: scaleM * cur.k }} />
        </div>
      )}
      {error && <p className="msg" role="alert">{error}</p>}
      {!error && !loaded && <p className="msg">Loading tiles…</p>}
      {!frame && !error && <p className="msg">No drives in the showcase.</p>}
    </>
  );
}
