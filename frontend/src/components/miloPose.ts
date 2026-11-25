// miloPose.ts -- which rig draws a pose, and which pose shows an app-wide MILO state.
import type { MiloState } from "../state/miloState";
import type { MiloPose, MiloRig } from "./MiloRobot";

/** The side rig is used for travel, the front rig for everything else. */
export function rigForPose(pose: MiloPose): MiloRig {
  return pose === "walk" || pose === "run" ? "side" : "front";
}

/** Maps the app-wide MILO state onto a drawable pose. */
export function poseForState(state: MiloState): MiloPose {
  switch (state) {
    case "listening":
      return "listening";
    case "understanding":
    case "thinking":
    case "planning":
    case "recalling_memory":
    case "replanning":
    case "reflecting":
      return "thinking";
    case "speaking":
      return "speaking";
    case "navigating":
    case "executing":
      return "run";
    case "success":
      return "success";
    case "error":
      return "error";
    default:
      return "idle";
  }
}
