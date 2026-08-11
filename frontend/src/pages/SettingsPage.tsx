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
import { SettingsIcon } from "../components/SettingsIcons";
import type { SettingsIconName } from "../components/SettingsIcons";
import { StatusPill } from "../components/StatusPill";
import { getLanguageStatus } from "../api/language";
import type { LanguageStatus } from "../api/types";
import { getSpeechStatus } from "../api/speech";
import type { SpeechStatus } from "../api/speechTypes";
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

// The real categories `SettingsPage` renders below, in order -- the
// sidebar is a jump-nav over those same sections (every section stays
// mounted; see SettingsPage.test.tsx's "renders all ten settings
// categories," which asserts all eleven `region`s exist at once), not a
// tab switcher that would hide sections the tests (and screen readers)
// expect to find simultaneously.
const CATEGORIES: Array<{ id: string; label: string; icon: SettingsIconName }> = [
  { id: "general", label: "General", icon: "general" },
  { id: "personality", label: "MILO Personality", icon: "personality" },
  { id: "speech", label: "Speech & Voice", icon: "speech" },
  { id: "llm", label: "LLM Provider", icon: "llm" },
  { id: "vision", label: "Vision", icon: "vision" },
  { id: "memory", label: "Memory", icon: "memory" },
  { id: "planning", label: "Planning & Execution", icon: "planning" },
  { id: "notifications", label: "Notifications", icon: "notifications" },
  { id: "privacy", label: "Data & Privacy", icon: "privacy" },
  { id: "integrations", label: "Integrations", icon: "integrations" },
  { id: "about", label: "About", icon: "about" },
];

export function SettingsPage() {
  const { settings, updateGeneral, updateSpeech, updateNotifications, clearLocalData } = useSettings();
  const { history } = useTask();
  const [clearConfirmed, setClearConfirmed] = useState(false);
  const [voiceStatus, setVoiceStatus] = useState<VoiceStatus | null>(null);
  const [languageStatus, setLanguageStatus] = useState<LanguageStatus | null>(null);
  const [speechStatus, setSpeechStatus] = useState<SpeechStatus | null>(null);
  const [activeCategory, setActiveCategory] = useState<string>(CATEGORIES[0].id);

  function jumpTo(id: string) {
    setActiveCategory(id);
    document.getElementById(`settings-${id}`)?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

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

  useEffect(() => {
    let cancelled = false;
    getLanguageStatus()
      .then((status) => {
        if (!cancelled) setLanguageStatus(status);
      })
      .catch(() => {
        // Real, honest failure: leave languageStatus null -> rendered as "Checking..." below.
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    getSpeechStatus()
      .then((status) => {
        if (!cancelled) setSpeechStatus(status);
      })
      .catch(() => {
        // Real, honest failure: leave speechStatus null -> rendered as "Checking..." below.
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
      <header className="settings-page__header">
        <h1>Settings</h1>
        <p className="settings-page__subtitle">
          Configure how MILO looks, thinks, remembers, and behaves.
        </p>
      </header>

      <div className="settings-page__layout">
        <nav className="settings-page__nav" aria-label="Settings categories">
          {CATEGORIES.map((category) => (
            <button
              key={category.id}
              type="button"
              className={
                "settings-page__nav-item" +
                (activeCategory === category.id ? " settings-page__nav-item--active" : "")
              }
              onClick={() => jumpTo(category.id)}
            >
              <SettingsIcon name={category.icon} />
              <span>{category.label}</span>
            </button>
          ))}
        </nav>

        <div className="settings-page__grid">
          <div id="settings-general" className="settings-page__anchor">
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
          </div>

          <div id="settings-personality" className="settings-page__anchor">
          <GlassCard title="MILO Personality" className="settings-page__card">
          <section aria-label="MILO Personality" className="settings-page__section">
            <p>
              MILO refers to itself as <strong>{settings.general.nickname || "MILO"}</strong> in
              conversation. There is no additional personality configuration yet -- this is the
              only personality-related setting the app currently supports.
            </p>
          </section>
          </GlassCard>
          </div>

          <div id="settings-speech" className="settings-page__anchor">
          <GlassCard title="Speech & Voice" className="settings-page__card">
          <section aria-label="Speech & Voice" className="settings-page__section">
            <p>
              The active speech-to-text backend transcribes microphone audio server-side; this
              page only shows its real configured status (see the "STT provider" pill below) --
              set via the backend's <code>STT_PROVIDER</code> environment variable, not from here.
            </p>
            <label htmlFor="settings-mic-device">Preferred microphone device ID (optional)</label>
            <input
              id="settings-mic-device"
              type="text"
              value={settings.speech.preferredMicDeviceId ?? ""}
              onChange={(event) => updateSpeech({ preferredMicDeviceId: event.target.value || null })}
              placeholder="Leave blank to use the browser's default microphone"
            />

            <div className="settings-page__voice-status">
              <span>STT provider (speech input)</span>
              {speechStatus ? (
                <StatusPill tone={speechStatus.available ? "success" : "neutral"} dot>
                  {speechStatus.provider} — {speechStatus.available ? "Available" : speechStatus.enabled ? "Configured, unavailable" : "Disabled"}
                </StatusPill>
              ) : (
                <StatusPill tone="neutral">Checking...</StatusPill>
              )}
            </div>

            <div className="settings-page__voice-status">
              <span>Voice output provider (ElevenLabs TTS)</span>
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
          </div>

          <div id="settings-llm" className="settings-page__anchor">
          <GlassCard title="LLM Provider" className="settings-page__card">
          <section aria-label="LLM Provider" className="settings-page__section">
            <p className="settings-page__readonly-note">
              Read-only -- set via the backend's <code>LANGUAGE_LLM_PROVIDER</code> environment
              variable (openai, gemini, or qwen). The API key is never sent to this page.
            </p>
            <div className="settings-page__voice-status">
              <span>Active provider</span>
              {languageStatus ? (
                <StatusPill tone={languageStatus.configured ? "success" : "neutral"} dot>
                  {languageStatus.provider} — {languageStatus.configured ? "Connected" : "Not configured"}
                </StatusPill>
              ) : (
                <StatusPill tone="neutral">Checking...</StatusPill>
              )}
            </div>
            {languageStatus && <p className="settings-page__readonly-note">Model: {languageStatus.model}</p>}
          </section>
          </GlassCard>
          </div>

          <div id="settings-vision" className="settings-page__anchor">
          <GlassCard title="Vision" className="settings-page__card">
          <section aria-label="Vision" className="settings-page__section">
            <p className="settings-page__readonly-note">Read-only -- no vision configuration endpoint exists yet.</p>
            <p>Depth source and detection results are shown live per-perception in Mission Control.</p>
          </section>
          </GlassCard>
          </div>

          <div id="settings-memory" className="settings-page__anchor">
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
          </div>

          <div id="settings-planning" className="settings-page__anchor">
          <GlassCard title="Planning & Execution" className="settings-page__card">
          <section aria-label="Planning & Execution" className="settings-page__section">
            <p className="settings-page__readonly-note">Read-only -- no planner configuration endpoint exists yet.</p>
            <p>Current planner: {latestPlannerType ?? "unknown (no task has run yet)"}</p>
          </section>
          </GlassCard>
          </div>

          <div id="settings-notifications" className="settings-page__anchor">
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
          </div>

          <div id="settings-privacy" className="settings-page__anchor">
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
          </div>

          <div id="settings-integrations" className="settings-page__anchor">
          <GlassCard title="Integrations" className="settings-page__card">
          <section aria-label="Integrations" className="settings-page__section">
            <p>No external integrations configured.</p>
          </section>
          </GlassCard>
          </div>

          <div id="settings-about" className="settings-page__anchor">
          <GlassCard title="About" className="settings-page__card">
          <section aria-label="About" className="settings-page__section">
            <dl>
              <dt>MILO frontend version</dt>
              <dd>{APP_VERSION}</dd>
            </dl>
          </section>
          </GlassCard>
          </div>
        </div>
      </div>
    </main>
  );
}
