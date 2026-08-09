// VisionPromptForm.tsx
//
// Purpose
// -------
// Text-entry point for the Vision panel's detection prompt (e.g.
// "chair. table. mug. apple. bottle."), mirroring `InstructionForm.tsx`'s
// shape exactly (own local state, reports the submitted string upward
// via `onSubmit`, knows nothing about HTTP or the API contract) -- kept
// as a separate component rather than reusing `InstructionForm` since
// the two forms submit conceptually different things (a natural
// language goal vs. a Grounding DINO detection prompt) to different
// APIs, even though their shape happens to look similar today.
import { useState, type FormEvent } from "react";

interface VisionPromptFormProps {
  onSubmit: (prompt: string) => void;
  isLoading: boolean;
}

const DEFAULT_PROMPT = "chair. table. mug. apple. bottle. refrigerator.";

export function VisionPromptForm({ onSubmit, isLoading }: VisionPromptFormProps) {
  const [prompt, setPrompt] = useState(DEFAULT_PROMPT);

  function handleSubmit(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    const trimmed = prompt.trim();
    if (!trimmed || isLoading) {
      return;
    }
    onSubmit(trimmed);
  }

  return (
    <form className="vision-prompt-form" onSubmit={handleSubmit}>
      <label htmlFor="vision-prompt-input" className="vision-prompt-form__label">
        Detection prompt
      </label>
      <input
        id="vision-prompt-input"
        className="vision-prompt-form__input"
        type="text"
        placeholder={DEFAULT_PROMPT}
        value={prompt}
        onChange={(event) => setPrompt(event.target.value)}
        disabled={isLoading}
      />
      <button
        type="submit"
        className="vision-prompt-form__submit"
        disabled={isLoading || !prompt.trim()}
      >
        {isLoading ? "Perceiving..." : "Perceive"}
      </button>
    </form>
  );
}
