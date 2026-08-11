# MILO State System

Living reference for `MiloState` and `MiloStateContext` (Phase 8.3,
extended in Phase 8.5 Stage 2). Previously only touched in passing by
`docs/phases/phase8_2_ui_report.md` (a point-in-time completion
report) -- this document tracks the actual current implementation and
should be updated whenever `frontend/src/state/miloState.ts` or
`MiloStateContext.tsx` changes.

## Source of truth

- `frontend/src/state/miloState.ts` -- the `MiloState` type, the
  `MiloVisual` → asset mapping, state labels/descriptions.
- `frontend/src/state/MiloStateContext.tsx` -- the single place that
  derives one canonical `MiloState` from every other real-time context
  (`TaskContext`, `VoiceContext`, `SpeechContext`, `AgentsContext`).
  No other component computes MILO's state independently.

## The 15 logical states

```
offline · initializing · idle · listening · understanding · thinking
planning · perceiving · navigating · executing · replanning
reflecting · speaking · success · error
```

Only **7 real character images** exist
(`frontend/public/assets/milo/milo-{idle,listening,thinking,speaking,executing,success,error}.png`),
so `VISUAL_FOR_STATE` (`miloState.ts`) maps each of the 15 logical
states onto whichever of the 7 images communicates it best (e.g.
`understanding`/`planning`/`replanning`/`reflecting` all render the
`thinking` image; `navigating` renders the `executing` image;
`offline`/`initializing` render the `idle` image, dimmed via CSS).
This mapping is intentional and one-time -- a new logical state added
later must get an explicit entry, never fall through by accident.

## Precedence chain

`MiloStateContext`'s `state` is a `useMemo` recomputed every render
from four real inputs, checked in this order (first match wins):

```mermaid
flowchart TD
    A[voice.state === "speaking"?] -->|yes| SPEAKING[speaking]
    A -->|no| B[speech.state === "listening"?]
    B -->|yes| LISTENING[listening]
    B -->|no| C["speech.state is processing/transcribing?"]
    C -->|yes| UNDERSTANDING[understanding]
    C -->|no| D["holding success/error for the active task?"]
    D -->|yes| HOLD["success or error (transient)"]
    D -->|no| E["active task, non-terminal status?"]
    E -->|yes| TASKMAP["STATE_FOR_TASK_STATUS[status]"]
    E -->|no| F[agents offline?]
    F -->|yes| OFFLINE[offline]
    F -->|no| G["agents status loading/idle?"]
    G -->|yes| INIT[initializing]
    G -->|no| IDLE[idle]
```

1. **`voice.state === "speaking"`** (`VoiceContext`) -- MILO is
   audibly speaking via ElevenLabs TTS. Highest precedence: if MILO is
   talking, that's what's shown regardless of what the task is doing
   underneath.
2. **`speech.state`** (`SpeechContext`, mic capture) -- `"listening"`
   maps directly to `listening`; `"processing"`/`"transcribing"` both
   map to `understanding`.
3. **Task status hold** -- once the active task reaches `succeeded`/
   `failed`, that display holds for `SUCCESS_HOLD_MS` (4000ms) /
   `ERROR_HOLD_MS` (6000ms) — a real `window.setTimeout` over a real
   terminal status, not a fabricated animation — then reverts to idle
   (or sooner, if a new task starts first).
4. **Active task status** (`TaskContext`, non-terminal) -- mapped via
   `STATE_FOR_TASK_STATUS` (table below).
5. **Agents/offline fallback** -- `offline` if `AgentsContext`
   reports a genuine connectivity failure (not the common
   `agents_unavailable` 503, which means "backend reachable, no
   orchestrator running yet" — see `MiloStateContext.tsx`'s
   `isOffline` derivation, which mirrors `NavBar.tsx`'s
   `deriveConnectionState`); `initializing` while agent status is
   still loading; otherwise `idle`.

## `TaskStatus` → `MiloState` mapping

Every value is a real `TaskStatus` enum member
(`backend/agents/task_state.py`) — nothing here is invented:

| `TaskStatus` | `MiloState` |
|---|---|
| `created` | `initializing` |
| `parsing` | `understanding` |
| `retrieving_memory` | `thinking` |
| `planning` | `planning` |
| `executing` | `executing` |
| `reflecting` | `reflecting` |
| `replanning` | `replanning` |
| `succeeded` | `success` (via the hold timer) |
| `failed` | `error` (via the hold timer) |
| `cancelled` | `idle` |

## Interruption/cancellation and MILO state (Phase 8.5 Stage 2)

`MiloStateContext` itself holds no state that could get "stuck" — it
recomputes from its four real inputs on every render, so as soon as
`SpeechContext`/`VoiceContext` reset (e.g. after `stop()` or a
cancelled recording), the derived state updates on the next render.
The state system was never the source of interruption bugs; the fixes
landed in the two contexts it reads from:

- **`SpeechContext`** now guards `handleRecordingStopped()` with a
  generation counter (mirroring `usePolling.ts`'s pattern) so a stale
  transcription request from an earlier recording can never overwrite
  a newer recording's `state`/`transcript` — and, by extension, can
  never push `MiloState` into a stale `understanding`/`error` display.
- **`VoiceContext`** now exposes `stop()` (pauses audio, reverts
  `state` to `idle` if currently `speaking`) — used for barge-in: when
  the user starts a new recording while MILO is still speaking,
  `TalkToMilo.tsx` calls `voice.stop()` first, so `MiloState` moves
  cleanly from `speaking` to `listening` rather than both being true
  at once (the precedence order already made `speaking` win over
  `listening`, which is why an explicit stop is needed for the mic
  click to actually show `listening`).

## Consuming `MiloState`

`useMiloState()` is the only supported way to read it — throws if
called outside `<MiloStateProvider>`. Never derive a page-local
approximation of MILO's state from `TaskContext`/`VoiceContext`/
`SpeechContext` directly; always go through this context so every
`MiloAvatar`/`MiloStateIndicator` instance across the app agrees.
