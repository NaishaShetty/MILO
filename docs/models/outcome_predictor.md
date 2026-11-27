# Model card: step outcome predictor

**What it does.** Before each step runs, estimates P(step succeeds), expected duration, P(a retry would succeed) and the most likely failure type. MILO uses it (behind flags) to show per-step confidence, to choose retry / replan / stop after a failure (`LearnedReflector`), and to rank candidate plans (`PlanRanker`).

**Inputs** (`learning/predictor_features.py`, one function for training and serving): action, target class, target visibility / distance / reachable / open / on, whether the hand is full, retries and replans so far, step index and steps remaining, memory-hit statistics, planner, perception confidence. Nothing observed after the step is used.

**Training data.** `python -m learning.generate` + `learning.build_dataset`: 6,000 synthetic episodes, 50 scenes, 28,896 labelled steps (seed 0, 2026-11-24). Test = 10 whole held-out scenes (5,853 steps); train/val split by episode. **The data is from a synthetic simulator with injected faults (blocked path, out of reach, stuck door, timeout, wrong detection, missing object), not AI2-THOR.**

**Models.** scikit-learn HistGradientBoosting (LightGBM needs a system OpenMP library not present here) with isotonic calibration fitted on validation data; a small PyTorch MLP was also trained and was *not* kept (no clear margin over the trees).

**Held-out-scene results (success probability).**

| | AUROC | PR-AUC | Brier | ECE |
|---|---|---|---|---|
| gradient-boosted trees | 0.968 | 0.990 | 0.0459 | 0.0052 |
| MLP (not served) | 0.968 | 0.990 | 0.0451 | 0.0048 |
| hand-written rules | 0.661 | 0.873 | 0.2653 | 0.2192 |
| majority class | 0.500 | 0.822 | 0.1464 | 0.0000 |

Duration MAE 234 ms (mean-predictor 1,482 ms). Failure-type accuracy 0.899 (majority 0.253). Latency p50 about 6 ms, p95 about 7 ms per call (budget 20 ms).

**Online, 600 episodes on the held-out scenes, identical seeds, same fault mix** (`make eval-outcome`):

| | mission success | wasted steps / mission | replans / mission | mean time (sim s) |
|---|---|---|---|---|
| rule-based reflector | 0.717 | 1.94 | 0.118 | 8.53 |
| shadow (same behaviour, logs only) | 0.717 | 1.94 | 0.118 | 8.53 |
| learned reflector (`on`) | 0.783 | 1.22 | 0.160 | 8.95 |

93 missions were aborted early by the learned reflector; all 93 also failed under the rule-based reflector. Mean time is slightly higher.

**Known limits.** Trained and evaluated on synthetic data whose failures are mostly determined by the features the model sees, so the offline numbers are optimistic and the online gain is **not yet shown on AI2-THOR**. Keep the flag at `shadow` until real-simulator episodes have been logged and compared. Memory-hit features are always zero in this dataset. Duration labels are simulated seconds. Under input drift, high latency or low confidence the system falls back to the rule-based reflector.

**Flags.** `MILO_LEARNED_REFLECTOR=off|shadow|on` (default `off`), `MILO_PLAN_RANKING=0|1`, `MILO_MODEL_DIR`. Reproduce: `make data dataset train-outcome eval-outcome`. Promote a retrained model only if it wins: `make promote-outcome` (previous version kept; `python -m learning.promote --rollback`).

## On real AI2-THOR episodes (2026-11-27)

`make collect-thor` logged 600 real AI2-THOR episodes (nothing injected; 349 succeeded, 251 failed). `make train-real` trained the same model on the synthetic episodes plus the 300 real episodes from training scenes, and tested it on the other 300, from 20 real scenes it never saw: 1,070 steps, of which 54 failed. Results: `results/outcome_real/offline_real_test.json`.

| Real held-out steps | AUROC | Brier | ECE |
|---|---|---|---|
| **Current model (synthetic only, the one MILO ships)** | **0.39** | 0.231 | 0.239 |
| Retrained (synthetic + real) | **0.99** | 0.017 | **0.017** |
| Hand-written rules | 0.13 | 0.607 | 0.647 |

**The shipped model does not transfer to real AI2-THOR**: it ranks real failures worse than chance. This is the risk the limits above warned about, now measured.

**Most of the retrained model's 0.99 is easy.** In real AI2-THOR almost every failure is a *place* step: 51 of 99 "put it down" steps failed, against 3 of 971 other steps. So "place steps are risky" alone scores highly. On place steps alone (99 steps, 51 failures) the retrained model still has real skill: AUROC 0.87, ECE 0.054, while the shipped model predicts success for every one of them (AUROC 0.5). It has learned, for example, that putting down a plate, pillow, pot or box often fails, and keys or a mug rarely do.

### On real missions: no gain (2026-11-27)

`make eval-outcome-thor` (`learning/eval_online_thor.py`): 300 real AI2-THOR missions in the 20 held-out scenes, each run twice with the same scene, task and planner, once with the rule-based reflector and once with the retrained predictor deciding (`on`). Tasks use a different seed from the collected episodes. Results: `results/outcome_real/online_thor.summary.json`, one line per pair in `online_thor.jsonl`.

| 300 paired real missions | Mission success | Wasted steps / mission | Replans / mission | Retries / mission |
|---|---|---|---|---|
| Rule-based reflector | 60.0% | 1.277 | 0.013 | 0.120 |
| Retrained predictor deciding | 60.0% | 1.260 | 0.010 | 0.120 |

No pair succeeded on one side only. The predictor made a decision in 3 of the 300 missions; it stopped 1 early, which also failed with the rule-based reflector. It never switched itself off for being slow.

**Why so little:** the learned reflector chooses only between retrying, replanning and stopping, and its rules map the failure types the synthetic simulator injects (blocked, not reachable, not visible, wrong object) to those moves. Real AI2-THOR failures are almost all a *place* step failing for an "other" reason, and for that the rules have no move, so the rule-based choice stands. The model can tell which put-downs are likely to fail (AUROC 0.87 on place steps); MILO has no action that uses it.

**Decision: not promoted; the flag stays at `shadow`.** Offline it is calibrated (ECE 0.017, under the 0.05 bar), but it does not win on real missions. The retrained model is in `artifacts/outcome_real/` on this laptop (not in git). The next step is a design change, not more training: use the prediction *before* a place step, for example to choose another receptacle or spot when one is likely to fail, and measure that on real missions the same way.

Two more caveats: 54 failing test steps is a small sample, and real missions fail mostly in ways step-level prediction can't see (95% of real steps succeed, but only 56% of real missions).
