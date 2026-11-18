/* eslint-disable @typescript-eslint/no-explicit-any */
import { PolygonLayer, PathLayer, ScatterplotLayer } from "@deck.gl/layers";
import { COORDINATE_SYSTEM } from "@deck.gl/core";
import { PathStyleExtension } from "@deck.gl/extensions";
import type { Tokens } from "./colors";
import { withAlpha } from "./colors";
import { overlayStyle } from "./overlayStyle";
import type { ElementKey } from "./mapdata";
import type { Point } from "./mapdata";

export type { OverlayStyle } from "./overlayStyle";
export { overlayStyle };

export interface VectorDeps {
  state: { facility: string | null };
  tokens: Tokens;
  phone: boolean;
  selectedLine: string | null;
  element: ElementKey | null;
  analysis: string | null;
  handlers?: {
    onFacility?: (id: string | null) => void;
    pickElement?: (el: ElementKey | null) => void;
    onLine?: (id: string | null) => void;
    onHover?: (obj: any) => void;
  };
}

export interface OverlayIn {
  el: ElementKey;
  closed: boolean;
  p95?: number;
  pts: Point[];
  key?: string;
}

export interface VectorLayersOptions {
  deps: VectorDeps;
  overlays?: OverlayIn[];
  facilities?: { f: { id: string }; ring: Point[] }[];
  sights?: { key: string; facId: string; s: any; el?: string }[];
  linesView?: { id: string; path?: Point[]; at: [number, number]; label?: string }[];
  facilityRing?: Point[];
}

const ext = new PathStyleExtension({ dash: true });

export function vectorLayers(opts: VectorLayersOptions | VectorDeps, ...rest: unknown[]) {
  // Allow positional call: vectorLayers(deps, overlays, facilities, sights, ...)
  let deps: VectorDeps;
  let overlays: OverlayIn[] = [];
  let facilities: { f: { id: string }; ring: Point[] }[] = [];
  let sights: { key: string; facId: string; s: unknown; el?: string }[] = [];
  let linesView: { id: string; path?: Point[]; at: [number, number]; label?: string }[] = [];
  let facilityRing: Point[] | undefined;
  if ((opts as any)?.deps) {
    const o = opts as VectorLayersOptions;
    deps = o.deps;
    overlays = o.overlays ?? [];
    facilities = o.facilities ?? [];
    sights = o.sights ?? [];
    linesView = o.linesView ?? [];
    facilityRing = o.facilityRing;
  } else {
    deps = opts as VectorDeps;
    overlays = (rest[0] as OverlayIn[]) ?? [];
    facilities = (rest[1] as any) ?? [];
    sights = (rest[2] as any) ?? [];
  }

  const { tokens, phone, selectedLine, element, state, handlers } = deps;
  const facilityLevel = state.facility !== null;
  const hitEnabled = facilityLevel;

  const closedData = overlays.filter((o) => o.closed).map((o, i) => ({
    kind: "element",
    id: o.key ?? `el-${i}`,
    el: o.el,
    closed: true,
    p95: o.p95,
    points: o.pts,
  }));
  const openData = overlays.filter((o) => !o.closed).map((o, i) => ({
    kind: "element",
    id: o.key ?? `el-${i}`,
    el: o.el,
    closed: false,
    p95: o.p95,
    points: o.pts,
  }));

  const accuracyColor = (o: any) =>
    deps.analysis === "accuracy" && o.p95 !== undefined ? (o.p95 <= 0.2 ? "#9CC7A4" : o.p95 <= 0.4 ? "#E0A94F" : "#E0704F") : null;

  const layers: any[] = [];

  // 1 overlay-closed
  layers.push(
    new PolygonLayer({
      id: "overlay-closed",
      data: closedData,
      coordinateSystem: COORDINATE_SYSTEM.CARTESIAN,
      getPolygon: (d: any) => d.points,
      getFillColor: (d: any) => {
        const st = overlayStyle(d.el, true, element === d.el, element !== null && element !== d.el, accuracyColor(d), tokens);
        return st.fill ?? [0, 0, 0, 0];
      },
      getLineColor: (d: any) => {
        const st = overlayStyle(d.el, true, element === d.el, element !== null && element !== d.el, accuracyColor(d), tokens);
        return st.color;
      },
      getLineWidth: (d: any) => {
        const st = overlayStyle(d.el, true, element === d.el, element !== null && element !== d.el, accuracyColor(d), tokens);
        return st.width;
      },
       getDashArray: (d: any) => {
         const st = overlayStyle(d.el, true, element === d.el, element !== null && element !== d.el, accuracyColor(d), tokens);
         return st.dash ?? [1, 0];
       },
       lineWidthUnits: "pixels",
       extensions: [ext],
       pickable: false,
       onClick: (info: any) => handlers?.pickElement?.(info?.object?.el ?? null),
    }),
  );

  // 2 overlay-open
  layers.push(
    new PathLayer({
      id: "overlay-open",
      data: openData,
      coordinateSystem: COORDINATE_SYSTEM.CARTESIAN,
      getPath: (d: any) => d.points,
      getColor: (d: any) => {
        const st = overlayStyle(d.el, false, element === d.el, element !== null && element !== d.el, accuracyColor(d), tokens);
        return st.color;
      },
        getWidth: (d: any) => {
          const st = overlayStyle(d.el, false, element === d.el, element !== null && element !== d.el, accuracyColor(d), tokens);
          return st.width;
        },
        getDashArray: (d: any) => {
          const st = overlayStyle(d.el, false, element === d.el, element !== null && element !== d.el, accuracyColor(d), tokens);
          return st.dash ?? [1, 0];
        },
        widthUnits: "pixels",
        dashUnits: "pixels" as any,
        extensions: [ext],
       updateTriggers: { getColor: [element, deps.analysis], getWidth: [element, deps.analysis] },
      pickable: false,
    }),
  );

  // 3 overlay-closed-hit
  layers.push(
    new PolygonLayer({
      id: "overlay-closed-hit",
      data: hitEnabled ? closedData : [],
      coordinateSystem: COORDINATE_SYSTEM.CARTESIAN,
      getPolygon: (d: any) => d.points,
       getFillColor: [0, 0, 0, 0],
       lineWidthUnits: "pixels",
       pickable: true,
       onClick: (info: any) => handlers?.pickElement?.(info?.object?.el ?? null),
       onHover: (info: any) => handlers?.onHover?.(info?.object ?? null),
     }),
   );

   // 4 overlay-open-hit
  layers.push(
    new PathLayer({
      id: "overlay-open-hit",
      data: hitEnabled ? openData : [],
      coordinateSystem: COORDINATE_SYSTEM.CARTESIAN,
      getPath: (d: any) => d.points,
      getColor: [0, 0, 0, 0],
      getWidth: 10,
      widthUnits: "pixels",
      pickable: true,
      onClick: (info: any) => handlers?.pickElement?.(info?.object?.el ?? null),
      onHover: (info: any) => handlers?.onHover?.(info?.object ?? null),
    }),
  );

  // 5 facilities
  const facData = state.facility === null ? facilities.map((f) => ({ kind: "facility", id: f.f.id, ring: f.ring })) : [];
  layers.push(
    new PolygonLayer({
      id: "facilities",
      data: facData,
      coordinateSystem: COORDINATE_SYSTEM.CARTESIAN,
      getPolygon: (d: any) => d.ring,
      getFillColor: withAlpha(tokens.fac, 18) as any,
      getLineColor: tokens.fac,
      getLineWidth: 1.4,
      lineWidthUnits: "pixels",
      getLineDashArray: [5, 4] as any,
      lineDashUnits: "pixels" as any,
      extensions: [ext],
      pickable: state.facility === null,
      onClick: (info: any) => handlers?.onFacility?.(info?.object?.id ?? null),
      onHover: (info: any) => handlers?.onHover?.(info?.object ?? null),
    }),
  );

  // 6 facility-outline
  const outlineData = facilityRing ? [{ ring: facilityRing }] : [];
  layers.push(
    new PathLayer({
      id: "facility-outline",
      data: outlineData,
      coordinateSystem: COORDINATE_SYSTEM.CARTESIAN,
      getPath: (d: any) => d.ring,
      getColor: withAlpha(tokens.fac, 0.6 * 255),
      getWidth: 1,
      widthUnits: "pixels",
      getDashArray: [3, 4],
      dashUnits: "pixels" as any,
      extensions: [ext],
      pickable: false,
    }),
  );

  // sight data
  const sightEyes: any[] = [];
  const sightPaths: any[] = [];
  for (const s of sights) {
    const ss = s.s as any;
    const eye = ss.eye ?? [0, 0];
    const end = ss.end ?? null;
    sightEyes.push({ kind: "sight", id: `eye-${s.key}`, key: s.key, facId: s.facId, el: s.el, s: ss, pos: eye });
    if (ss.status === "short" && end) {
      sightEyes.push({ kind: "sight", id: `ring-${s.key}`, key: s.key, facId: s.facId, el: s.el, s: ss, pos: end, ring: true });
    }
    const pathEnd = end ?? [eye[0], eye[1] + 50];
    sightPaths.push({ kind: "sight", id: `sight-${s.key}`, key: s.key, facId: s.facId, el: s.el, s: ss, path: [eye, pathEnd] });
  }

  // 7 sight-eyes
  layers.push(
    new ScatterplotLayer({
      id: "sight-eyes",
      data: sightEyes,
      coordinateSystem: COORDINATE_SYSTEM.CARTESIAN,
      getPosition: (d: any) => d.pos,
      getRadius: 5,
      radiusUnits: "pixels",
      getFillColor: (d: any) => (d.ring ? [0, 0, 0, 0] : tokens.sight),
      getLineColor: tokens.danger,
      getLineWidth: (d: any) => (d.ring ? 2 : 0),
      lineWidthUnits: "pixels",
      stroked: true,
      // @ts-expect-error deck types
      filled: (d: any) => !d.ring,
      pickable: false,
      onHover: (info: any) => handlers?.onHover?.(info?.object ?? null),
    }),
  );

  // 8 sight-lines (stub)
  layers.push(
    new PathLayer({
      id: "sight-lines",
      data: sightPaths,
      coordinateSystem: COORDINATE_SYSTEM.CARTESIAN,
      getPath: (d: any) => d.path,
      getColor: withAlpha(tokens.white, 179),
       getWidth: 1.4,
       widthUnits: "pixels",
       getDashArray: [2, 4],
       extensions: [ext],
      pickable: false,
    }),
  );

  // 9 sight-hits
  layers.push(
    new PathLayer({
      id: "sight-hits",
      data: hitEnabled ? sightPaths : [],
      coordinateSystem: COORDINATE_SYSTEM.CARTESIAN,
      getPath: (d: any) => d.path,
      getColor: [0, 0, 0, 0],
      getWidth: 10,
      widthUnits: "pixels",
      pickable: true,
      onClick: (info: any) => handlers?.pickElement?.(info?.object?.el ?? null),
      onHover: (info: any) => handlers?.onHover?.(info?.object ?? null),
    }),
  );

  // 10 centrelines
  const centreData = linesView;
  layers.push(
    new PathLayer({
      id: "centrelines",
      data: centreData,
      coordinateSystem: COORDINATE_SYSTEM.CARTESIAN,
      getPath: (d: any) => d.path ?? [],
      getColor: (d: any) => (selectedLine === d.id ? tokens.fac : withAlpha(tokens.white, 153)),
       getWidth: (d: any) => (selectedLine === d.id ? 2.4 : 1.2),
       widthUnits: "pixels",
       pickable: false,
     }),
   );

  // 11 centreline-hits (LAST)
  layers.push(
    new PathLayer({
      id: "centreline-hits",
      data: hitEnabled ? centreData : [],
      coordinateSystem: COORDINATE_SYSTEM.CARTESIAN,
      getPath: (d: any) => d.path ?? [],
      getColor: [0, 0, 0, 0],
      getWidth: phone ? 44 : 12,
      widthUnits: "pixels",
      pickable: true,
      onClick: (info: any) => handlers?.onLine?.(info?.object?.id ?? null),
      onHover: (info: any) => handlers?.onHover?.(info?.object ?? null),
    }),
  );

  return layers;
}
