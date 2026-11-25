// demo.ts -- demo mode: the hosted UI replays pre-recorded missions (frontend/public/demo,
// made by `python -m demo.record`) with no backend, simulator or GPU.
//
// On when built with VITE_DEMO=1, or opened with ?demo=1 (remembered), off with ?demo=0.

const KEY = "milo.demo";

export function isDemo(): boolean {
  if (typeof window === "undefined") return false;
  const q = new URLSearchParams(window.location.search).get("demo");
  if (q === "1") window.localStorage.setItem(KEY, "1");
  if (q === "0") window.localStorage.removeItem(KEY);
  return import.meta.env.VITE_DEMO === "1" || window.localStorage.getItem(KEY) === "1";
}

export async function demoJson<T>(path: string): Promise<T> {
  const response = await fetch(`/demo/${path}`);
  if (!response.ok) throw new Error(`demo file ${path} missing`);
  return (await response.json()) as T;
}

export interface DemoMission {
  id: string;
  title: string;
  about: string;
  outcome: string;
  task_text: string;
}

export const demoMissions = () => demoJson<DemoMission[]>("missions.json");
