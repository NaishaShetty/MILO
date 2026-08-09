// AboutPage.tsx
//
// Purpose
// -------
// Informational page explaining what MILO is and how it works (the
// Perceive -> Understand -> Remember -> Plan -> Navigate -> Act ->
// Reflect -> Replan -> Learn pipeline this whole project implements).
// No backend integration needed (spec: "This page does not require
// complex backend integration") -- just static content plus links to
// Home/Mission Control/MILO Lab.
import { Link } from "react-router-dom";

const PIPELINE_STAGES: Array<{ stage: string; description: string }> = [
  {
    stage: "Perceive",
    description:
      "The Vision agent detects and localizes objects in the current scene via the backend's " +
      "perception pipeline (detection, depth, tracking, scene graph).",
  },
  {
    stage: "Understand",
    description:
      "A natural language instruction is parsed into a structured task (goal, object, target) " +
      "by the Language agent.",
  },
  {
    stage: "Remember",
    description:
      "The Memory agent retrieves relevant things MILO already knows or has experienced before " +
      "planning, and writes new memories once a task concludes.",
  },
  {
    stage: "Plan",
    description: "The Planner agent expands the goal into an ordered sequence of executable steps.",
  },
  {
    stage: "Navigate",
    description: "The Execution agent drives the simulated robot through the environment toward its target.",
  },
  {
    stage: "Act",
    description: "Each planned step is dispatched to the AI2-THOR simulator and its result recorded.",
  },
  {
    stage: "Reflect",
    description: "The Reflection agent examines what happened -- especially failures -- and why.",
  },
  {
    stage: "Replan",
    description: "When something goes wrong, the Orchestrator triggers a new plan instead of giving up.",
  },
  {
    stage: "Learn",
    description: "The outcome -- success or failure -- is written back to memory for next time.",
  },
];

export function AboutPage() {
  return (
    <main aria-label="About MILO" className="about-page">
      <h1>👋 About MILO</h1>
      <p className="about-page__greeting">Hi, I'm MILO.</p>
      <p className="about-page__fullname">Memory Integrated Language Oriented Robot</p>

      <section aria-label="What is MILO" className="about-page__section">
        <h2>What is MILO?</h2>
        <p>
          MILO is an embodied AI system operating in the AI2-THOR simulator. It's built to take a
          natural-language instruction from a person and carry it out in a simulated home --
          finding objects, navigating rooms, picking things up, and reporting back what happened.
        </p>
        <p>
          Most language-driven robot agents forget everything the moment a task ends. MILO's
          defining idea is that it shouldn't have to relearn the same environment, the same
          objects, and the same mistakes every single time -- so memory is a first-class part of
          its architecture, not an afterthought.
        </p>
      </section>

      <section aria-label="How MILO Works" className="about-page__section">
        <h2>How MILO Works</h2>
        <ol className="about-page__pipeline">
          {PIPELINE_STAGES.map(({ stage, description }) => (
            <li key={stage}>
              <strong>{stage}</strong> — {description}
            </li>
          ))}
        </ol>
      </section>

      <section aria-label="Explore MILO" className="about-page__section">
        <h2>Explore MILO</h2>
        <div className="about-page__links">
          <Link to="/">🏠 Home</Link>
          <Link to="/mission-control">🎮 Mission Control</Link>
          <Link to="/lab">🔬 MILO Lab</Link>
        </div>
      </section>
    </main>
  );
}
