// PerceptionStatusPanel.tsx
//
// Purpose
// -------
// Renders the "PERCEPTION" status summary from the project's
// recommended dashboard layout: object/tracked counts and whether
// depth/tracking data is present this frame -- a quick, glanceable
// answer to "is perception working right now," distinct from the
// per-object detail `ObjectInspectorTable` provides.
import type { PerceptionStatus } from "../api/visionTypes";

interface PerceptionStatusPanelProps {
  status: PerceptionStatus;
}

function StatusRow({ label, value, ok }: { label: string; value: string; ok?: boolean }) {
  return (
    <div className="perception-status__row">
      <span className="perception-status__label">{label}</span>
      <span
        className={
          ok === undefined
            ? "perception-status__value"
            : `perception-status__value perception-status__value--${ok ? "ok" : "warn"}`
        }
      >
        {value}
      </span>
    </div>
  );
}

export function PerceptionStatusPanel({ status }: PerceptionStatusPanelProps) {
  return (
    <div className="perception-status">
      <h2 className="perception-status__title">Perception</h2>
      <StatusRow label="Objects" value={String(status.object_count)} />
      <StatusRow label="Tracked" value={String(status.tracked_count)} />
      <StatusRow
        label="Depth"
        value={
          status.depth_available_count > 0
            ? `✓ ${status.depth_available_count}/${status.object_count} (${status.depth_source})`
            : "unavailable"
        }
        ok={status.depth_available_count > 0}
      />
      <StatusRow
        label="Tracking"
        value={status.tracked_count > 0 ? "✓ active" : "unavailable"}
        ok={status.tracked_count > 0}
      />
    </div>
  );
}
