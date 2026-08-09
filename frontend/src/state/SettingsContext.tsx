// SettingsContext.tsx
//
// Purpose
// -------
// Frontend-only settings state, persisted to `localStorage` -- this is
// the *only* persistence layer for Settings (spec: "only persist
// settings the application actually supports"). No backend settings
// endpoint exists anywhere in `backend/api/routes/`, so nothing here
// claims to configure the server; `SettingsPage.tsx` is explicit in
// its own copy about which sections are locally-editable vs.
// read-only display of backend-reported values.
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import type { ReactNode } from "react";

const STORAGE_KEY = "milo:settings";

export type ThemePreference = "dark" | "light" | "system";
export type StartPage = "/" | "/mission-control" | "/memory" | "/activity" | "/about" | "/lab" | "/settings";

export interface MiloSettings {
  general: {
    nickname: string;
    theme: ThemePreference;
    compactMode: boolean;
    startPage: StartPage;
  };
  speech: {
    preferredMicDeviceId: string | null;
  };
  notifications: {
    taskCompletionEnabled: boolean;
  };
}

export const DEFAULT_SETTINGS: MiloSettings = {
  general: { nickname: "", theme: "dark", compactMode: false, startPage: "/" },
  speech: { preferredMicDeviceId: null },
  notifications: { taskCompletionEnabled: false },
};

function loadSettings(): MiloSettings {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return DEFAULT_SETTINGS;
    const parsed = JSON.parse(raw) as Partial<MiloSettings>;
    return {
      general: { ...DEFAULT_SETTINGS.general, ...parsed.general },
      speech: { ...DEFAULT_SETTINGS.speech, ...parsed.speech },
      notifications: { ...DEFAULT_SETTINGS.notifications, ...parsed.notifications },
    };
  } catch {
    // Corrupt/foreign localStorage content -- never crash the app over it.
    return DEFAULT_SETTINGS;
  }
}

export interface SettingsContextValue {
  settings: MiloSettings;
  updateGeneral: (patch: Partial<MiloSettings["general"]>) => void;
  updateSpeech: (patch: Partial<MiloSettings["speech"]>) => void;
  updateNotifications: (patch: Partial<MiloSettings["notifications"]>) => void;
  /** Clears locally-stored settings/preferences only -- never touches backend data. */
  clearLocalData: () => void;
}

const SettingsContext = createContext<SettingsContextValue | null>(null);

export function SettingsProvider({ children }: { children: ReactNode }) {
  const [settings, setSettings] = useState<MiloSettings>(() => loadSettings());

  // Each updater below persists synchronously alongside its own
  // `setSettings` call (rather than a separate `useEffect` watching
  // `settings`) so `clearLocalData()` can remove the storage key
  // without a subsequent render's effect immediately re-writing
  // defaults back into it.
  function persist(next: MiloSettings): MiloSettings {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
    return next;
  }

  useEffect(() => {
    const root = document.documentElement;
    root.setAttribute(
      "data-theme",
      settings.general.theme === "system" ? "" : settings.general.theme,
    );
    root.classList.toggle("milo-compact", settings.general.compactMode);
  }, [settings.general.theme, settings.general.compactMode]);

  const updateGeneral = useCallback((patch: Partial<MiloSettings["general"]>) => {
    setSettings((previous) => persist({ ...previous, general: { ...previous.general, ...patch } }));
  }, []);

  const updateSpeech = useCallback((patch: Partial<MiloSettings["speech"]>) => {
    setSettings((previous) => persist({ ...previous, speech: { ...previous.speech, ...patch } }));
  }, []);

  const updateNotifications = useCallback(
    (patch: Partial<MiloSettings["notifications"]>) => {
      setSettings((previous) =>
        persist({ ...previous, notifications: { ...previous.notifications, ...patch } }),
      );
    },
    [],
  );

  const clearLocalData = useCallback(() => {
    window.localStorage.removeItem(STORAGE_KEY);
    setSettings(DEFAULT_SETTINGS);
  }, []);

  const value = useMemo<SettingsContextValue>(
    () => ({ settings, updateGeneral, updateSpeech, updateNotifications, clearLocalData }),
    [settings, updateGeneral, updateSpeech, updateNotifications, clearLocalData],
  );

  return <SettingsContext.Provider value={value}>{children}</SettingsContext.Provider>;
}

export function useSettings(): SettingsContextValue {
  const context = useContext(SettingsContext);
  if (!context) {
    throw new Error("useSettings() must be used within a <SettingsProvider>.");
  }
  return context;
}
