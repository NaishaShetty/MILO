// ModelsPanel.tsx -- Lab: which learned models are active, their version and
// latest metrics, the shadow-mode comparison, health/drift, and a toggle per model
// with the fallback behaviour explained.
import { useEffect, useState } from "react";

import { getModels, setOutcomeMode } from "../api/lab";
import type { ModelStatus } from "../api/lab";

const MODES: Array<{ id: NonNullable<ModelStatus["mode"]>; label: string }> = [
  { id: "off", label: "Off" },
  { id: "shadow", label: "Shadow" },
  { id: "on", label: "On" },
];

export function ModelsPanel() {
  const [models, setModels] = useState<ModelStatus[] | null>(null);
  const [problem, setProblem] = useState<string | null>(null);

  useEffect(() => {
    getModels()
      .then((r) => setModels(r.models))
      .catch(() => setProblem("I couldn't load the models list. Is MILO's server running?"));
  }, []);

  async function choose(mode: NonNullable<ModelStatus["mode"]>) {
    try {
      setModels((await setOutcomeMode(mode)).models);
      setProblem(null);
    } catch {
      setProblem("I couldn't change that. Start the simulator and try again.");
    }
  }

  return (
    <section className="card" aria-label="Learned models">
      <h2>Models</h2>
      {problem && <div className="notice notice--error" role="alert">{problem}</div>}
      {models === null && !problem && <p className="muted">Checking the models...</p>}
      {models?.map((model) =>
        model.mode === undefined ? (
          <div key={model.name} className="library__item">
            <strong>{model.title}</strong>{" "}
            <span className="pill">{!model.available ? "not trained yet" : model.enabled ? "on" : "off"}</span>
            {model.headline && <p className="muted">{model.headline}</p>}
            <p className="muted">{model.explains}</p>
          </div>
        ) : (
        <div key={model.name} className="library__item">
          <strong>{model.title}</strong>{" "}
          <span className="pill">{model.available ? `version ${model.version}` : "not trained yet"}</span>
          {model.metrics && model.trained_on != null && (
            <p className="muted">
              Trained on {model.trained_on} steps ({model.date}). Held-out scenes: AUROC {model.metrics.auroc.toFixed(3)}, calibration error{" "}
              {model.metrics.ece.toFixed(3)}.
            </p>
          )}
          <div className="filters" role="group" aria-label={`${model.title} mode`}>
            {MODES.map((m) => (
              <button
                key={m.id}
                type="button"
                className="filter"
                aria-pressed={model.mode === m.id}
                disabled={!model.available && m.id !== "off"}
                onClick={() => void choose(m.id)}
              >
                {m.label}
              </button>
            ))}
          </div>
          <p className="muted">{model.explains}</p>
          {model.shadow && model.shadow.compared > 0 && (
            <p>
              Shadow comparison: the model agreed with the built-in rules on {model.shadow.agree} of {model.shadow.compared} decisions
              {model.shadow.fallbacks > 0 ? `; fell back ${model.shadow.fallbacks} times` : ""}.
            </p>
          )}
          {model.latency && (
            <p className="muted">
              Speed: typical {model.latency.p50_ms.toFixed(1)} ms, slowest 5% {model.latency.p95_ms.toFixed(1)} ms.
            </p>
          )}
          {model.drift_score != null && (
            <p className="muted">Input drift: {model.drift_score.toFixed(2)} (the model is set aside above 2.5).</p>
          )}
          {model.problem && <div className="notice notice--error">Using the built-in rules because: {model.problem}.</div>}
        </div>
        ),
      )}
    </section>
  );
}
