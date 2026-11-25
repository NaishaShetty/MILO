// settingsDefaults.ts -- the settings a new browser starts with.
import type { MiloSettings } from "./SettingsContext";

export const DEFAULT_SETTINGS: MiloSettings = {
  general: { nickname: "", theme: "dark", compactMode: false, startPage: "/" },
  speech: { preferredMicDeviceId: null },
  notifications: { taskCompletionEnabled: false },
};
