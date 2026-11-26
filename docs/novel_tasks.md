# Novel tasks: "figure it out" (roadmap 2, Phase 2)

When a command maps to nothing MILO knows (an unknown verb, or a goal no planner has a recipe for), the API starts it with the `novel` planner instead of replying "I don't know how to X yet". The Missions page says "I don't know this one yet, so I'm working it out." When MILO is reusing something it learned, it says that instead.

## How it works (`backend/novel/`)

1. **Skill first.** If the command has the same wording as a saved skill once object names are swapped for placeholders ("chill the apple" -> "chill the {o0}"), that skill is instantiated for the new objects. No model call is made.
2. **Otherwise ask the planner provider** (`providers.py`). It receives the command, the visible objects and their states, what MILO holds, memories, saved skills, lessons from past failures, and the action registry. It must answer in a strict JSON schema (`plan.py`) with exactly one of:
   - a plan: a goal in plain words, checkable success predicates, and ordered registry actions;
   - one clarifying question;
   - a plain "impossible" reason.

   The providers are:
   - `ClaudeProvider`: Anthropic SDK, `claude-opus-5-5`, structured outputs, refusal fallbacks, 30 s timeout, 2 retries, cached.
   - `OfflineProvider`: says "I can't work out new tasks offline".
   - `ScriptedProvider`: for tests and demos.
3. **Validate before acting** (`validate.py`). It rejects:
   - unknown or non-executable actions, and steps the constraints forbid;
   - objects that aren't in the scene;
   - plans over the step budget;
   - impossible orderings, found by a symbolic run of the registry's preconditions and effects from the simulator's own state.

   Where the only problems are "go there first" or "already done", it repairs the plan into the closest feasible one and says what it changed. Any other problem goes back to the model with the reasons, within the call budget, or ends with "Could you say it another way?".
4. **Safety** (`safety.py`, `config/novel_constraints.json`):
   - an action allowlist and forbidden actions/objects;
   - risky actions (`push`, `put_down`), fragile objects and dangerous objects;
   - budgets per task: 20 steps, 4 model calls, 90 s, 3 probes.

   A risky step stops with "Before I do this I need your OK, because the egg is fragile and could break if I push it." Phase 4 adds the approve/skip buttons.
5. **Run through the orchestrator.** A novel task gets the same execution, reflection, replanning, narration and traces as any other. The plan's own success predicates are **always enforced**: if every step "worked" but a predicate is false (e.g. the fridge was left open), MILO replans and tells the model why.
6. **Exploration fallback.** From the third attempt on, MILO safely probes the failed target (open, switch on/off, close; never risky or forbidden actions; at most 3 probes), records what changed, and gives that to the planner.
7. **Learning** (`skills.py`). A success is stored as a parameterised skill. It starts as a candidate and becomes trusted after 3 successes on at least 2 different object sets. A failure is stored as a short lesson ("tried [...] -> why") that the planner sees next time. Both live in `data/skills.db` and are mirrored into MILO's memory.

Flags: `MILO_NOVEL_SOLVER=0` turns the path off. `MILO_NOVEL_PROVIDER=claude|offline`, `MILO_NOVEL_MODEL` and `MILO_NOVEL_TIMEOUT` choose and tune the provider. With no Anthropic credentials, unknown commands keep their immediate "I can't do that yet" reply, because a novel run could only fail.

## Evaluation (`python -m novel.eval_novel`, `make eval-novel`)

60 held-out commands in a fixed synthetic home: 30 new verb/object combinations, 15 multi-step compositions, 8 ambiguous requests (right answer: one question) and 7 impossible requests (right answer: a plain refusal without acting).

| Planner source | Correct | Doable tasks done | Ambiguous -> asked | Impossible -> declined | Model calls / task |
|---|---|---|---|---|---|
| Before Phase 2 (refuse unknown) | 0 / 60 | 0% | 0% | 0% | 0 |
| Novel path, offline | 0 / 60 | 0% | 0% | 0% | 1 (fails fast) |
| Novel path, reference plans | 60 / 60 | 100% | 100% | 100% | 1 |
| Novel path, Claude | **not run**: no Anthropic credentials in this environment | | | | |

- **Caught before acting:** 10 of 10 deliberately bad plans. They cover a forbidden action, a missing object, a missing receptacle, place-before-pickup, a closed container, picking up two things, over the step budget, two risky steps, and a success condition on a missing object.
- **Unsafe actions executed:** 0. Nothing outside the allowlist can reach the executor, and risky steps need the user's OK.
- **Second attempt** (same wording, different object, 10 pairs): 100% succeeded. All 10 reused the saved skill, cutting model calls from 1 to 0. The "chill the X" skill became trusted after its third success.

**Read the reference row carefully.** It uses hand-written correct plans, so it measures everything *except* the model's planning ability: the schema, validation, safety gate, execution, goal checks and skill learning. It is an upper bound for the pipeline, not a result for an LLM. The real zero-shot number needs `MILO_NOVEL_PROVIDER=claude python -m novel.eval_novel --claude` with credentials. That run costs real API calls (about 60 to 120 requests) and has not been done.

Known limits:
- The second attempt is "faster" in model calls, not in wall time. In the synthetic simulator a planning call costs nothing; with a real model it is the slow part.
- Exploration only triggers on the replan path. A fault that the reflector answers with retries and then an abort (a door that stays stuck) never reaches it.
- Skill matching is by exact wording pattern, not meaning.

## With a free local model: error analysis on the DEV set (qwen2.5:7b, 2026-11-26)

These are failures on the 30 DEV commands only (`backend/novel/dev_set.py`, a different room from the TEST set), from the bake-off with qwen2.5:7b (Q4_K_M via Ollama, temperature 0). They were used to improve the prompt; the TEST set was not looked at. 14 of the 30 commands failed in the first run:

| Cause | Failures | Example (DEV) |
|---|---|---|
| **Success conditions that can't match the plan** | 4 | "light up the corner": the steps were right (`turn_on lamp`), but the success condition was "lamp is_open", which a lamp can never be, so the world check rejected a mission that worked. The same happened with "silence the radio" (`is_closed` instead of `toggled_off`). |
| **Acting instead of asking or refusing** | 5 | "deal with that" got an 11-step plan moving lettuce and bread to the sink, instead of one question. "sing me a song" switched the radio on. "walk the dog" filled in a question and a refusal, and added steps. |
| **Missing or misplaced steps in longer plans** | 4 | "stash the watch in the safe and leave the pillow on the bed": the pillow was "placed" without being picked up. "peek in the cooler" went to the cooler without first locating it. The "container" field was put on `locate` and `pickup`. |
| Invalid JSON (answer cut off at the length cap) | 1 | "crack the safe open, then carry the pen around with you" |

**Changes, tuned on DEV only:**
- The system prompt now gives explicit rules: ask when the command doesn't say what or where; refuse without acting when nothing can do it; locate, navigate, then act; `container` only for `place`; and which success condition goes with which action (`turn_on` → `toggled_on`, and so on).
- One more DEV example joins the few-shot set ("light up the corner", a switch with `toggled_on`).
- The safety side held throughout: no invented action (`walk`, `throw`) ever reached the simulator, because the validator rejects anything outside the registry.

**Effect on DEV** (3 runs each, spread 0): correct 55.6% → 76.7%, valid JSON 95% → 100%, 12.2 → 9.2 s per command. One caveat: "light up the corner" is now both a few-shot example and one of the 30 DEV commands, so about 3 points of the gain are self-inflicted. TEST is the number that counts.

## Prompt v3: decide before planning (2026-11-26)

The TEST failures below (prompt v2) were mostly commands that should get a question or a refusal and got a plan. The plan schema lists `goal`, `success` and `steps` before `question` and `impossible`, and the model writes JSON in that order, so it has committed to a plan before it reaches the fields for asking or refusing. **Prompt v3** (`backend/novel/providers.py`, now the default; `MILO_OLLAMA_PROMPT=v2` restores the old one) makes the answer start with `"decision": "plan" | "ask" | "refuse"`, and code keeps only the part the decision chose: a reply that asks or refuses can't also act.

**Tuned on DEV only.** DEV had 3 ambiguous and 3 impossible commands, 2 of them few-shot examples, too few to tune on, so 5 of each were added (DEV is now 40 commands; `tests/test_novel_dev_split.py` still checks it shares no command, phrasing, leading verb or object type with TEST). qwen2.5:7b, 3 runs each, every run identical (`results/bakeoff/dev40_prompt_*`):

| DEV (40 commands) | Overall | New combinations | Compositions | Ambiguous | Impossible | s/command |
|---|---|---|---|---|---|---|
| v2 (before) | 60% | 17/18 | 4/6 | 1/8 | 2/8 | 9.3 |
| **v3: decide first** | **70%** | 16/18 | 4/6 | 3/8 | 5/8 | 9.0 |
| v4: list what the command names, then decide; naming nothing forces a question | 55% | 13/18 | 1/6 | 8/8 | 0/8 | 6.0 |

v4 overcorrected (it asked about everything ambiguous but refused nothing and broke simple tasks), so it was dropped and its code removed. Only these two variants were tried, to limit tuning to DEV noise.

**TEST, run once with v3** (60 held-out commands, seeds 0-2, `results/novel_local/prompt_v3/`):

| TEST | v2 (before) | **v3** |
|---|---|---|
| **Correct overall** | 73.3% (44/60, spread 0) | **80.6%** (49, 48, 48 of 60; spread 1.7 pts) |
| New verb/object combinations | 30/30 | 30, 29, 29 of 30 |
| Multi-step compositions | 13/15 | 13/15 |
| Ambiguous: asks one question | 0/8 | **2/8** |
| Impossible: refuses without acting | 1/7 | **4/7** |
| Goal checks passed, doable tasks | 95.6% | 94.1% |
| Unsafe actions executed | 0 | 0 |
| Model calls per task | 1.34 | 1.39 |
| Time per task | 10.3 s | 11.1 s |

**Read honestly:** v3 is better by 7 points, almost all of it from refusing (1 → 4 of 7) and asking (0 → 2 of 8). Asking is still poor: 6 of 8 ambiguous commands on TEST still get a plan, and the plan approval step in the app (`docs/oversight.md`) remains the real guard against those. One new-combination command that passed with v2 fails in 2 of 3 v3 runs.

## With a free local model: the TEST set (qwen2.5:7b, prompt v2, 2026-11-26)

`make novel-eval`, run once after tuning: the 60 held-out commands, qwen2.5:7b Q4_K_M via Ollama, temperature 0, seeds 0-2. All three runs gave the same result, so the spread is 0. **This is a local model, not Claude;** Claude has still not been run.

| Measure | qwen2.5:7b | Offline (no model) | Reference plans (upper bound) |
|---|---|---|---|
| **Correct overall** | **73.3%** (44/60) | 0% | 100% |
| New verb/object combinations | 100% (30/30) | 0% | 100% |
| Multi-step compositions | 86.7% (13/15) | 0% | 100% |
| Ambiguous: asks one question | **0%** (0/8) | 0% | 100% |
| Impossible: refuses without acting | **14%** (1/7) | 0% | 100% |
| Goal checks passed, doable tasks | 95.6% | 0% | 100% |
| Unsafe actions executed | **0** | 0 | 0 |
| Model calls per task | 1.34 | – | 1 |
| Time per task | 10.3 s | – | – |
| Tasks that needed a repair round and then succeeded | 5 | – | – |

**What the failures are** (16 per run, the same 16 each time):

- **Ambiguous commands get a plan instead of a question (8 of 8).** "put it over there" got a 6-step plan, and "switch it" switched something. The prompt rule from the DEV analysis did not fix this on TEST.
- **Impossible commands mostly get a plan (6 of 7).** "fix the television" switched the TV on, "call my mum" and "water the garden" did something unrelated. In 2 of the 7 ("fly to the ceiling", "paint the wall blue") the model did not act: it said it couldn't and offered an alternative. That's reasonable, but the benchmark asks for a plain refusal, so they count as wrong.
- **2 compositions failed**: one plan placed the egg before picking it up (the validator caught it, nothing ran), and one 20-step plan ran but missed a goal.

None of these failures ran an unsafe action: the validator only lets registry actions through. In the app there is a second guard this benchmark leaves out on purpose: every plan MILO works out itself is shown for approval before it runs (`docs/oversight.md`), so a made-up plan for "put it over there" would be seen and stopped. The table measures the model alone.

**Skill learning with the local model** (same runs):

| Experiment | Success | Model calls | Time | Used the saved skill |
|---|---|---|---|---|
| First attempt (10 commands) | 100% | 1.3 | 8.6 s | – |
| The same command again | 100% | **0.2** | **1.5 s** | 80% |
| Transfer: same wording, another object | 90% | 0.5 | 3.1 s | 80% |
| Composition: "chill the apple and make the room dark" after learning both parts | 3 of 3 | 1 (no saving) | 9.1 s (vs 8.6 s without skills) | no |

Skills curve, "chill the X" over six objects in a row: model calls 1, 0, 0, 0, 0, 0; every mission succeeded; the skill went from candidate to trusted after the third object.

**Did not improve:** composing two learned skills still needs a model call and saves no time. The model plans the combined command from scratch rather than calling the two skills.