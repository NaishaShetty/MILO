# Model card: world model (Phase F, optional)

**What it is.** A learned transition model over the symbolic world MILO already logs. From a step's context (the same feature vector as the outcome predictor) it predicts, after the step: is the target visible, reachable, open, switched on, and is the hand holding something. One gradient-boosted tree classifier per field (scikit-learn), trained on the Phase A training split.

**What it is used for.** Plan scoring. The Phase B ranker scores every step against the state *before the plan runs*, so a `pickup` after a `navigate` is judged as if the robot were still far away. With the world model, `rollout_score` walks the plan and scores each step against the state the earlier steps are predicted to leave behind.

| Variable | Meaning |
|---|---|
| `MILO_WORLD_MODEL=1` | use rollout scoring (default off; needs `MILO_PLAN_RANKING=1`) |
| `MILO_WORLD_MODEL_PATH` | default `artifacts/worldmodel/world.pkl` |

A missing model, a load failure or any exception during a rollout means the original static scoring is used.

**Results (held-out scenes)**

Next-state accuracy, 5,853 test steps (learned vs "nothing changes" vs always-the-majority-class):

| Field | Learned | Copy-before | Majority |
|---|---|---|---|
| visible | 0.923 | 0.810 | 0.818 |
| reachable | 0.903 | 0.689 | 0.616 |
| is_open | 0.992 | 0.906 | 0.796 |
| is_on | 0.994 | 0.969 | 0.915 |
| holding | 0.992 | 0.868 | 0.748 |

On the steps where the state really does change, accuracy is 0.88 for `reachable`, 0.94 for `holding`, 0.99 for `is_open`, 0.80 for `is_on`, but only 0.59 for `visible`.

Plan scores (365 held-out episodes): the static scorer gives a score of exactly zero to 67% of plans because later steps' preconditions are not met in the starting state; the rollout does so for 8%. Predicting mission success from the plan score: AUROC 0.525 (static) vs 0.552 (rollout).

**Honest caveats**

- **No mission-level gain.** Static, rollout and no ranking all give 70.0% mission success, 0.135 replans per mission and 8.4 s mean time on the same 400 episodes. In this synthetic simulator the three planners produce identical action sequences, so there is never a better plan to choose. Ranking cannot help here whatever the score.
- The rollout makes the plan score *much less degenerate* and the transition model clearly beats the baselines, but the improvement in how well the score predicts mission success is small (AUROC 0.55 is only slightly better than chance). Mission outcomes are dominated by injected faults that the symbolic state does not show.
- The model only tracks the acted-on target and the hand. Other objects' distances after a `navigate` are not updated.
- Everything is learned from the synthetic Phase A logs. Before relying on it, re-check on real AI2-THOR runs where planners may genuinely differ.
- Recommendation: leave off until there is a setting where planners produce different plans; it costs a few milliseconds per candidate plan.

Reproduce: `make eval-worldmodel`.

## Re-evaluated on competing routes (2026-11-25)

The benchmark's routes tier (`docs/benchmark.md`) is where a world model should help: the nearest shelf or table is blocked for good and a farther one is clear, so every plan that goes to the near one fails. A failure counts as caught if its plan scores below every plan that succeeds, so it could be rejected before acting without rejecting a good plan.

| | Plans | Rollout score | Caught before acting |
|---|---|---|---|
| Route plans (all fail) | 4 | 0.770 each | **0 of 4** |
| Known-task plans (all succeed) | 23 | median 0.770, minimum 0.0 | – |

**No gain, for two structural reasons:**

1. The blockage isn't in anything the model sees. It is a hidden fault, not an object state, so a doomed route plan scores exactly like a good one.
2. Plans name object types ("shelf"), not instances ("Shelf|2"). Even a perfect score could only reject the plan; nothing could ask for the other shelf instead.

The criterion also can't catch anything while some successful plan scores 0.0. Fixing either reason needs new inputs, not a better model: an observable obstacle in the state, and plans that can name an instance. Until then the recommendation stands: leave it off.

Reproduce: `make eval-worldmodel-routes` (uses `backend/artifacts`).