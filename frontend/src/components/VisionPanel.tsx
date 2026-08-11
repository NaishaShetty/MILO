// VisionPanel.tsx
//
// Purpose
// -------
// Top-level component for the Vision half of the dashboard -- owns the
// lifecycle of the most recent `perceive()` call (idle -> loading ->
// success/error), exactly mirroring how `App.tsx` owns the Language
// request lifecycle (see that file's docstring), and composes the
// camera/depth/status/inspector panels underneath it. Kept as its own
// component (not inlined into `App.tsx`) so `App.tsx` stays a thin
// two-column composition of "the Vision panel" and "the Language
// panel," neither of which needs to know the other exists.
import { useEffect, useState } from "react";
import { perceive } from "../api/vision";
import type { PerceiveResponse, SpatialObject } from "../api/visionTypes";
import { CameraPanel } from "./CameraPanel";
import { DepthPanel } from "./DepthPanel";
import { ObjectInspectorTable } from "./ObjectInspectorTable";
import { PerceptionStatusPanel } from "./PerceptionStatusPanel";
import { SceneChangesList } from "./SceneChangesList";
import { VisionErrorBanner } from "./VisionErrorBanner";
import { VisionPromptForm } from "./VisionPromptForm";

type VisionRequestState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "success"; response: PerceiveResponse }
  | { status: "error"; error: Error };

export interface VisionPanelProps {
  /** Real robot position (from `TaskContext.robotState`), passed
   * through to `CameraPanel`'s minimap overlay -- purely presentational,
   * VisionPanel does not fetch or derive it itself. */
  robotPosition?: { x: number; z: number } | null;
  /** Mirrors the latest perceive() result's objects out to a parent
   * that wants to render them elsewhere (Mission Control's "Detected
   * Objects" strip) without owning a second fetch of its own -- see
   * this file's docstring: `VisionPanel` remains the single call site
   * for `perceive()`. */
  onObjectsChange?: (objects: SpatialObject[] | null) => void;
}

export function VisionPanel({ robotPosition = null, onObjectsChange }: VisionPanelProps = {}) {
  const [requestState, setRequestState] = useState<VisionRequestState>({ status: "idle" });

  async function handleSubmit(prompt: string): Promise<void> {
    setRequestState({ status: "loading" });
    try {
      const response = await perceive(prompt);
      setRequestState({ status: "success", response });
    } catch (error) {
      setRequestState({
        status: "error",
        error: error instanceof Error ? error : new Error(String(error)),
      });
    }
  }

  const isLoading = requestState.status === "loading";
  const response = requestState.status === "success" ? requestState.response : null;

  useEffect(() => {
    onObjectsChange?.(response?.objects ?? null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [response]);

  return (
    <section className="vision-panel" aria-label="Vision">
      <VisionPromptForm onSubmit={handleSubmit} isLoading={isLoading} />

      {requestState.status === "error" && <VisionErrorBanner error={requestState.error} />}

      <CameraPanel
        imageBase64={response?.camera_image_png_b64 ?? null}
        isLoading={isLoading}
        robotPosition={robotPosition}
      />

      <DepthPanel
        imageBase64={response?.depth_image_png_b64 ?? null}
        legend={response?.depth_legend ?? null}
      />

      {response && (
        <>
          <PerceptionStatusPanel status={response.status} />
          <SceneChangesList changes={response.scene_changes} />
          <ObjectInspectorTable objects={response.objects} />
        </>
      )}
    </section>
  );
}
