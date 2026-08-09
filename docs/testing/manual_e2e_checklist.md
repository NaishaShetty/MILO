# MILO Manual End-to-End Checklist (Session 3 / Phase 7)

This checklist covers the eight end-to-end scenarios from the Session 3 brief
that require a **live backend with a real AI2-THOR simulator and a display**
(`VISION_ENABLE_SIMULATOR=true`) and, for the speech scenario, a real
microphone and a loaded Whisper model. Neither of those is available in the
environment this session's automated work ran in, so this checklist was
**not executed automatically** — run it manually before considering Phase 7
fully verified end-to-end.

Everything that *doesn't* require a simulator/display/microphone was already
verified automatically: 857 backend tests, 167 frontend tests (component +
integration, mocked backend), and a live smoke test of every reachable
endpoint against a real (simulator-disabled) backend process (see the
Session 3 summary for the exact requests/responses).

## Setup

```bash
# Terminal 1 — backend, with a real simulator
cd backend
VISION_ENABLE_SIMULATOR=true uvicorn api.app:app --reload

# Terminal 2 — frontend
cd frontend
npm run dev
```

Open the printed Vite URL (default `http://localhost:5173`).

## Test 1 — Text instruction creates a task

1. Open **Home**.
2. Type `Find the apple` into the instruction field, click **Send**.
3. **Expect:** the app navigates to **Mission Control**; "Current Mission"
   shows the request text and a status that progresses away from `created`.

## Test 2 — Speech instruction creates a task

1. Open **Home**, click the 🎤 button, grant microphone permission if
   prompted, speak an instruction (e.g. "find the apple"), click 🎤 again to
   stop.
2. **Expect:** status line shows `Transcribing with Whisper...`, then the
   transcript appears ("Heard: ..."), then the app navigates to **Mission
   Control** with a task created from that transcript (`input_source:
   "speech"` — check via the browser network tab or backend logs).

## Test 3 — Full task lifecycle

1. From Home or Mission Control, submit `Put the apple in the refrigerator.`
2. **Expect**, in order, on Mission Control: plan appears under "MILO's
   Plan" with steps; "MILO Status" shows agents transitioning through
   active/thinking states; "Detected Objects" (after a manual **Perceive**
   in "MILO's Eyes") shows real detections; status eventually reaches
   `succeeded` or `failed`; "Activity Feed" shows `TASK_CREATED` →
   `PLAN_CREATED` → ... → `TASK_COMPLETED`/`TASK_FAILED`.

## Test 4 — Failure recovery / replanning

1. Submit an instruction likely to hit a recoverable failure (e.g. asking
   for an object not in the current room, or unplug/move something first).
2. **Expect:** a failure appears in the task's events/failures; if the
   orchestrator replans, `REPLAN_TRIGGERED` appears in the Activity Feed and
   "MILO's Plan" updates; the task still reaches a terminal status.

## Test 5 — Cancellation

1. Submit a longer-running instruction.
2. While `status` is not yet terminal, click **Cancel Mission** on Mission
   Control.
3. **Expect:** the button disables/changes to "Cancelling...", then the
   page shows "Mission cancelled." and status is `cancelled`; the mission no
   longer appears as active on any page.

## Test 6 — Memory created and visible

1. Complete a task successfully (Test 3).
2. Open **Memory**.
3. **Expect:** "Memory Statistics" counts increase for the relevant type(s);
   the new memory's content appears under "Recent Memories" and, if
   semantic, "My Knowledge"; "Memory Timeline" lists it.

## Test 7 — Activity reflects real task events

1. After Test 3/4, open **Activity**.
2. **Expect:** the task's events appear in the feed; filtering by "Tasks",
   "Planning", "Execution", etc. narrows the list correctly; selecting an
   event shows its real Time/Agent/Event/Task/Metadata; **Export Log**
   downloads a JSON file containing exactly the currently filtered events.

## Test 8 — MILO Lab reflects real metrics

1. After running a few tasks (mix of success/failure/cancellation), open
   **MILO Lab**.
2. **Expect:** "Lab Stats" (tasks run, success rate, total actions, memories
   created, failures, replans, average task time) match what actually
   happened — cross-check a couple of numbers against Activity/Memory.
   "My Sandbox" mirrors whatever task is currently active on Mission
   Control. "Technical System Information" lists real registered agents.

## Notes

- If any step 503s with `execution_unavailable`/`agents_unavailable`, the
  simulator did not start — check the backend's startup logs for the
  AI2-THOR/Unity launch failure reason.
- Every page must show an explicit empty state (not a crash) before any task
  has run — this was already verified automatically in the frontend test
  suite (e.g. `HomePage.test.tsx`'s "No missions yet." case) but is worth a
  quick manual glance on first load.
