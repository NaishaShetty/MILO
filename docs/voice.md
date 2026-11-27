# Voice (roadmap 2, Phase 8)

MILO can listen and talk using the **browser's own** speech recognition and speech synthesis: no server and no key. Code: `frontend/src/state/BrowserVoice.tsx`, `components/VoiceToggle.tsx`, `components/VoiceCoach.tsx`, `utils/voiceAnswers.ts`.

- **On/off switch:** "Talk with MILO" on the Play page. It's off by default and remembered between visits.
- **Listening:** with voice on, the microphone button uses browser recognition. While it listens MILO switches to his listening pose ("I'm listening...") and a "Listening..." badge shows. What was heard is sent as the instruction. With voice off or unsupported, the button uses the existing record-and-transcribe path through the server.
- **Spoken questions:** when MILO asks something back ("I can see 2 cups. Which one do you mean?"), it says the question aloud and listens for the answer. Saying the words of a choice ("the one on the table") picks it, matched by shared words.
- **Spoken approvals:** when MILO waits for an OK on a risky step, it says the step and why, then listens.
  - "Yes / go ahead / do it" approves.
  - "No / skip" skips the step.
  - "Cancel / never mind" cancels.

  For a plan preview, "yes" goes ahead and "no" or "cancel" stops. The on-screen buttons keep working the whole time.
- **Fallback:** if the browser can't listen or speak, the switch is disabled and says so in plain words: "This browser can't listen or speak. Type to MILO instead." It handles listen-only and speak-only browsers too, and everything stays usable by typing and tapping.

## MILO's states

MILO now has a distinct pose for each moment the UI rules list, chosen from the real task state (`state/miloDirector.ts`):

| Moment | Pose |
|---|---|
| Listening to voice | listening (amber sound wave by his ear) |
| Figuring something out / showing a plan to approve | thinking |
| Asking a question back | **asking**: a question-mark bubble above his head |
| Waiting for approval of a risky step | **waiting**: a small clock above his head |
| Recovering after a failure (reflecting or replanning with failures) | **recovering**: a bobbing sweat drop |

The new marks animate gently and respect `prefers-reduced-motion`.

Tests (`frontend/src/state/BrowserVoice.test.tsx`, with stand-in speech APIs):
- the fallback message and disabled switch;
- the remembered on/off setting;
- listening, with its visible state;
- an approval spoken aloud and approved on "yes";
- a clarifying question answered by voice;
- the yes/skip/cancel and choice matching;
- the pose for each state.

**In a real browser** (`frontend/tests/e2e/browserVoice.spec.ts`, Chromium, run in CI): the switch and its remembered setting, a spoken command sent as a speech mission, an approval request said out loud and approved by a spoken "yes", and the fallback when the browser has no speech APIs. Chrome's recognition sends audio to Google's servers, so the test uses a stand-in recogniser that "hears" a fixed sentence and a stand-in speaker that records what MILO says. Everything between them is the real app. The record-and-transcribe path (voice off) is tested with Chromium's fake microphone in `microphone.spec.ts`.

The real-browser test found one bug: a command heard by browser voice was sent as typed text (`input_source: "text"`). It is now sent as `"speech"`, like the record-and-transcribe path.

**Not verified:** real speech recognition with a real microphone. Recognition quality depends on the browser: Chrome and Edge ship `webkitSpeechRecognition`; Firefox doesn't.

## Trying it yourself (5 minutes, Chrome or Edge)

Run the app (`make demo`, or backend and frontend as in the README), open the Play page and allow the microphone when asked.

1. Tick **Talk with MILO**. Reload the page: it should still be ticked.
2. Press **Talk to MILO** and say "put the apple in the fridge". "Listening..." shows while it listens; the mission should start and the page move to Missions.
3. Give a command with a risky step (for example "open the fridge" with approvals on). MILO should say the step and why out loud. Say "yes": the step should be approved. Try again and say "skip", then "cancel".
4. Say something unclear ("bring me the cup" with two cups in view). MILO should ask which one out loud; answer "the one on the table".
5. Untick **Talk with MILO**: the microphone should go back to record-and-transcribe through the server.
6. Open the same page in Firefox: the switch should be disabled with a plain reason.

Note what happened at each step, especially any word MILO misheard.
