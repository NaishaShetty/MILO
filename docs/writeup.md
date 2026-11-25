# MILO: a household robot that works things out, asks first, and checks its work

*Technical write-up, 2026-11-25.*

## The problem

Household-robot demos usually work for the commands they were built for and fail silently on everything else. They guess when a request is ambiguous ("bring me the cup" with two cups). They report success when the world disagrees. They trust whatever is in their memory. We wanted a robot whose behaviour on the *unexpected* is sensible:
- work out new tasks;
- ask instead of guessing;
- get approval before risky actions;
- verify outcomes against the world;
- learn from both success and failure;
- resist bad information.

## Design

**One trusted action vocabulary.** Every plan, whether from a classical planner or a language model, can only use actions from a typed registry with preconditions and effects. A symbolic run of the registry catches impossible orderings before anything moves. This exposed a real bug: two plan actions were silently executed as no-ops that reported success.

**The world decides success.** Goal conditions (*the apple is in the fridge*, *the fridge is closed*) are read from the simulator's own object state. Plans MILO works out itself state their own conditions, and those are always enforced. If every step "worked" but a condition is false, MILO replans with that reason.

**Novel tasks.** An unknown command goes to a pluggable planner (Claude via structured outputs, or offline). Its answer is a strict schema: a plan, one clarifying question, or a plain refusal. Plans are validated, repaired where the only problem is "go there first" or "already done", gated by a constraints file (allowlist, fragile/dangerous objects, budgets), previewed to the user, and run through the normal orchestrator. Successes become parameterised skills ("chill the {o0}"). A skill is trusted after repeated success on different objects. Failures become lessons.

**Human in the loop.** Ambiguity produces one question with tappable choices pinned to real objects. Risky steps wait for approval, and no answer means *skip*. Every completed step records the state before it, so undo can play inverse actions back. Voice uses the browser's own speech, with spoken questions and approvals.

**Memory you can trust.** Every memory carries a source, confidence and decay:
- trust-weighted lookups: user > observation > skill > imported;
- quarantine for imported memories that contradict trusted ones or read like instructions;
- reconciliation against what the camera sees right now.

**Measurement as a feature.** A versioned trace store records every mission: plan, steps, timings, frames, thoughts, verdicts. That one store feeds replay, p50/p95 timings, the scene map, the benchmark, CI and the demo mode. A fixed benchmark runs every planner, ablation and fault kind in about 10 seconds, deterministically. CI fails a push that drops any planner's success by more than 5 points; we confirmed this on a deliberately broken branch.

## Results

| Phase | Baseline | New | Verdict |
|---|---|---|---|
| Foundation: goal checks | successes taken on trust | 3 of 213 "successes" shown false by the world | better (now visible) |
| Novel tasks (60 commands) | 0/60 (refused) | 60/60 with reference plans; 10/10 bad plans caught; 0 unsafe actions | pipeline proven; **LLM result not measured** |
| Teaching skills | — | a taught skill reused in a new room on a new object, 0 model calls; chained skills run end to end | meets acceptance |
| Ask / approve / undo | guesses between two cups | one question with exact choices; risky steps wait; undo restores the fridge and the apple | meets acceptance |
| Memory poisoning | 0% correct at full attack | 100% (imported preferences, fake skills) | better, except **spoofed user memories: 0% → 0%** |
| Failure memory | 0% on repeats | 100% for "couldn't see it"; out of reach unchanged | better where a fix exists |
| Benchmark and CI | none | reproducible suite; gate fails a broken branch | meets acceptance |
| Observability / replay / map | — | stage p50/p95, waterfall, scrubbable replay, shareable link, report, top-down map | delivered |
| Voice | server speech only | browser speech, spoken questions and approvals, fallback | delivered; **not tried in a real browser** |
| Learned models (earlier roadmap) | rules / Grounding DINO / hashing | outcome predictor +6.6 pts success; detector 20x faster; embedder and world model: no mission change | mixed, reported per model |

## What didn't work

- **Some faults used to barely recover within a mission.** Wrong detection recovered 4% of the time and out of reach 22%, because a retry never re-ran the walk-up. Targeted in-mission fixes (look around after "not visible", re-approach after "not reachable") raised these to 83% and 100%. "Find" tasks under a wrong detection still only recover on the *next* mission, through failure memory.
- **Memory adds nothing on our benchmark** because every object is always visible. That's a weakness of the benchmark as much as a finding.
- **Spoofed user memories can't be told apart from a real change of mind** without authenticated input.
- **We never ran a language model in this environment** (no credentials). The novel-task numbers measure everything except the model's own planning.
- **Nearly everything was measured in a synthetic simulator.** Only the detector was evaluated on real rendered AI2-THOR frames.

## Next

Run the novel-task and full benchmarks with Claude; add within-mission mitigations for detection and reach; authenticate user statements; and repeat every measurement on real AI2-THOR scenes.
