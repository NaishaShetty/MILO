// DiagnosticsPanel.tsx
//
// Purpose
// -------
// Optionally renders the safe diagnostics the backend attaches to a
// successful parse (`ParseResponse.diagnostics`, see
// `backend/api/models/language.py`'s `ParseDiagnostics`) -- provider,
// model, prompt/schema version, attempt count, latency, and whether
// recovery fired. Every field here is already guaranteed
// credential-free by the backend (see that model's Security note);
// this component adds no filtering of its own, it only formats.
import type { ParseDiagnostics } from "../api/types";

interface DiagnosticsPanelProps {
  diagnostics: ParseDiagnostics;
}

export function DiagnosticsPanel({ diagnostics }: DiagnosticsPanelProps) {
  return (
    <dl className="diagnostics-panel" aria-label="Parse diagnostics">
      {diagnostics.provider && (
        <div className="diagnostics-panel__item">
          <dt>Provider</dt>
          <dd>{diagnostics.provider}</dd>
        </div>
      )}
      {diagnostics.model && (
        <div className="diagnostics-panel__item">
          <dt>Model</dt>
          <dd>{diagnostics.model}</dd>
        </div>
      )}
      {diagnostics.latency_ms != null && (
        <div className="diagnostics-panel__item">
          <dt>Latency</dt>
          <dd>{Math.round(diagnostics.latency_ms)} ms</dd>
        </div>
      )}
      <div className="diagnostics-panel__item">
        <dt>Attempts</dt>
        <dd>{diagnostics.attempt_count}</dd>
      </div>
      {diagnostics.recovered && (
        <div className="diagnostics-panel__item">
          <dt>Recovered</dt>
          <dd>Yes</dd>
        </div>
      )}
    </dl>
  );
}
