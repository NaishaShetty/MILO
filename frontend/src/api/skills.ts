// skills.ts -- skills MILO has learned or been taught (backend/api/routes/skills.py).
import { request } from "./client";
import type { TaskState } from "./tasksTypes";

export interface SkillStep {
  action: string;
  target?: string | null;
  container?: string | null;
}

export interface Skill {
  skill_id: string;
  name: string;
  /** The wording that triggers it, objects as {o0}, {o1}... */
  wording: string;
  status: "teaching" | "candidate" | "trusted" | "disabled";
  successes: number;
  failures: number;
  success_rate: number | null;
  last_used: number | null;
  steps: SkillStep[];
}

export async function listSkills(): Promise<Skill[]> {
  return (await request<{ skills: Skill[] }>("/api/v1/skills")).skills;
}

export async function editSkill(
  id: string,
  change: { name?: string; status?: "candidate" | "trusted" | "disabled"; steps?: SkillStep[] },
): Promise<Skill> {
  return request<Skill>(`/api/v1/skills/${id}`, { method: "PATCH", body: JSON.stringify(change) });
}

export async function deleteSkill(id: string): Promise<void> {
  await request(`/api/v1/skills/${id}`, { method: "DELETE" });
}

export async function saveTaskAsSkill(taskId: string, name: string, wording?: string): Promise<Skill> {
  return request<Skill>(`/api/v1/skills/from-task/${taskId}`, {
    method: "POST",
    body: JSON.stringify({ name, wording: wording || undefined }),
  });
}

export async function teachSkill(
  name: string,
  wording: string,
  steps: string[],
): Promise<{ skill: Skill; task: TaskState | null; message: string }> {
  return request("/api/v1/skills/teach", { method: "POST", body: JSON.stringify({ name, wording, steps }) });
}

/** "set the {o0} on the {o1}" -> "set the … on the …" for people. */
export function readableWording(wording: string): string {
  return wording.replace(/\{o\d+\}/g, "…");
}
