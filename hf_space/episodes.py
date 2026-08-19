"""
episodes.py -- picks a small, representative handful of real logged
episodes out of the full `episodes` array for the replay tab, and builds
a display record for each.

Two honesty notes, spelled out here because they matter more than the
code:

1. **Plan traces are reconstructed, not logged.** The source JSON's
   episode records have aggregate fields only (`action_count`,
   `plan_step_count`) -- there is no per-step action log in
   `experiments/results/*.json`. `reconstruct_plan_trace()` below builds
   an illustrative step list from this project's documented,
   deterministic planner behavior (see `phase_e_milo_benchmark_report.md`
   and the dataset README: tier1_locate = locate; tier2_pickup = locate
   -> navigate -> pick_up; tier3_store = locate -> navigate -> pick_up ->
   navigate -> open (if openable) -> place -> close (if opened), per
   `_deposit()`'s documented behavior). Every trace built this way is
   labeled "reconstructed plan trace for illustration" in the UI and
   should never be read as a literal log pulled from a file -- it isn't
   one. `react` failures short-circuit the trace at the step named in
   the episode's real, logged `failure_cause` string, since that much
   *is* real (a genuine, logged planner-rejection message).

2. **Screenshots are generic, not per-episode.** `docs/screenshots/demo/`
   has exactly 3 images from one live product walkthrough, not one image
   per dataset task. They're associated with illustrative episodes below
   purely as "here's roughly what the live UI looks like when this kind
   of thing happens," and every place they're shown is captioned to say
   exactly that -- never "this is what episode X looked like."
"""

from __future__ import annotations

from dataclasses import dataclass, field

# (planner, task_id) pairs picked for the replay tab, with a one-line
# reason each was picked.
CURATED_EPISODES = [
    ("rule_based", "milo-v1-fp1-t3a", "rule_based success on a tier3_store task (bread -> fridge)."),
    ("behavior_tree", "milo-v1-fp5-t3a", "behavior_tree success on a different scene's tier3_store task (mug -> cabinet), for scene variety."),
    ("htn", "milo-v1-fp401-t3a", "htn success on a tier3_store task requiring real open/place decomposition (spray bottle -> shelf, non-openable target) -- a genuine HTN method-library expansion (DepositObject), not a second implementation of rule_based's control flow, reaching the identical plan shape."),
    ("react", "milo-v1-fp1-t2a", "react's strongest tier: a genuine tier2_pickup success (apple), plan produced and executed for real."),
    ("react", "milo-v1-fp1-t3a", "react's typical tier3_store failure mode: mis-sequenced action rejected by the precondition validator, not an infrastructure error."),
    ("rule_based", "milo-v1-fp301-t3a", "The known, still-failing FloorPlan301 book->drawer case: a real AI2-THOR geometry limit (the drawer has no room for this book), not a planner defect. Documented in the dataset README's 'Known limitations' and reproduced identically by all three symbolic planners (rule_based, behavior_tree, htn)."),
]

SCREENSHOT_ASSOCIATIONS = {
    # (planner, task_id) -> list of screenshot filenames, illustrative only.
    ("rule_based", "milo-v1-fp1-t3a"): [
        "live-01-instruction-typed.png",
        "live-02-task-in-progress.png",
        "live-03-task-complete.png",
    ],
}


@dataclass
class EpisodeDisplay:
    planner: str
    task_id: str
    reason_picked: str
    scene: str
    room_type: str
    difficulty_tier: str
    instruction: str
    goal: str
    object_: str
    target: str | None
    plan_success: bool
    execution_success: bool
    goal_success: bool
    wall_clock_ms: float
    failure_cause: str | None
    llm_retry_attempts: int
    model_label: str
    plan_trace: list = field(default_factory=list)
    screenshots: list = field(default_factory=list)

    @property
    def title(self) -> str:
        outcome = "SUCCESS" if self.goal_success else "FAILED"
        return f"[{outcome}] {self.planner} — {self.task_id} — {self.instruction}"


MODEL_LABELS = {
    "rule_based": "rule_based — deterministic symbolic planner, no LLM",
    "behavior_tree": "behavior_tree — deterministic BT composition of the same goal templates, no LLM",
    "htn": "htn — deterministic Hierarchical Task Network engine (compound tasks, method library, recursive decomposition), no LLM",
    "react": "react — qwen2.5:7b via Ollama, local (no cloud API, no external quota)",
}


def reconstruct_plan_trace(episode: dict) -> list[str]:
    """Build an illustrative step list from goal/object/target and this
    project's documented deterministic planner shape. NOT a literal log --
    see module docstring. Real failures short-circuit at the step implied
    by the episode's actual `failure_cause` string where possible."""
    goal = episode.get("goal")
    obj = episode.get("object")
    target = episode.get("target")
    tier = episode.get("difficulty_tier")
    cause = (episode.get("failure_cause") or "").lower()
    steps: list[str] = []

    if tier == "tier1_locate":
        steps.append(f"locate({obj})")
    elif tier == "tier2_pickup":
        steps += [f"locate({obj})", f"navigate(to={obj})", f"pick_up({obj})"]
    elif tier == "tier3_store":
        steps.append(f"locate({obj})")
        if "target_located" in cause:
            steps.append(f"navigate(to={obj})  <-- rejected: {episode.get('failure_cause')}")
            return steps
        steps.append(f"navigate(to={obj})")
        if "target_near" in cause and "pickup" in cause:
            steps.append(f"pick_up({obj})  <-- rejected: {episode.get('failure_cause')}")
            return steps
        steps.append(f"pick_up({obj})")
        steps.append(f"navigate(to={target})")
        if "target_near" in cause and "open" in cause:
            steps.append(f"open({target})  <-- rejected: {episode.get('failure_cause')}")
            return steps
        steps.append(f"open({target})  [only if target is openable]")
        if "holding_target" in cause or "container_ready" in cause:
            steps.append(f"place({obj}, {target})  <-- rejected: {episode.get('failure_cause')}")
            return steps
        if episode.get("failure_cause") and "no valid positions" in cause:
            steps.append(f"place({obj}, {target})  <-- execution failed: {episode.get('failure_cause')}")
            return steps
        steps.append(f"place({obj}, {target})")
        steps.append(f"close({target})  [only if opened above]")
    else:
        steps.append(f"{goal}({obj}" + (f" -> {target})" if target else ")"))
    return steps


def build_episode_displays(data) -> list[EpisodeDisplay]:
    by_key = {(e["planner"], e["task_id"]): e for e in data.episodes}
    out = []
    for planner, task_id, reason in CURATED_EPISODES:
        e = by_key.get((planner, task_id))
        if e is None:
            continue
        out.append(
            EpisodeDisplay(
                planner=planner,
                task_id=task_id,
                reason_picked=reason,
                scene=e.get("scene"),
                room_type=e.get("room_type"),
                difficulty_tier=e.get("difficulty_tier"),
                instruction=e.get("instruction"),
                goal=e.get("goal"),
                object_=e.get("object"),
                target=e.get("target"),
                plan_success=bool(e.get("plan_success")),
                execution_success=bool(e.get("execution_success")),
                goal_success=bool(e.get("goal_success")),
                wall_clock_ms=e.get("wall_clock_ms"),
                failure_cause=e.get("failure_cause"),
                llm_retry_attempts=e.get("llm_retry_attempts", 0),
                model_label=MODEL_LABELS.get(planner, planner),
                plan_trace=reconstruct_plan_trace(e),
                screenshots=SCREENSHOT_ASSOCIATIONS.get((planner, task_id), []),
            )
        )
    return out
