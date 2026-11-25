// SkillsPage.tsx -- what MILO has learned or been taught: status, success rate, last
// used, and rename / enable-disable / delete. Plus "Teach MILO": a name, the words
// that should trigger it, and the steps in plain words.
import { useCallback, useEffect, useState } from "react";

import { ApiError } from "../api/client";
import { deleteSkill, editSkill, listSkills, readableWording, teachSkill } from "../api/skills";
import type { Skill } from "../api/skills";
import { useTask } from "../state/useTask";

const STATUS_LABEL: Record<Skill["status"], string> = {
  teaching: "being checked",
  candidate: "learning",
  trusted: "trusted",
  disabled: "switched off",
};

function lastUsed(ts: number | null): string {
  if (!ts) return "never";
  const days = Math.floor((Date.now() / 1000 - ts) / 86400);
  return days <= 0 ? "today" : days === 1 ? "yesterday" : `${days} days ago`;
}

function message(error: unknown, fallback: string): string {
  return error instanceof ApiError ? error.message : fallback;
}

function SkillRow({ skill, onChange }: { skill: Skill; onChange: () => void }) {
  const [renaming, setRenaming] = useState(false);
  const [name, setName] = useState(skill.name);
  const [problem, setProblem] = useState<string | null>(null);
  const act = async (fn: () => Promise<unknown>) => {
    try {
      await fn();
      setProblem(null);
      onChange();
    } catch (error) {
      setProblem(message(error, "That didn't work. Is MILO's server running?"));
    }
  };
  const rate = skill.success_rate === null ? "not tried yet" : `${Math.round(skill.success_rate * 100)}% worked`;
  return (
    <li className="card library__item" aria-label={`Skill ${skill.name}`}>
      {renaming ? (
        <span className="ask__row">
          <input className="input" aria-label="New name" value={name} onChange={(e) => setName(e.target.value)} />
          <button type="button" className="btn btn--go" onClick={() => void act(() => editSkill(skill.skill_id, { name })).then(() => setRenaming(false))}>
            Save
          </button>
        </span>
      ) : (
        <strong>{skill.name}</strong>
      )}{" "}
      <span className="pill">{STATUS_LABEL[skill.status]}</span>
      <p className="muted">
        Say "{readableWording(skill.wording)}" · {skill.steps.length} steps · {rate} ({skill.successes} of{" "}
        {skill.successes + skill.failures}) · last used {lastUsed(skill.last_used)}
      </p>
      <div className="filters">
        {!renaming && (
          <button type="button" className="filter" onClick={() => setRenaming(true)}>
            Rename
          </button>
        )}
        <button
          type="button"
          className="filter"
          onClick={() =>
            void act(() => editSkill(skill.skill_id, { status: skill.status === "disabled" ? "candidate" : "disabled" }))
          }
        >
          {skill.status === "disabled" ? "Switch on" : "Switch off"}
        </button>
        <button
          type="button"
          className="filter"
          onClick={() => {
            if (window.confirm(`Forget "${skill.name}"? This can't be undone.`)) void act(() => deleteSkill(skill.skill_id));
          }}
        >
          Delete
        </button>
      </div>
      {problem && <div className="notice notice--error" role="alert">{problem}</div>}
    </li>
  );
}

function TeachForm({ onTaught }: { onTaught: () => void }) {
  const { setActiveTaskId } = useTask();
  const [name, setName] = useState("");
  const [wording, setWording] = useState("");
  const [steps, setSteps] = useState("");
  const [busy, setBusy] = useState(false);
  const [reply, setReply] = useState<{ text: string; bad: boolean } | null>(null);
  const submit = async () => {
    setBusy(true);
    try {
      const lines = steps.split("\n").map((s) => s.trim()).filter(Boolean);
      const result = await teachSkill(name.trim(), wording.trim(), lines);
      setReply({ text: result.message, bad: false });
      if (result.task) setActiveTaskId(result.task.task_id);
      setName("");
      setWording("");
      setSteps("");
      onTaught();
    } catch (error) {
      setReply({ text: message(error, "I couldn't learn that. Is MILO's server running?"), bad: true });
    } finally {
      setBusy(false);
    }
  };
  const ready = name.trim() && wording.trim() && steps.trim();
  return (
    <section className="card" aria-label="Teach MILO">
      <h2>Teach MILO</h2>
      <p className="muted">Give it a name, the words you'll use, and the steps one per line. MILO will try it once to show you.</p>
      <label htmlFor="teach-name">Name</label>
      <input id="teach-name" className="input" value={name} placeholder="Set the table" onChange={(e) => setName(e.target.value)} />
      <label htmlFor="teach-wording">What you'll say</label>
      <input
        id="teach-wording"
        className="input"
        value={wording}
        placeholder="set the mug on the table"
        onChange={(e) => setWording(e.target.value)}
      />
      <label htmlFor="teach-steps">Steps</label>
      <textarea
        id="teach-steps"
        className="input"
        rows={4}
        value={steps}
        placeholder={"pick up the mug\nput it on the table"}
        onChange={(e) => setSteps(e.target.value)}
      />
      <button type="button" className="btn btn--go" disabled={!ready || busy} onClick={() => void submit()}>
        {busy ? "Learning..." : "Teach"}
      </button>
      {reply && (
        <div className={`notice${reply.bad ? " notice--error" : ""}`} role={reply.bad ? "alert" : "status"}>
          {reply.text}
        </div>
      )}
    </section>
  );
}

export function SkillsPage() {
  const [skills, setSkills] = useState<Skill[] | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const load = useCallback(() => {
    listSkills()
      .then((s) => {
        setSkills(s);
        setProblem(null);
      })
      .catch(() => setProblem("I couldn't load my skills. Is MILO's server running?"));
  }, []);
  useEffect(load, [load]);
  return (
    <div className="legacy-page">
      <section className="card">
        <h1>Skills</h1>
        <p className="muted">Things MILO has learned to do. A skill becomes trusted after it has worked a few times with different things.</p>
        {problem && <div className="notice notice--error" role="alert">{problem}</div>}
        {skills === null && !problem && <p className="muted">Checking my skills...</p>}
        {skills?.length === 0 && <p>No skills yet. Teach one below, or save a mission that went well.</p>}
        <ul className="library" aria-label="Skills">
          {skills?.map((s) => <SkillRow key={s.skill_id} skill={s} onChange={load} />)}
        </ul>
      </section>
      <TeachForm onTaught={load} />
    </div>
  );
}
