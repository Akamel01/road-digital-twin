"use client";

import { useEffect, useMemo, useRef, useState, useCallback } from "react";

let __mvRenders = 0;
function bumpRender() {
  __mvRenders++;
  if (typeof window !== "undefined") (window as Window & { __renders?: number }).__renders = __mvRenders;
}
import dynamic from "next/dynamic";
import MapPanel, { type Analysis, type Layer, type Layers } from "@/components/MapPanel";
import MapLabels, { type LabelItem } from "@/components/MapLabels";
import {
  type Centreline,
  isElement,
  loadCentrelines,
  loadDrive,
  type DriveData,
  type ElementKey,
  type FacilityGeo,
  type Point,
  type Raster,
} from "@/lib/mapdata";
import { sightsOf, type Sight } from "@/lib/sight";
import { typeLabel, type AreaFacility, type AreaIndex, type FacilityType } from "@/lib/showcase";
import { PHONE, useMedia } from "@/lib/media";
import {
  fitState,
  frameOf,
  localRect,
  minZoomOf,
  viewOf,
  viewStateOf,
  type Frame,
  type Rect,
  type Size,
  type View,
  type ViewState,
  MAX_K,
  MAX_VIEW_ZOOM,
} from "@/lib/tiles";
import { loadMosaics, loadTileVersion, mosaicFrame, type MosaicMeta } from "@/lib/mosaic";
import { DEFAULT_LAYERS, applyTrioToggle, applySafetyLayers, rastersFor } from "@/lib/layers";
import { FALLBACK_TOKENS, readTokens, type Tokens } from "@/lib/colors";
import { tileLayers } from "@/lib/deckTiles";
import { vectorLayers, type OverlayIn } from "@/lib/deckVectors";

const MapCanvas = dynamic(() => import("@/components/MapCanvas"), { ssr: false });

const LABEL_ZOOM_THRESHOLD = 4;
const TYPE_RANK: Record<FacilityType, number> = { intersection: 0, segment: 1, access_point: 2 };

interface LoadedDrive {
  run: string;
  data: DriveData;
}

interface StoredView extends View {
  key: string;
}

interface GeoEntry {
  geo: FacilityGeo;
  drive: LoadedDrive;
}

const toLocal = (f: Frame, p: Point): Point => [p[0] - f.ox, f.top - p[1]];

function rectOf(pts: Point[]): Rect {
  const xs = pts.map((p) => p[0]);
  const ys = pts.map((p) => p[1]);
  return { x0: Math.min(...xs), y0: Math.min(...ys), x1: Math.max(...xs), y1: Math.max(...ys) };
}

function clamp(n: number, lo: number, hi: number): number {
  return Math.min(hi, Math.max(lo, n));
}

function labelAt(pts: Point[], r: Rect | null): Point {
  if (!pts.length) return [0, 0];
  if (!r) return pts[Math.floor(pts.length / 2)];
  const cx = (r.x0 + r.x1) / 2;
  const cy = (r.y0 + r.y1) / 2;
  let best = pts[0];
  let bestD = Infinity;
  for (const p of pts) {
    const px = clamp(p[0], r.x0, r.x1);
    const py = clamp(p[1], r.y0, r.y1);
    const dx = px - cx;
    const dy = py - cy;
    const d = dx * dx + dy * dy;
    if (d < bestD) {
      bestD = d;
      best = [px, py];
    }
  }
  return best;
}

function openRing(pts: Point[]): Point[] {
  if (pts.length > 1) {
    const a = pts[0];
    const b = pts[pts.length - 1];
    if (a[0] === b[0] && a[1] === b[1]) return pts.slice(0, -1);
  }
  return pts;
}

interface Props {
  area: AreaIndex;
  facility: AreaFacility | null;
  element: string | null;
  line: string | null;
  onFacility: (id: string) => void;
  onElement: (e: string) => void;
  onLine: (id: string) => void;
}

export default function MapView({ area, facility, element, line, onFacility, onElement, onLine }: Props) {
  bumpRender();
  const phone = useMedia(PHONE);
  const [mosaic, setMosaic] = useState<{ metas: Record<Raster, MosaicMeta>; frame: Frame } | null>(null);
  const [version, setVersion] = useState("");
  const [tokens, setTokens] = useState<Tokens>(FALLBACK_TOKENS);
  const [loaded, setLoaded] = useState<LoadedDrive[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [layers, setLayers] = useState<Layers>(DEFAULT_LAYERS);
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [size, setSize] = useState<Size>({ w: 0, h: 0 });
  const [view, setView] = useState<StoredView | null>(null);
  const panRef = useRef<HTMLDivElement>(null);
  const [centre, setCentre] = useState<{ key: string; lines: Centreline[] } | null>(null);
  const pendingView = useRef<StoredView | null>(null);
  const viewRaf = useRef<number | null>(null);

  const frame = mosaic?.frame ?? null;

  // Load mosaics + drives
  useEffect(() => {
    let live = true;
    (async () => {
      try {
        const [metas, v, drives] = await Promise.all([
          loadMosaics(),
          loadTileVersion(),
          Promise.all(area.drives.map((d) => loadDrive(d.run_id).then((data) => ({ run: d.run_id, data })))),
        ]);
        const fr = mosaicFrame(metas);
        if (!fr) throw new Error("showcase mosaic has no bbox");
        if (!live) return;
        setMosaic({ metas, frame: fr });
        setVersion(v);
        setLoaded(drives);
      } catch (e) {
        if (live) setError(e instanceof Error ? e.message : String(e));
      }
    })();
    return () => {
      live = false;
    };
  }, [area]);

  useEffect(() => {
    const el = panRef.current;
    if (!el) return;
    const measure = () => setSize({ w: el.clientWidth, h: el.clientHeight });
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (typeof window !== "undefined") setTokens(readTokens());
  }, []);

  useEffect(() => {
    return () => {
      if (viewRaf.current !== null) cancelAnimationFrame(viewRaf.current);
    };
  }, []);

  const clRun = facility?.best_run ?? null;
  const clFid = facility?.id ?? null;
  useEffect(() => {
    if (!clRun || !clFid) return;
    const key = `${clRun}|${clFid}`;
    let live = true;
    loadCentrelines(clRun, clFid).then(
      (lines) => {
        if (live) setCentre({ key, lines });
      },
      () => {
        if (live) setCentre({ key, lines: [] });
      },
    );
    return () => {
      live = false;
    };
  }, [clRun, clFid]);

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

  const shown = useMemo(
    () => loaded?.filter((d) => !facility || facility.runs.includes(d.run)) ?? [],
    [loaded, facility],
  );

  const areaFacilities = useMemo(
    () =>
      frame
        ? area.facilities.flatMap((f) => {
            const entry = geoIndex.get(f.id);
            return entry ? [{ f, ring: entry.geo.ring.map((p) => toLocal(frame, p)) }] : [];
          })
        : [],
    [frame, area, geoIndex],
  );

  const union = useMemo(() => frameOf(area.drives.flatMap((d) => (d.bbox ? [d.bbox] : []))), [area]);
  const areaRect: Rect | null =
    frame && union
      ? localRect([union.ox, union.top - union.h, union.ox + union.w, union.top], frame)
      : null;

  const runRect = useCallback(
    (run: string | null): Rect | null => {
      const b = area.drives.find((d) => d.run_id === run)?.bbox;
      return frame && b ? localRect(b, frame) : null;
    },
    [area, frame],
  );

  const facEntry = facility ? geoIndex.get(facility.id) : undefined;
  const facRect = useMemo(
    () => (frame && facEntry ? rectOf(facEntry.geo.ring.map((p) => toLocal(frame, p))) : null),
    [frame, facEntry],
  );

  const target = facRect ?? (facility ? runRect(facility.best_run) : null) ?? areaRect;
  const fitKey = `${facility?.id ?? ""}|${size.w}x${size.h}`;
  const fitted = target && size.w && size.h ? fitState(target, size, facility ? 1.5 : 1.02, MAX_K) : null;
  const fittedView = fitted ? viewOf(fitted, size) : null;
  const cur = (view && view.key === fitKey ? view : fittedView) as View | null;
  const minZoom = areaRect && size.w && size.h ? minZoomOf(areaRect, size) : 0;

  function zoomBy(m: number) {
    if (!cur) return;
    const cx = size.w / 2;
    const cy = size.h / 2;
    const k = Math.min(MAX_K, Math.max(2 ** minZoom, cur.k * m));
    setView({ k, tx: cx - ((cx - cur.tx) * k) / cur.k, ty: cy - ((cy - cur.ty) * k) / cur.k, key: fitKey });
  }

  function fitAll() {
    if (target && size.w && size.h) {
      const vs = fitState(target, size, facility ? 1.5 : 1.02, MAX_K);
      const vv = viewOf(vs, size);
      setView({ k: vv.k, tx: vv.tx, ty: vv.ty, key: fitKey });
    }
  }

  function pickAnalysis(a: Analysis) {
    if (a === "safety") {
      setAnalysis((prev) => {
        if (prev === "safety") return null;
        setLayers((v) => applySafetyLayers(v));
        return "safety";
      });
      return;
    }
    setAnalysis((prev) => (prev === a ? null : a));
  }

  const toggleLayer = useCallback((k: Layer) => {
    setLayers((v) => applyTrioToggle(v, k));
  }, []);

  const pickElement = useCallback(
    (el: string | null) => {
      if (!el) return;
      if (isElement(el)) setAnalysis("accuracy");
      else if (el.startsWith("isd-")) {
        setAnalysis("safety");
        setLayers((v) => applySafetyLayers(v));
      }
      onElement(el);
    },
    [onElement],
  );

  const onHover = useCallback((obj: { kind: string; id: string } | null) => {
    if (panRef.current) panRef.current.style.cursor = obj ? "pointer" : "";
  }, []);

  const dpr = typeof window === "undefined" ? 1 : window.devicePixelRatio;

  // Adapters
  const overlays: OverlayIn[] = useMemo(() => {
    if (!frame) return [];
    return shown.flatMap((d) =>
      d.data.lines
        .filter((l) => layers[l.element])
        .map((l, i) => ({
          key: `${d.run}-${i}`,
          el: l.element,
          closed: l.closed,
          p95: d.data.p95[l.element],
          pts: l.points.map((p) => toLocal(frame, p)),
        })),
    );
  }, [frame, shown, layers]);

  // sights
  const sightsRaw = useMemo(() => {
    if (!frame || analysis !== "safety") return [];
    const out: { key: string; s: Sight }[] = [];
    for (const f of area.facilities) {
      if (facility && f.id !== facility.id) continue;
      const entry = geoIndex.get(f.id);
      if (!entry) continue;
      for (const s of sightsOf(entry.geo, entry.drive.data.legs[f.id])) {
        out.push({ key: `${f.id}-${s.approach}-${s.side}`, s });
      }
    }
    return out;
  }, [frame, analysis, area, facility, geoIndex]);

  const sights = useMemo(
    () =>
      frame
        ? sightsRaw.map(({ key, s }) => ({
            key,
            el: `isd-${s.approach}`,
            eye: toLocal(frame, s.eye),
            end: s.end ? toLocal(frame, s.end) : null,
            status: s.status,
          }))
        : [],
    [sightsRaw, frame],
  );

  const facilityRingLocal = useMemo(
    () => (frame && facEntry ? facEntry.geo.ring.map((p) => toLocal(frame, p)) : null),
    [frame, facEntry],
  );
  const facilityOutline = useMemo(
    () => (facilityRingLocal ? openRing(facilityRingLocal) : null),
    [facilityRingLocal],
  );

  const clKey = `${clRun}|${clFid}`;
  const lines = useMemo(
    () => (facility && frame && centre?.key === clKey ? centre.lines : []),
    [facility, frame, centre, clKey],
  );
  const selId = lines.find((l) => l.id === line)?.id ?? lines[0]?.id ?? null;
  const linesView = useMemo(
    () =>
      facility && frame
        ? lines.map((l) => {
            const pts = l.points.map((p) => toLocal(frame, p));
            return { id: l.id, label: l.label, points: l.points, pts, at: labelAt(pts, facRect) };
          })
        : [],
    [facility, frame, lines, facRect],
  );

  const rasters = useMemo(() => rastersFor(layers, analysis), [layers, analysis]);

  const deckLayers = useMemo(() => {
    if (!mosaic || !loaded) return [];
    return [
      ...tileLayers({ metas: mosaic.metas, rasters, version, dpr }),
      // eslint-disable-next-line react-hooks/refs
      ...vectorLayers({
        deps: {
          state: { facility: facility?.id ?? null },
          tokens,
          phone,
          selectedLine: selId,
          element: element as ElementKey | null,
          analysis,
          handlers: {
            onFacility: onFacility as (id: string | null) => void,
            pickElement: pickElement as (el: ElementKey | null) => void,
            onLine: onLine as (id: string | null) => void,
            onHover,
          },
        },
        overlays,
        facilities: areaFacilities.map(({ f, ring }) => ({ f: { id: f.id }, ring })),
        sights: sights.map((s) => ({
          key: s.key,
          facId: facility?.id ?? "",
          el: s.el,
          s: { eye: s.eye, end: s.end, status: s.status },
        })),
        linesView: linesView.map((l) => ({ id: l.id, path: l.pts, at: l.at, label: l.label })),
        facilityRing: facilityOutline ?? undefined,
      }),
    ];
  }, [
    mosaic,
    loaded,
    rasters,
    version,
    dpr,
    overlays,
    facilityOutline,
    linesView,
    selId,
    sights,
    tokens,
    element,
    analysis,
    facility,
    phone,
    areaFacilities,
    onFacility,
    pickElement,
    onLine,
    onHover,
  ]);

  const sv = cur;
  const labelK = sv ? Math.round(sv.k * 100) / 100 : 1;
  const labelTx = sv ? Math.round(sv.tx) : 0;
  const labelTy = sv ? Math.round(sv.ty) : 0;
  const labelItems: LabelItem[] = useMemo(() => {
    const zoom = labelK;
    const items: LabelItem[] = [];
    const emitted: { x0: number; y0: number; x1: number; y1: number }[] = [];
    const charW = 7 / labelK;
    const charH = 12 / labelK;

    if (!facility) {
      const sorted = [...areaFacilities].sort((a, b) => {
        const ra = TYPE_RANK[a.f.type] ?? 9;
        const rb = TYPE_RANK[b.f.type] ?? 9;
        if (ra !== rb) return ra - rb;
        return a.f.id < b.f.id ? -1 : a.f.id > b.f.id ? 1 : 0;
      });
      for (const { f, ring } of sorted) {
        if (f.type !== "intersection" && zoom < LABEL_ZOOM_THRESHOLD) continue;
        const r = rectOf(ring);
        const text = phone ? f.id : `${f.id} · ${typeLabel(f.type)}`;
        const x = r.x0;
        const y = r.y0 - 2 / labelK;
        const box = { x0: x, y0: y - charH, x1: x + text.length * charW, y1: y };
        const overlaps = emitted.some((b) => !(box.x1 < b.x0 || box.x0 > b.x1 || box.y1 < b.y0 || box.y0 > b.y1));
        if (overlaps) continue;
        emitted.push(box);
        items.push({ id: `lbl-${f.id}`, x, y, text });
      }
    }

    if (facility) {
      for (const l of linesView) {
        const text = l.label ?? l.id;
        const x = l.at[0] + 4 / labelK;
        const y = l.at[1] - 4 / labelK;
        const box = { x0: x, y0: y - charH, x1: x + text.length * charW, y1: y };
        const overlaps = emitted.some((b) => !(box.x1 < b.x0 || box.x0 > b.x1 || box.y1 < b.y0 || box.y0 > b.y1));
        if (overlaps) continue;
        emitted.push(box);
        items.push({ id: `cll-${l.id}`, x, y, text });
      }
    }
    return items;
  }, [facility, areaFacilities, linesView, labelK, phone]);

  const scaleM = cur ? [5, 10, 20, 50, 100, 200].find((v) => v * cur.k >= 60) ?? 200 : 0;

  const handleViewStateChange = useCallback(
    (v: ViewState) => {
      if (!v || !Number.isFinite(v.zoom) || !size.w || !size.h) return;
      const z = Math.min(MAX_VIEW_ZOOM, Math.max(minZoom, v.zoom));
      const t0 = v.target?.[0];
      const t1 = v.target?.[1];
      if (!Number.isFinite(t0) || !Number.isFinite(t1)) return;
      const vv = viewOf({ target: [t0, t1, 0], zoom: z }, size);
      if (!Number.isFinite(vv.k) || !Number.isFinite(vv.tx) || !Number.isFinite(vv.ty)) return;
      pendingView.current = { k: vv.k, tx: vv.tx, ty: vv.ty, key: fitKey };
      if (viewRaf.current === null) {
        viewRaf.current = requestAnimationFrame(() => {
          viewRaf.current = null;
          if (pendingView.current) setView(pendingView.current);
        });
      }
    },
    [minZoom, size, fitKey],
  );

  const deckViewState: ViewState | null = cur ? viewStateOf(cur as unknown as View, size) : null;
  const ready = !!mosaic && loaded !== null;
  const noData = ready && (!frame || area.drives.length === 0);

  return (
    <>
      <div
        ref={panRef}
        className="pan"
        data-centreline-count={linesView.length}
        data-label-count={labelItems.length}
        data-facility-count={areaFacilities.length}
      >
        <div className="gl" role="img" aria-label="Plan map">
          {cur && deckViewState && size.w > 0 && size.h > 0 && Number.isFinite(cur.k) && Number.isFinite(cur.tx) && Number.isFinite(cur.ty) && (
            <MapCanvas
              viewState={deckViewState}
              layers={deckLayers}
              onViewStateChange={handleViewStateChange}
              onError={(e) => setError(e.message)}
            />
          )}
        </div>
        {cur && sv && Number.isFinite(sv.k) && Number.isFinite(sv.tx) && Number.isFinite(sv.ty) && <MapLabels items={labelItems} k={labelK} tx={labelTx} ty={labelTy} />}
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
      {layers.height && (
        <div className="heightlegend glass" aria-label="Height legend">
          <div className="over">Height above road surface</div>
          <div className="hramp" role="img" aria-label="0 to 25 plus centimeters ramp" />
          <div className="hticks">
            <span>0</span>
            <span>5</span>
            <span>10</span>
            <span>15</span>
            <span>20</span>
            <span>25+ cm</span>
          </div>
          <p className="hnote">Curb = sharp step from blue/teal (road) to yellow/white (sidewalk, 10–15 cm)</p>
        </div>
      )}
      {error && <p className="msg" role="alert">{error}</p>}
      {!error && !ready && <p className="msg">Loading tiles…</p>}
      {!error && noData && <p className="msg">No drives in the showcase.</p>}
    </>
  );
}
