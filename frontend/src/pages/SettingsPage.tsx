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
// cards.
//
// ElevenLabs (Phase 8.2): `Speech & Voice` now shows the real backend
// config via `GET /api/v1/voice` (provider, voice ID, enabled/
// available) -- never the API key, which the backend itself never
// exposes (see `voice/config.py`'s security note). Actually speaking/
// listening through ElevenLabs is wired in Stage 4; this section shows
// real status now rather than nothing.
//
// Phase 8.2 visual pass: every category is still simultaneously
// rendered (kept for accessibility/testability -- see
// SettingsPage.test.tsx's "renders all nine settings categories"),
// now as a GlassCard grid instead of a plain vertical stack.
import { useEffect, useState } from "react";

import { GlassCard } from "../components/GlassCard";
import { StatusPill } from "../components/StatusPill";
import { getVoiceStatus } from "../api/voice";
import type { VoiceStatus } from "../api/voiceTypes";
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
  const [voiceStatus, setVoiceStatus] = useState<VoiceStatus | null>(null);

  useEffect(() => {
    let cancelled = false;
    getVoiceStatus()
      .then((status) => {
        if (!cancelled) setVoiceStatus(status);
      })
      .catch(() => {
        // Real, honest failure: leave voiceStatus null -> rendered as "unavailable" below.
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const latestPlannerType = history.find((task) => task.current_plan)?.current_plan?.planner_type ?? null;

  function handleClear() {
    clearLocalData();
    setClearConfirmed(true);
  }

  return (
    <main aria-label="Settings" className="settings-page">
      <h1>Settings</h1>

      <div className="settings-page__grid">
        <GlassCard title="General" className="settings-page__card">
          <section aria-label="General" className="settings-page__section">
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
        </GlassCard>

        <GlassCard title="MILO Personality" className="settings-page__card">
          <section aria-label="MILO Personality" className="settings-page__section">
            <p>
              MILO refers to itself as <strong>{settings.general.nickname || "MILO"}</strong> in
              conversation. There is no additional personality configuration yet -- this is the
              only personality-related setting the app currently supports.
            </p>
          </section>
        </GlassCard>

        <GlassCard title="Speech & Voice" className="settings-page__card">
          <section aria-label="Speech & Voice" className="settings-page__section">
            <p>Whisper transcribes speech server-side; the frontend only captures microphone audio.</p>
            <label htmlFor="settings-mic-device">Preferred microphone device ID (optional)</label>
            <input
              id="settings-mic-device"
              type="text"
              value={settings.speech.preferredMicDeviceId ?? ""}
              onChange={(event) => updateSpeech({ preferredMicDeviceId: event.target.value || null })}
              placeholder="Leave blank to use the browser's default microphone"
            />

            <div className="settings-page__voice-status">
              <span>Voice output provider</span>
              {voiceStatus ? (
                <>
                  <StatusPill tone={voiceStatus.available ? "success" : "neutral"} dot>
                    {voiceStatus.provider} — {voiceStatus.available ? "Available" : voiceStatus.enabled ? "Configured, no API key" : "Disabled"}
                  </StatusPill>
                  <p className="settings-page__readonly-note">Voice ID: {voiceStatus.voice_id}</p>
                </>
              ) : (
                <StatusPill tone="neutral">Checking...</StatusPill>
              )}
            </div>
          </section>
        </GlassCard>

        <GlassCard title="Vision" className="settings-page__card">
          <section aria-label="Vision" className="settings-page__section">
            <p className="settings-page__readonly-note">Read-only -- no vision configuration endpoint exists yet.</p>
            <p>Depth source and detection results are shown live per-perception in Mission Control.</p>
          </section>
        </GlassCard>

        <GlassCard title="Memory" className="settings-page__card">
          <section aria-label="Memory" className="settings-page__section">
            <p className="settings-page__readonly-note">Read-only -- no memory configuration endpoint exists yet.</p>
            <ul>
              {Object.entries(MEMORY_CATEGORY_LABELS).map(([type, label]) => (
                <li key={type}>{label}</li>
              ))}
            </ul>
          </section>
        </GlassCard>

        <GlassCard title="Planning & Execution" className="settings-page__card">
          <section aria-label="Planning & Execution" className="settings-page__section">
            <p className="settings-page__readonly-note">Read-only -- no planner configuration endpoint exists yet.</p>
            <p>Current planner: {latestPlannerType ?? "unknown (no task has run yet)"}</p>
          </section>
        </GlassCard>

        <GlassCard title="Notifications" className="settings-page__card">
          <section aria-label="Notifications" className="settings-page__section">
            <label>
              <input
                type="checkbox"
                checked={settings.notifications.taskCompletionEnabled}
                onChange={(event) => updateNotifications({ taskCompletionEnabled: event.target.checked })}
              />
              Notify me when a mission completes or fails
            </label>
          </section>
        </GlassCard>

        <GlassCard title="Data & Privacy" className="settings-page__card">
          <section aria-label="Data & Privacy" className="settings-page__section">
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
        </GlassCard>

        <GlassCard title="Integrations" className="settings-page__card">
          <section aria-label="Integrations" className="settings-page__section">
            <p>No external integrations configured.</p>
          </section>
        </GlassCard>

        <GlassCard title="About" className="settings-page__card">
          <section aria-label="About" className="settings-page__section">
            <dl>
              <dt>MILO frontend version</dt>
              <dd>{APP_VERSION}</dd>
            </dl>
          </section>
        </GlassCard>
      </div>
    </main>
  );
}
