// App.tsx
//
// Purpose
// -------
// Top-level component for the MILO application (Session 3 / Phase 7).
// Supersedes the earlier single-page Vision+Language dashboard (see
// git history / the old `App.test.tsx`) with the seven routed MILO
// pages the spec requires -- no Mission Detail page, exactly these
// seven: Home, Mission Control, Memory, Activity, About MILO, MILO
// Lab, Settings. The Vision/Language/Planner/Execution components and
// API modules this replaced are not deleted -- they're still used
// where they fit inside the new pages (e.g. `VisionPanel` inside
// Mission Control's "MILO's Eyes"/"Detected Objects"); only this
// top-level composition changes, per Session 3's explicit brief.
//
// Provider order (outermost first): Settings (theme must be known
// before anything renders), Agents, Task, Speech -- Speech is
// innermost since it's the only one that ever calls into Task
// (`submitInstruction`) from page code, not from another provider.
// `ErrorBoundary` wraps `<Routes>` only, not the providers themselves,
// so a render crash inside one page can't take down navigation.
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";

import { ErrorBoundary } from "./components/ErrorBoundary";
import { NavBar } from "./components/NavBar";
import { AgentsProvider } from "./state/AgentsContext";
import { SettingsProvider } from "./state/SettingsContext";
import { SpeechProvider } from "./state/SpeechContext";
import { TaskProvider } from "./state/TaskContext";
import { AboutPage } from "./pages/AboutPage";
import { ActivityPage } from "./pages/ActivityPage";
import { HomePage } from "./pages/HomePage";
import { LabPage } from "./pages/LabPage";
import { MemoryPage } from "./pages/MemoryPage";
import { MissionControlPage } from "./pages/MissionControlPage";
import { SettingsPage } from "./pages/SettingsPage";

export default function App() {
  return (
    <SettingsProvider>
      <AgentsProvider>
        <TaskProvider>
          <SpeechProvider>
            <BrowserRouter>
              <div className="milo-app">
                <NavBar />
                <ErrorBoundary>
                  <Routes>
                    <Route path="/" element={<HomePage />} />
                    <Route path="/mission-control" element={<MissionControlPage />} />
                    <Route path="/memory" element={<MemoryPage />} />
                    <Route path="/activity" element={<ActivityPage />} />
                    <Route path="/about" element={<AboutPage />} />
                    <Route path="/lab" element={<LabPage />} />
                    <Route path="/settings" element={<SettingsPage />} />
                    <Route path="*" element={<Navigate to="/" replace />} />
                  </Routes>
                </ErrorBoundary>
              </div>
            </BrowserRouter>
          </SpeechProvider>
        </TaskProvider>
      </AgentsProvider>
    </SettingsProvider>
  );
}
