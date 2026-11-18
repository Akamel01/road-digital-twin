export interface ToolbarButton {
  id: string;
  label: string;
}

export const MODE_BUTTONS: ToolbarButton[] = [
  { id: "select", label: "select" },
  { id: "point", label: "point" },
  { id: "line", label: "line" },
  { id: "polygon", label: "polygon" },
];

export const LAYER_BUTTONS: ToolbarButton[] = [
  { id: "height", label: "height" },
  { id: "lidar", label: "lidar" },
  { id: "ortho", label: "ortho" },
];
