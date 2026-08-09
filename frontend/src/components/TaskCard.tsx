// TaskCard.tsx
//
// Purpose
// -------
// Renders one `SingleTask` as labeled structured fields (goal, object,
// target, locations, attributes, constraints, ...) rather than a raw
// JSON dump -- this is Phase 3.7's "parser visualization" requirement
// (`backend/docs/language_interface_spec.md` section 26.6): letting a
// researcher visually audit a parser result at a glance. Used both
// directly (a `SingleTask` response) and once per entry when rendering
// a `MultiTask`'s `subtasks` (see `ResultView.tsx`) -- the Planner
// treats every subtask as a `SingleTask` (per `schemas/task.py`), and
// this component mirrors that by having exactly one rendering for
// either case.
import type { SingleTask } from "../api/types";

interface TaskCardProps {
  task: SingleTask;
  /** Rendered as "Task N" above the card when part of a MultiTask. */
  index?: number;
}

function Field({ label, value }: { label: string; value?: string | null }) {
  if (!value) {
    return null;
  }
  return (
    <div className="task-card__field">
      <span className="task-card__field-label">{label}</span>
      <span className="task-card__field-value">{value}</span>
    </div>
  );
}

function ListField({ label, values }: { label: string; values?: string[] | null }) {
  if (!values || values.length === 0) {
    return null;
  }
  return (
    <div className="task-card__field">
      <span className="task-card__field-label">{label}</span>
      <ul className="task-card__field-list">
        {values.map((value) => (
          <li key={value}>{value}</li>
        ))}
      </ul>
    </div>
  );
}

export function TaskCard({ task, index }: TaskCardProps) {
  const attributes = task.attributes;
  const hasAttributes =
    attributes &&
    (attributes.color ||
      attributes.size ||
      attributes.material ||
      attributes.state ||
      attributes.quantity ||
      (attributes.descriptors && attributes.descriptors.length > 0));

  return (
    <div className="task-card">
      {index !== undefined && <p className="task-card__index">Task {index}</p>}
      <div className="task-card__grid">
        <Field label="Goal" value={task.goal?.toUpperCase()} />
        <Field label="Object" value={task.object?.toUpperCase()} />
        <Field label="Target" value={task.target?.toUpperCase()} />
        <Field label="Source Location" value={task.source_location} />
        <Field label="Target Location" value={task.target_location} />
        <Field label="Priority" value={task.priority ?? undefined} />
      </div>

      {hasAttributes && (
        <div className="task-card__field">
          <span className="task-card__field-label">Attributes</span>
          <ul className="task-card__field-list">
            {attributes?.color && <li>Color: {attributes.color}</li>}
            {attributes?.size && <li>Size: {attributes.size}</li>}
            {attributes?.material && <li>Material: {attributes.material}</li>}
            {attributes?.state && <li>State: {attributes.state}</li>}
            {attributes?.quantity && <li>Quantity: {attributes.quantity}</li>}
            {attributes?.descriptors?.map((descriptor) => (
              <li key={descriptor}>{descriptor}</li>
            ))}
          </ul>
        </div>
      )}

      {task.constraints && task.constraints.length > 0 && (
        <div className="task-card__field">
          <span className="task-card__field-label">Constraints</span>
          <ul className="task-card__field-list">
            {task.constraints.map((constraint, i) => (
              <li key={i}>
                [{constraint.constraint_type}] {constraint.description}
              </li>
            ))}
          </ul>
        </div>
      )}

      <ListField label="Preconditions" values={task.preconditions} />
      <ListField label="Postconditions" values={task.postconditions} />
      <Field label="Estimated Outcome" value={task.estimated_goal} />

      <div className="task-card__status">
        {task.needs_clarification ? (
          <span className="task-card__status-badge task-card__status-badge--warning">
            ⚠ Needs Clarification
          </span>
        ) : (
          <span className="task-card__status-badge task-card__status-badge--ok">
            ✓ Parsed
          </span>
        )}
      </div>
    </div>
  );
}
