// InstructionForm.tsx
//
// Purpose
// -------
// The single text-entry point for this Phase 3.7 UI: lets a user type
// a natural language instruction and submit it. Knows nothing about
// HTTP, the API contract, or what a "task" looks like -- it only
// reports the submitted string upward via `onSubmit`, so this
// component stays reusable regardless of how the caller chooses to
// handle the result (see `App.tsx`, this project's "UI components
// must not know about the API client's internals" boundary applied to
// input as well as output).
import { useState, type FormEvent } from "react";

interface InstructionFormProps {
  onSubmit: (instruction: string) => void;
  isLoading: boolean;
}

export function InstructionForm({ onSubmit, isLoading }: InstructionFormProps) {
  const [instruction, setInstruction] = useState("");

  function handleSubmit(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    const trimmed = instruction.trim();
    if (!trimmed || isLoading) {
      return;
    }
    onSubmit(trimmed);
  }

  return (
    <form className="instruction-form" onSubmit={handleSubmit}>
      <label htmlFor="instruction-input" className="instruction-form__label">
        Natural language instruction
      </label>
      <textarea
        id="instruction-input"
        className="instruction-form__input"
        placeholder="Bring me the red mug."
        value={instruction}
        onChange={(event) => setInstruction(event.target.value)}
        rows={3}
        disabled={isLoading}
      />
      <button
        type="submit"
        className="instruction-form__submit"
        disabled={isLoading || !instruction.trim()}
      >
        {isLoading ? "Parsing..." : "Parse"}
      </button>
    </form>
  );
}
