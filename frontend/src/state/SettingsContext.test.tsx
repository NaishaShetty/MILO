// SettingsContext.test.tsx
import { renderHook, act } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import { DEFAULT_SETTINGS, SettingsProvider, useSettings } from "./SettingsContext";

beforeEach(() => {
  window.localStorage.clear();
  document.documentElement.removeAttribute("data-theme");
  document.documentElement.classList.remove("milo-compact");
});

describe("SettingsContext", () => {
  it("starts from defaults when nothing is stored", () => {
    const { result } = renderHook(() => useSettings(), { wrapper: SettingsProvider });
    expect(result.current.settings).toEqual(DEFAULT_SETTINGS);
  });

  it("updateGeneral merges into settings and persists to localStorage", () => {
    const { result } = renderHook(() => useSettings(), { wrapper: SettingsProvider });

    act(() => {
      result.current.updateGeneral({ nickname: "Robo", compactMode: true });
    });

    expect(result.current.settings.general.nickname).toBe("Robo");
    expect(result.current.settings.general.compactMode).toBe(true);
    const stored = JSON.parse(window.localStorage.getItem("milo:settings")!);
    expect(stored.general.nickname).toBe("Robo");
  });

  it("applies theme/compact preferences to the document root", () => {
    const { result } = renderHook(() => useSettings(), { wrapper: SettingsProvider });

    act(() => {
      result.current.updateGeneral({ theme: "light", compactMode: true });
    });

    expect(document.documentElement.getAttribute("data-theme")).toBe("light");
    expect(document.documentElement.classList.contains("milo-compact")).toBe(true);
  });

  it("clearLocalData resets settings and removes the localStorage entry", () => {
    const { result } = renderHook(() => useSettings(), { wrapper: SettingsProvider });

    act(() => {
      result.current.updateGeneral({ nickname: "Robo" });
    });
    act(() => {
      result.current.clearLocalData();
    });

    expect(result.current.settings).toEqual(DEFAULT_SETTINGS);
    expect(window.localStorage.getItem("milo:settings")).toBeNull();
  });

  it("recovers gracefully from corrupt localStorage content", () => {
    window.localStorage.setItem("milo:settings", "{not json");
    const { result } = renderHook(() => useSettings(), { wrapper: SettingsProvider });
    expect(result.current.settings).toEqual(DEFAULT_SETTINGS);
  });
});
