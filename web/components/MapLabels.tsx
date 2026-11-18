import { memo } from "react";

export interface LabelItem {
  id: string;
  x: number;
  y: number;
  text: string;
}

function MapLabels({
  items,
  k,
  tx,
  ty,
}: {
  items: LabelItem[];
  k: number;
  tx: number;
  ty: number;
}) {
  if (!Number.isFinite(k) || !Number.isFinite(tx) || !Number.isFinite(ty)) return null;
  return (
    <svg className="labels" aria-hidden="true">
      <g transform={`translate(${tx},${ty}) scale(${k})`}>
        {items.map((it) => (
          <text
            key={it.id}
            className="flabel"
            x={it.x}
            y={it.y}
            fontSize={12 / k}
          >
            {it.text}
          </text>
        ))}
      </g>
    </svg>
  );
}

export default memo(MapLabels);
