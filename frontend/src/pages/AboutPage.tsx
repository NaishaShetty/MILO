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
//
// Visual pass: reproduces the About MILO mockup's composition -- hero
// (MiloPresence + dialogue + trait cards), a capability-card grid for
// "How MILO Works" (icons instead of a bare numeric index), a small
// "MILO Expressions" showcase, and a closing CTA panel -- every stage
// name/description, greeting, and link/href from the original static
// content is unchanged, only the surrounding markup/CSS changed. The
// expressions showcase renders explicit `MiloState` props (never the
// live canonical state) precisely because `MiloAvatar`'s own docstring
// calls this out as the one legitimate non-live use of the component --
// a design preview, clearly labeled, not a claim that MILO is actually
// in that state right now.
import { Link } from "react-router-dom";

import { AboutIcon } from "../components/AboutIcons";
import type { AboutIconName } from "../components/AboutIcons";
import { GlassCard } from "../components/GlassCard";
import { MiloAvatar } from "../components/MiloAvatar";
import { MiloPresence } from "../components/MiloPresence";
import { useMiloState } from "../state/MiloStateContext";
import type { MiloState } from "../state/miloState";

const PIPELINE_STAGES: Array<{ stage: string; icon: AboutIconName; description: string }> = [
  {
    stage: "Perceive",
    icon: "perceive",
    description:
      "The Vision agent detects and localizes objects in the current scene via the backend's " +
      "perception pipeline (detection, depth, tracking, scene graph).",
  },
  {
    stage: "Understand",
    icon: "understand",
    description:
      "A natural language instruction is parsed into a structured task (goal, object, target) " +
      "by the Language agent.",
  },
  {
    stage: "Remember",
    icon: "remember",
    description:
      "The Memory agent retrieves relevant things MILO already knows or has experienced before " +
      "planning, and writes new memories once a task concludes.",
  },
  {
    stage: "Plan",
    icon: "plan",
    description: "The Planner agent expands the goal into an ordered sequence of executable steps.",
  },
  {
    stage: "Navigate",
    icon: "navigate",
    description: "The Execution agent drives the simulated robot through the environment toward its target.",
  },
  {
    stage: "Act",
    icon: "act",
    description: "Each planned step is dispatched to the AI2-THOR simulator and its result recorded.",
  },
  {
    stage: "Reflect",
    icon: "reflect",
    description: "The Reflection agent examines what happened -- especially failures -- and why.",
  },
  {
    stage: "Replan",
    icon: "replan",
    description: "When something goes wrong, the Orchestrator triggers a new plan instead of giving up.",
  },
  {
    stage: "Learn",
    icon: "learn",
    description: "The outcome -- success or failure -- is written back to memory for next time.",
  },
];

// Static, truthful product traits -- each maps to a real, already-
// described part of the architecture above (memory writes, perception,
// the memory store, replanning); no invented capability or statistic.
// Icons reuse `AboutIconName`s already defined for the pipeline stages
// below (same concepts: learn, perceive, remember, replan).
const TRAITS: Array<{ title: string; body: string; icon: AboutIconName }> = [
  {
    title: "Always Learning",
    body: "Every task's outcome -- success or failure -- gets written back to memory for next time.",
    icon: "learn",
  },
  {
    title: "Always Watching",
    body: "The Vision agent perceives the current scene before MILO decides what to do.",
    icon: "perceive",
  },
  {
    title: "Always Remembering",
    body: "Memory is retrieved before planning and updated after every task, not an afterthought.",
    icon: "remember",
  },
  {
    title: "Always Adapting",
    body: "When a step fails, the Orchestrator replans instead of giving up on the goal.",
    icon: "replan",
  },
];

// Conceptual only -- explicit props, not the live `MiloState` (see this
// file's own docstring and `MiloAvatar.tsx`'s). Labeled as a showcase,
// never presented as MILO's current state.
const EXPRESSION_SHOWCASE: Array<{ state: MiloState; label: string }> = [
  { state: "idle", label: "Idle" },
  { state: "listening", label: "Listening" },
  { state: "thinking", label: "Thinking" },
  { state: "executing", label: "Executing" },
  { state: "success", label: "Success" },
];

export function AboutPage() {
  const miloState = useMiloState();
  return (
    <main aria-label="About MILO" className="about-page">
      <h1 className="sr-only">About MILO</h1>

      <section className="about-page__hero milo-hero-panel">
        <div className="about-page__character">
          <div className="milo-glow-orb" aria-hidden="true" />
          <MiloPresence state={miloState} size="lg" dialogueText="Hey! I'm MILO 👋" />
        </div>
        <div className="about-page__intro">
          <p className="about-page__greeting">Hi, I'm MILO.</p>
          <p className="about-page__fullname">Memory Integrated Language Oriented Robot</p>
          <p className="about-page__pullquote">
            &ldquo;I don't just execute tasks. I learn from them.&rdquo;
          </p>
          <Link to="/mission-control" className="about-page__talk-link">
            Talk to MILO <span aria-hidden="true">→</span>
          </Link>
        </div>
        <div className="about-page__traits">
          {TRAITS.map((trait) => (
            <div key={trait.title} className="about-page__trait">
              <span className="about-page__trait-icon" aria-hidden="true">
                <AboutIcon name={trait.icon} />
              </span>
              <div>
                <strong>{trait.title}</strong>
                <p>{trait.body}</p>
              </div>
            </div>
          ))}
        </div>
      </section>

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
        <div className="about-page__pipeline">
          {PIPELINE_STAGES.map(({ stage, icon, description }, index) => (
            <GlassCard key={stage} className="about-page__pipeline-card">
              <div className="about-page__pipeline-head">
                <span className="about-page__pipeline-icon">
                  <AboutIcon name={icon} />
                </span>
                <span className="about-page__pipeline-index">{index + 1}</span>
              </div>
              <strong className="about-page__pipeline-stage">{stage}</strong>
              <p className="about-page__pipeline-description">{description}</p>
            </GlassCard>
          ))}
        </div>
      </section>

      <section aria-label="MILO Expressions" className="about-page__section">
        <h2>MILO Expressions</h2>
        <p className="about-page__expressions-note">
          A conceptual look at MILO's visual states -- not a live readout (see Mission Control for
          that).
        </p>
        <div className="about-page__expressions">
          {EXPRESSION_SHOWCASE.map(({ state, label }) => (
            <div key={state} className="about-page__expression">
              <div className="about-page__expression-frame">
                <MiloAvatar state={state} size="md" />
              </div>
              <span>{label}</span>
            </div>
          ))}
        </div>
      </section>

      <section aria-label="Explore MILO" className="about-page__cta milo-hero-panel">
        <div className="about-page__cta-milo">
          <MiloAvatar state="idle" size="md" />
        </div>
        <div className="about-page__cta-body">
          <h2>Ready to see what MILO can do?</h2>
          <p>
            My goal is simple: understand, remember, and learn -- so I can make the next task
            easier than the last.
          </p>
          <div className="about-page__links">
            <Link to="/">Home</Link>
            <Link to="/mission-control">Mission Control</Link>
            <Link to="/lab">MILO Lab</Link>
          </div>
        </div>
      </section>
    </main>
  );
}
