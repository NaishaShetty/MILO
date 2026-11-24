import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { MiloRobot, poseForState, rigForPose } from "./MiloRobot";
import type { MiloPose } from "./MiloRobot";

describe("pose to rig mapping", () => {
  it("uses the side rig only for walking and running", () => {
    const poses: MiloPose[] = ["idle", "listening", "thinking", "speaking", "walk", "run", "success", "error"];
    const side = poses.filter((p) => rigForPose(p) === "side");
    expect(side).toEqual(["walk", "run"]);
  });

  it("maps app states onto poses", () => {
    expect(poseForState("listening")).toBe("listening");
    expect(poseForState("planning")).toBe("thinking");
    expect(poseForState("executing")).toBe("run");
    expect(poseForState("success")).toBe("success");
    expect(poseForState("error")).toBe("error");
    expect(poseForState("offline")).toBe("idle");
  });
});

describe("MiloRobot", () => {
  it("renders the front rig with independent parts and alt text", () => {
    const { container } = render(<MiloRobot pose="thinking" />);
    expect(screen.getByRole("img", { name: /MILO the robot, thinking/ })).toBeInTheDocument();
    expect(container.querySelector("[data-rig='front']")).not.toBeNull();
    for (const part of [".milo-head", ".milo-eyes", ".milo-arm--l", ".milo-arm--r", ".milo-leg--l", ".milo-leg--r"]) {
      expect(container.querySelector(part), part).not.toBeNull();
    }
  });

  it("renders the side rig with elbows and knees when running", () => {
    const { container } = render(<MiloRobot pose="run" />);
    expect(container.querySelector("[data-rig='side']")).not.toBeNull();
    expect(container.querySelectorAll(".milo-knee").length).toBe(2);
    expect(container.querySelectorAll(".milo-elbow").length).toBe(2);
  });

  it("mirrors the side rig to face the direction of travel", () => {
    const left = render(<MiloRobot pose="walk" facing="left" />).container;
    expect(left.querySelector("g[transform*='scale(-1 1)']")).not.toBeNull();
    const right = render(<MiloRobot pose="walk" facing="right" />).container;
    expect(right.querySelector("g[transform*='scale(-1 1)']")).toBeNull();
  });

  it("shows a carried object and mentions it for screen readers", () => {
    const { container } = render(<MiloRobot pose="walk" carrying="apple" />);
    expect(container.querySelector(".milo-carried")).not.toBeNull();
    expect(screen.getByRole("img", { name: /carrying the apple/ })).toBeInTheDocument();
  });

  it("has happy eyes on success and slanted eyes on error", () => {
    expect(render(<MiloRobot pose="success" />).container.querySelectorAll("path[d^='M80 98']").length).toBe(1);
    expect(render(<MiloRobot pose="error" />).container.querySelector("rect[transform*='rotate(14']")).not.toBeNull();
  });

  it("can be paused for snapshots", () => {
    const { container } = render(<MiloRobot pose="run" paused />);
    expect(container.querySelector(".milo-robot--paused")).not.toBeNull();
  });
});

const here = dirname(fileURLToPath(import.meta.url));
const read = (name: string) => readFileSync(resolve(here, "..", name), "utf8");

describe("reduced motion and palette", () => {
  const css = read("milo.css");

  it("disables running and bouncing animations under prefers-reduced-motion", () => {
    const block = css.slice(css.indexOf("@media (prefers-reduced-motion: reduce)"));
    expect(block).toContain("animation: none !important");
  });

  it("uses no purple or blue", () => {
    const tokens = read("tokens.css");
    for (const bad of ["#8b5cf6", "#4f7cff", "purple", "blue", "violet", "indigo"]) {
      expect(css.toLowerCase()).not.toContain(bad);
      expect(tokens.toLowerCase()).not.toContain(bad);
    }
  });
});
