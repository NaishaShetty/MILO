import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";

import { ErrorBoundary } from "./components/ErrorBoundary";
import { NavBar } from "./components/NavBar";
import { AgentsProvider } from "./state/AgentsContext";
import { MiloStateProvider } from "./state/MiloStateContext";
import { SettingsProvider } from "./state/SettingsContext";
import { SpeechProvider } from "./state/SpeechContext";
import { TaskProvider } from "./state/TaskContext";
import { VoiceProvider } from "./state/VoiceContext";
import { AboutPage } from "./pages/AboutPage";
import { ModelsPanel } from "./components/ModelsPanel";
import { LabPage } from "./pages/LabPage";
import { MemoryPage } from "./pages/MemoryPage";
import { SkillsPage } from "./pages/SkillsPage";
import { LeaderboardPage } from "./pages/LeaderboardPage";
import { DemoPage } from "./pages/DemoPage";
import { isDemo } from "./api/demo";
import { ReplayPage } from "./pages/ReplayPage";
import { ObservabilityPanel } from "./components/ObservabilityPanel";
import { MissionsPage } from "./pages/MissionsPage";
import { PlayPage } from "./pages/PlayPage";
import { SettingsPage } from "./pages/SettingsPage";
import { BrowserVoiceProvider } from "./state/BrowserVoice";

// Four friendly spaces -- Play, Missions, Memory, Lab -- plus About and
// Settings under the gear and Activity as a drawer (see NavBar).
export default function App() {
  return (
    <SettingsProvider>
      <BrowserVoiceProvider>
      <AgentsProvider>
        <TaskProvider>
          <SpeechProvider>
            <VoiceProvider>
              <MiloStateProvider>
                <BrowserRouter>
                  <div className="milo-app">
                    <NavBar />
                    <ErrorBoundary>
                      <Routes>
                        <Route path="/" element={isDemo() ? <DemoPage /> : <PlayPage />} />
                        <Route path="/demo" element={<DemoPage />} />
                        <Route path="/missions" element={<MissionsPage />} />
                        <Route path="/mission-control" element={<Navigate to="/missions" replace />} />
                        <Route path="/memory" element={<MemoryPage />} />
                        <Route path="/skills" element={<SkillsPage />} />
                        <Route path="/leaderboard" element={<LeaderboardPage />} />
                        <Route path="/replay" element={<ReplayPage />} />
                        <Route path="/replay/:missionId" element={<ReplayPage />} />
                        <Route path="/lab" element={<div className="legacy-page"><ModelsPanel /><ObservabilityPanel /><LabPage /></div>} />
                        <Route path="/about" element={<div className="legacy-page"><AboutPage /></div>} />
                        <Route path="/settings" element={<div className="legacy-page"><SettingsPage /></div>} />
                        <Route path="*" element={<Navigate to="/" replace />} />
                      </Routes>
                    </ErrorBoundary>
                  </div>
                </BrowserRouter>
              </MiloStateProvider>
            </VoiceProvider>
          </SpeechProvider>
        </TaskProvider>
      </AgentsProvider>
      </BrowserVoiceProvider>
    </SettingsProvider>
  );
}
