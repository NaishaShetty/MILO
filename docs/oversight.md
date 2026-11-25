# Ask before guessing, approve, and undo (roadmap 2, Phase 4)

Code: `backend/oversight/`. API: `backend/api/routes/tasks.py`. UI: Play page answer chips, and the Missions page `DecisionCard`, "No, the other one" and Undo.

## Ask before guessing

- **Which one?** If a command names something the room has more than one of ("put the cup on the sofa" with two cups) and nothing picks one out, MILO doesn't guess.
  - It asks one question: "I can see 2 cups. Which one do you mean?"
  - The answers are tappable choices described by where each object is ("the cup on the shelf", "the cup on the table").
  - Each choice is pinned to the real simulator object (`object_id`), so the answer is exact.
- **Where to?** "Put the mug away" with no remembered place now comes with the room's places as choices ("in the fridge", "on the shelf"...).
- **"No, the other one."** While a mission runs or after it, this button stops it and redoes it with the other matching object (`POST /tasks/{id}/correct`).

## Approve risky steps

Before a risky step MILO stops and asks "Can I do this?", with the reason. A step is risky when it involves:
- a dangerous object (toaster, knife, microwave...);
- a risky action (`push`, `put_down`), which is also marked "I can't undo this";
- a fragile object with a risky action.

These come from `config/novel_constraints.json`. "Yes, go ahead" runs the step and "Skip that step" leaves it out; the executor marks it skipped and it never reaches the simulator.

With **no answer within the timeout, the step is skipped**: MILO never does a risky thing by default. Stopping the mission also releases the question. Ordinary steps are never held up.

## Plan preview

A plan MILO **worked out itself** (a novel task planned by the language model) is shown before anything moves:
- "Go ahead" runs it;
- unticking steps then "Go ahead with N steps" runs an edited plan;
- "Cancel" stops with nothing done.

A plan from a saved skill or an ordinary planner runs straight away.

## Undo

Every completed step records the state just before it, and Undo plays the inverse actions back, newest first:
- open ↔ close and switch on ↔ off;
- picking up or placing something puts it back where it was before the mission.

Undo shows what it will do first, including anything it **can't** undo (push, put down), before you confirm.

The undo runs through the normal orchestrator. Its success conditions are the "before" state, so the world decides whether it worked: after "put the apple in the fridge", the apple must be back on the table and the fridge closed. The undo's own steps go through the same risk gate (switching a toaster off asks too).

Flags: `MILO_APPROVALS=0` turns the gate and preview off. `MILO_APPROVAL_TIMEOUT` (default 300 s) sets how long MILO waits for an answer.

## Acceptance (backend `tests/test_oversight.py`, frontend `DecisionCard.test.tsx`, `MissionsPage.test.tsx`)

- An ambiguous command ("put the cup on the sofa", two cups) returns one question with two choices. Choosing "the cup on the table" moves exactly that cup; the other stays on the shelf.
- A risky step ("turn on the toaster") waits with nothing done.
  - Approve: it runs.
  - Skip: it never runs.
  - No answer: it never runs.
  - Stopping releases the wait.
- A worked-out plan is previewed. A step can be left out, and a cancelled preview changes nothing.
- Undo after "put the apple in the fridge" restores the apple to the table and closes the fridge, checked against the simulator. Over the API, undo of "turn on the toaster" (after approving both) leaves it off.

Limits:
- Only the first plan of a novel task is previewed, not replans.
- "Edit a step" means leaving steps out, not rewriting them.
- Undo can't restore something that was pushed or put down, and says so.
- The correction button appears for missions pinned to a specific object.
