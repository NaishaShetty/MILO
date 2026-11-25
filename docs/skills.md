# Teaching MILO skills (roadmap 2, Phase 3)

A skill is a plan that worked, stored with its objects as placeholders so it works with other things: "set the mug on the table" is stored as `set the {o0} on the {o1}`. Skills live in `data/skills.db` (`backend/novel/skills.py`). They are shown on the **Skills** page and served at `/api/v1/skills`.

## Three ways to get one

1. **Learned on its own.** A novel task that succeeds (Phase 2) is saved automatically.
2. **Save as skill.** After any mission that succeeds, the Missions page offers "Save as skill" with an editable name. The skill stores:
   - the final plan's steps;
   - the success conditions that were checked at the end;
   - the mission's own words as the trigger wording.

   (`POST /api/v1/skills/from-task/{task_id}`)
3. **Teach MILO.** On the Skills page, give a name, the words you'll use, and the steps one per line ("pick up the mug", "put it on the table"). "it", "them" and "that" mean the last thing mentioned.
   - Each line is understood by MILO's own phrasebook, and the lines are planned together against the current room.
   - Success is the end state, so a step's condition is dropped when a later step changes it.
   - The skill is saved as *being checked*, and MILO immediately runs it once to show what it understood. It becomes a real (*learning*) skill when that run succeeds.

   (`POST /api/v1/skills/teach`)

## Using skills

- Saying a sentence with a skill's wording runs it with the new objects, through the normal orchestrator with goal checks. This works **without a language model**: the API routes any command that matches a saved, switched-on skill to the novel planner.
- A skill becomes **trusted** after 3 successes on at least 2 different sets of objects.
- **Chaining:** a skill step can call another skill: `{"action": "skill:shelve", "target": "{o0}"}`. The language-model planner can also use skills as high-level actions (`skill:<name>` in its plan); they are expanded before validation. Chains are limited to 3 levels, and a cycle (a skill that ends up calling itself) is refused when the skill is saved or edited.
- The Skills page lists each skill's status, how often it worked, and when it was last used. It also has **Rename**, **Switch off/on** and **Delete** (with confirmation). The API also accepts edited steps (`PATCH /api/v1/skills/{id}`), and those are re-checked for cycles.

## Acceptance (tests in `backend/tests/test_teach.py`)

- A skill taught as "set the mug on the table" in one room is run back successfully. It is then reused as "set the vase on the table" in a *different room*: other distances, no apple, a vase that wasn't there before. It runs from the skill with 0 model calls and no language model configured.
- A chained skill ("tidy the X and the Y", built from two calls to "shelve") runs end to end on new objects (tomato, bowl) and places both on the shelf.
- Cycles, unknown skills and chains deeper than 3 levels are refused with a plain reason.
- Over the API: teach -> run-back succeeds -> the status changes from teaching to candidate -> an ordinary command with the taught wording runs the skill offline; save-from-mission, rename, disable and delete also work.

Limits:
- "Teach by demonstration" means driving MILO through a mission and then using **Save as skill**. There is no separate step-by-step remote-control recorder.
- The rule-based, HTN and behaviour-tree planners don't call skills; only the novel/language-model planner treats skills as actions.
- Skill matching is by wording pattern, not meaning.
