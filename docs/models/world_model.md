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
