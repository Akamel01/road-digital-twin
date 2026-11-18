"use client";

import { useEffect, useMemo, useState } from "react";
import { DeckGL } from "@deck.gl/react";
import { OrthographicView } from "@deck.gl/core";
import type { Layer } from "@deck.gl/core";
import type { ViewState } from "@/lib/tiles";

export default function MapCanvas(p: {
  viewState: ViewState;
  layers: Layer[];
  onViewStateChange: (v: ViewState) => void;
  onError?: (e: Error) => void;
}) {
  const [ok, setOk] = useState<boolean | null>(null);
  useEffect(() => {
    const c = document.createElement("canvas");
    const gl = c.getContext("webgl2");
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setOk(!!gl);
    gl?.getExtension("WEBGL_lose_context")?.loseContext();
  }, []);
  const views = useMemo(() => [new OrthographicView({ id: "ortho", flipY: true })], []);
  if (ok === null) return null;
  if (!ok) return <p className="msg" role="alert">This map needs WebGL 2.</p>;
  return (
    <DeckGL
      views={views}
      viewState={p.viewState as never}
      controller={{
        dragPan: true,
        dragRotate: false,
        touchZoom: true,
        doubleClickZoom: false,
        inertia: false,
        scrollZoom: { smooth: false },
      }}
      getCursor={({ isDragging, isHovering }) =>
        isDragging ? "grabbing" : isHovering ? "pointer" : "grab"
      }
      layers={p.layers}
       onViewStateChange={({ viewState: v }) => {
          p.onViewStateChange(v as ViewState);
        }}
      onError={(e) => p.onError?.(e)}
    />
  );
}
