// SettingsPage.tsx
//
// Purpose
// -------
// Settings, split into the spec's categories -- but only ever wiring a
// control to something the app actually supports. `General` persists
// to `localStorage` via `SettingsContext` and takes effect immediately
// (theme/compact mode). `Speech & Voice`/`Notifications`/`Data &
// Privacy` are real, local, browser-level controls. `Vision`/`Memory`/
// `Planning & Execution` have no backend settings endpoint (Session 3
// audit found none), so they're explicitly labeled read-only,
// displaying whatever real data is already available (e.g. the most
// recent task's planner type) rather than a toggle wired to nothing.
// `Integrations` says plainly that none exist -- no fake integration
// cards. ElevenLabs is deliberately not here at all: it's a Phase 8
// concern (spec: "Do NOT implement ElevenLabs here").
import { useState } from "react";

import { useTask } from "../state/TaskContext";
import { MEMORY_CATEGORY_LABELS } from "../utils/memory";
import type { StartPage, ThemePreference } from "../state/SettingsContext";
import { useSettings } from "../state/SettingsContext";

const START_PAGE_OPTIONS: Array<{ value: StartPage; label: string }> = [
  { value: "/", label: "Home" },
  { value: "/mission-control", label: "Mission Control" },
  { value: "/memory", label: "Memory" },
  { value: "/activity", label: "Activity" },
  { value: "/about", label: "About MILO" },
  { value: "/lab", label: "MILO Lab" },
  { value: "/settings", label: "Settings" },
];

const APP_VERSION = "3.8.0";

export function SettingsPage() {
  const { settings, updateGeneral, updateSpeech, updateNotifications, clearLocalData } = useSettings();
  const { history } = useTask();
  const [clearConfirmed, setClearConfirmed] = useState(false);

  const latestPlannerType = history.find((task) => task.current_plan)?.current_plan?.planner_type ?? null;

  function handleClear() {
    clearLocalData();
    setClearConfirmed(true);
  }

  return (
    <main aria-label="Settings" className="settings-page">
      <h1>Settings</h1>

      <section aria-label="General" className="settings-page__section">
        <h2>General</h2>
        <label htmlFor="settings-nickname">Nickname for MILO</label>
        <input
          id="settings-nickname"
          type="text"
          value={settings.general.nickname}
          onChange={(event) => updateGeneral({ nickname: event.target.value })}
          placeholder="MILO"
        />

        <label htmlFor="settings-theme">Theme</label>
        <select
          id="settings-theme"
          value={settings.general.theme}
          onChange={(event) => updateGeneral({ theme: event.target.value as ThemePreference })}
        >
          <option value="dark">Dark</option>
          <option value="light">Light</option>
          <option value="system">System</option>
        </select>

        <label>
          <input
            type="checkbox"
            checked={settings.general.compactMode}
            onChange={(event) => updateGeneral({ compactMode: event.target.checked })}
          />
          Compact mode
        </label>

        <label htmlFor="settings-start-page">Start page</label>
        <select
          id="settings-start-page"
          value={settings.general.startPage}
          onChange={(event) => updateGeneral({ startPage: event.target.value as StartPage })}
        >
          {START_PAGE_OPTIONS.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      </section>

      <section aria-label="MILO Personality" className="settings-page__section">
        <h2>MILO Personality</h2>
        <p>
          MILO refers to itself as <strong>{settings.general.nickname || "MILO"}</strong> in
          conversation. There is no additional personality configuration yet -- this is the only
          personality-related setting the app currently supports.
        </p>
      </section>

      <section aria-label="Speech & Voice" className="settings-page__section">
        <h2>Speech &amp; Voice</h2>
        <p>Whisper transcribes speech server-side; the frontend only captures microphone audio.</p>
        <label htmlFor="settings-mic-device">Preferred microphone device ID (optional)</label>
        <input
          id="settings-mic-device"
          type="text"
          value={settings.speech.preferredMicDeviceId ?? ""}
          onChange={(event) => updateSpeech({ preferredMicDeviceId: event.target.value || null })}
          placeholder="Leave blank to use the browser's default microphone"
        />
        <p className="settings-page__readonly-note">
          Voice output (text-to-speech / ElevenLabs) is not part of this release -- planned for a
          later phase.
        </p>
      </section>

      <section aria-label="Vision" className="settings-page__section">
        <h2>Vision</h2>
        <p className="settings-page__readonly-note">Read-only -- no vision configuration endpoint exists yet.</p>
        <p>Depth source and detection results are shown live per-perception in Mission Control.</p>
      </section>

      <section aria-label="Memory" className="settings-page__section">
        <h2>Memory</h2>
        <p className="settings-page__readonly-note">Read-only -- no memory configuration endpoint exists yet.</p>
        <ul>
          {Object.entries(MEMORY_CATEGORY_LABELS).map(([type, label]) => (
            <li key={type}>{label}</li>
          ))}
        </ul>
      </section>

      <section aria-label="Planning & Execution" className="settings-page__section">
        <h2>Planning &amp; Execution</h2>
        <p className="settings-page__readonly-note">Read-only -- no planner configuration endpoint exists yet.</p>
        <p>Current planner: {latestPlannerType ?? "unknown (no task has run yet)"}</p>
      </section>

      <section aria-label="Notifications" className="settings-page__section">
        <h2>Notifications</h2>
        <label>
          <input
            type="checkbox"
            checked={settings.notifications.taskCompletionEnabled}
            onChange={(event) => updateNotifications({ taskCompletionEnabled: event.target.checked })}
          />
          Notify me when a mission completes or fails
        </label>
      </section>

      <section aria-label="Data & Privacy" className="settings-page__section">
        <h2>Data &amp; Privacy</h2>
        <p>
          This only clears settings stored in your browser (nickname, theme, and similar
          preferences). It does not delete anything from MILO's backend -- tasks and memories
          created there are managed independently.
        </p>
        <button type="button" onClick={handleClear}>
          Clear local settings
        </button>
        {clearConfirmed && <p role="status">Local settings cleared.</p>}
      </section>

      <section aria-label="Integrations" className="settings-page__section">
        <h2>Integrations</h2>
        <p>No external integrations configured.</p>
      </section>

      <section aria-label="About" className="settings-page__section">
        <h2>About</h2>
        <dl>
          <dt>MILO frontend version</dt>
          <dd>{APP_VERSION}</dd>
        </dl>
      </section>
    </main>
  );
}
