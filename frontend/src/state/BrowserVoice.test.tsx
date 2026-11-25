// BrowserVoice.test.tsx -- the on/off switch, the fallback, speaking, listening, and
// turning spoken answers into decisions and choices.
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { BrowserVoiceProvider, useBrowserVoice } from "./BrowserVoice";
import { VoiceToggle } from "../components/VoiceToggle";
import { VoiceCoach } from "../components/VoiceCoach";
import * as tasksApi from "../api/tasks";
import { choiceFromSpeech, decisionFromSpeech, spokenQuestion } from "../utils/voiceAnswers";
import { directMilo } from "./miloDirector";

vi.mock("../api/tasks", async () => ({ ...(await vi.importActual<object>("../api/tasks")), decide: vi.fn() }));

class FakeRecognition {
  static heard = "yes go ahead";
  lang = "";
  interimResults = false;
  maxAlternatives = 1;
  onresult: ((e: unknown) => void) | null = null;
  onerror: ((e: unknown) => void) | null = null;
  onend: (() => void) | null = null;
  start() {
    setTimeout(() => {
      this.onresult?.({ results: [[{ transcript: FakeRecognition.heard }]] });
      this.onend?.();
    }, 0);
  }
  stop() {
    this.onend?.();
  }
}

function installSpeech() {
  const spoken: string[] = [];
  Object.assign(window, { webkitSpeechRecognition: FakeRecognition });
  class Utterance {
    onend: (() => void) | null = null;
    onerror: (() => void) | null = null;
    constructor(public text: string) {}
  }
  Object.assign(window, {
    SpeechSynthesisUtterance: Utterance,
    speechSynthesis: {
      cancel: vi.fn(),
      speak: (u: Utterance) => {
        spoken.push(u.text);
        setTimeout(() => u.onend?.(), 0);
      },
    },
  });
  return spoken;
}

afterEach(() => {
  const w = window as unknown as Record<string, unknown>;
  delete w.webkitSpeechRecognition;
  delete w.speechSynthesis;
  delete w.SpeechSynthesisUtterance;
  window.localStorage.clear();
});

describe("browser voice", () => {
  it("falls back with a plain message when the browser can't listen or speak", () => {
    render(
      <BrowserVoiceProvider>
        <VoiceToggle />
      </BrowserVoiceProvider>,
    );
    expect(screen.getByRole("checkbox", { name: "Talk with MILO" })).toBeDisabled();
    expect(screen.getByText(/can't listen or speak. Type to MILO instead./)).toBeInTheDocument();
  });

  it("is switched on and off, and the choice is remembered", () => {
    installSpeech();
    render(
      <BrowserVoiceProvider>
        <VoiceToggle />
      </BrowserVoiceProvider>,
    );
    const box = screen.getByRole("checkbox", { name: "Talk with MILO" });
    expect(box).not.toBeChecked();
    fireEvent.click(box);
    expect(box).toBeChecked();
    expect(window.localStorage.getItem("milo.browserVoice")).toBe("1");
  });

  it("listens (showing it) and returns what was heard", async () => {
    installSpeech();
    FakeRecognition.heard = "put the apple in the fridge";
    let heard = "";
    function Probe() {
      const v = useBrowserVoice();
      return (
        <>
          <button onClick={() => void v.listen().then((h) => (heard = h))}>listen</button>
          {v.listening && <span>listening now</span>}
        </>
      );
    }
    render(
      <BrowserVoiceProvider>
        <Probe />
      </BrowserVoiceProvider>,
    );
    fireEvent.click(screen.getByText("listen"));
    expect(screen.getByText("listening now")).toBeInTheDocument();
    await waitFor(() => expect(heard).toBe("put the apple in the fridge"));
  });

  it("says an approval request out loud and approves on 'yes'", async () => {
    const spoken = installSpeech();
    window.localStorage.setItem("milo.browserVoice", "1");
    FakeRecognition.heard = "yes go ahead";
    vi.mocked(tasksApi.decide).mockResolvedValue({} as never);
    await act(async () => {
      render(
        <BrowserVoiceProvider>
          <VoiceCoach taskId="t1" pending={{ kind: "step", why: "the toaster could be dangerous", text: "Turning on the toaster." }} />
        </BrowserVoiceProvider>,
      );
    });
    await waitFor(() => expect(tasksApi.decide).toHaveBeenCalledWith("t1", "approve"));
    expect(spoken[0]).toContain("I'm asking because the toaster could be dangerous");
  });

  it("asks a clarifying question out loud and picks the answer that was said", async () => {
    installSpeech();
    window.localStorage.setItem("milo.browserVoice", "1");
    FakeRecognition.heard = "the one on the table";
    const onChoice = vi.fn();
    const choices = [
      { label: "the cup on the shelf", instruction: "x", object_id: "Cup|1" },
      { label: "the cup on the table", instruction: "x", object_id: "Cup|2" },
    ];
    await act(async () => {
      render(
        <BrowserVoiceProvider>
          <VoiceCoach question="Which cup?" choices={choices} onChoice={onChoice} />
        </BrowserVoiceProvider>,
      );
    });
    await waitFor(() => expect(onChoice).toHaveBeenCalledWith(choices[1]));
  });
});

describe("spoken answers and MILO's states", () => {
  it("understands yes / skip / cancel and choices", () => {
    expect(decisionFromSpeech("yeah do it", "step")).toBe("approve");
    expect(decisionFromSpeech("no, skip that", "step")).toBe("skip");
    expect(decisionFromSpeech("no thanks", "plan")).toBe("cancel");
    expect(decisionFromSpeech("never mind", "step")).toBe("cancel");
    expect(decisionFromSpeech("hmm", "step")).toBeNull();
    expect(choiceFromSpeech("the fridge one", [{ label: "in the fridge" }, { label: "on the table" }])).toEqual({ label: "in the fridge" });
    expect(choiceFromSpeech("whatever", [{ label: "in the fridge" }])).toBeNull();
    expect(spokenQuestion({ kind: "plan", why: "x" })).toContain("Shall I go ahead?");
  });

  it("gives MILO distinct poses for asking, waiting, figuring out and recovering", () => {
    expect(directMilo(null, "Which cup?", true).pose).toBe("asking");
    const base = { task_id: "t", status: "executing", thoughts: [], failures: [], current_plan: null, current_step: null } as never;
    expect(directMilo({ ...(base as object), pending_decision: { kind: "step", why: "w", text: "x" } } as never).pose).toBe("waiting");
    expect(directMilo({ ...(base as object), pending_decision: { kind: "plan", why: "w" } } as never).pose).toBe("thinking");
    expect(directMilo({ ...(base as object), status: "replanning", failures: [{}] } as never).pose).toBe("recovering");
    expect(directMilo({ ...(base as object), status: "planning" } as never).pose).toBe("thinking");
  });
});
