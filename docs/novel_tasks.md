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
