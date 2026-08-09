// ClarificationBanner.tsx
//
// Purpose
// -------
// Renders the "clarification required" state described in
// `backend/docs/language_interface_spec.md` section 30.6: the backend
// returned an otherwise-valid, successfully-parsed task whose model
// output flagged `needs_clarification=true`. This is deliberately NOT
// styled or treated as an error component (see `ErrorBanner.tsx`) --
// clarification is a normal, successful outcome of parsing an
// ambiguous instruction, not a failure of this system.
//
// This component intentionally does not offer clarification choices
// or a follow-up input -- Phase 3.7 explicitly excludes the
// conversational clarification loop (see this project's scope notes);
// it only surfaces `clarification_reason` verbatim, exactly as the
// Language Understanding runtime produced it.
interface ClarificationBannerProps {
  reason: string | null | undefined;
}

export function ClarificationBanner({ reason }: ClarificationBannerProps) {
  return (
    <div className="banner banner--clarification" role="status">
      <p className="banner__title">Clarification Required</p>
      <p className="banner__body">
        {reason ?? "The instruction is ambiguous and needs more detail."}
      </p>
    </div>
  );
}
