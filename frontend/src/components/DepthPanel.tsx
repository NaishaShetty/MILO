// DepthPanel.tsx
//
// Purpose
// -------
// Displays the depth colormap view alongside the RGB camera view (the
// project's "RGB View and Depth View" requirement), with an explicit
// legend -- never implying colors mean a physical distance without
// stating the scale (`backend/vision/visualization/depth_visualizer.py`
// computes `min_depth_m`/`max_depth_m` fresh per frame; this component
// only displays what it's given). Renders nothing (not a placeholder)
// when depth was unavailable this frame, since "no depth panel" is a
// clearer signal than an empty/greyed-out one for a feature that simply
// isn't configured (e.g. no depth stage in the pipeline).
import type { DepthLegend } from "../api/visionTypes";

interface DepthPanelProps {
  imageBase64: string | null;
  legend: DepthLegend | null;
}

export function DepthPanel({ imageBase64, legend }: DepthPanelProps) {
  if (!imageBase64 || !legend) {
    return null;
  }

  return (
    <div className="depth-panel">
      <h2 className="depth-panel__title">Depth</h2>
      <img
        className="depth-panel__image"
        src={`data:image/png;base64,${imageBase64}`}
        alt="Depth colormap of the current scene"
      />
      <p className="depth-panel__legend">
        <span className="depth-panel__legend-swatch depth-panel__legend-swatch--near" />
        {legend.near_is} = {legend.min_depth_m.toFixed(2)}
        <span className="depth-panel__legend-spacer" />
        <span className="depth-panel__legend-swatch depth-panel__legend-swatch--far" />
        far = {legend.max_depth_m.toFixed(2)}
        <span className="depth-panel__legend-colormap"> ({legend.colormap_name})</span>
      </p>
    </div>
  );
}
