// NavBar.tsx -- the top pill (Play / Missions / Memory / Skills / Lab), connection status,
// and the gear menu (Activity drawer, About, Settings). On small screens the
// pill becomes a bottom tab dock.
import { useState } from "react";
import { Link, NavLink } from "react-router-dom";

import { ApiError } from "../api/client";
import { useAgents } from "../state/useAgents";
import { ActivityPage } from "../pages/ActivityPage";
import { isDemo } from "../api/demo";
import { BookIcon, FlagIcon, FlaskIcon, GearIcon, PlayIcon, SparkIcon } from "./Icons";
import { MiloWordmark } from "./MiloWordmark";

const TABS = [
  { to: "/", label: "Play", icon: <PlayIcon />, end: true },
  { to: "/missions", label: "Missions", icon: <FlagIcon /> },
  { to: "/memory", label: "Memory", icon: <BookIcon /> },
  { to: "/skills", label: "Skills", icon: <SparkIcon /> },
  { to: "/lab", label: "Lab", icon: <FlaskIcon /> },
];

function Tabs({ className }: { className: string }) {
  return (
    <nav className={className} aria-label="Main navigation">
      {TABS.map((tab) => (
        <NavLink
          key={tab.to}
          to={tab.to}
          end={tab.end}
          className={({ isActive }) => "tab" + (isActive ? " tab--active" : "")}
        >
          {tab.icon}
          {tab.label}
        </NavLink>
      ))}
    </nav>
  );
}

function DemoBanner() {
  if (!isDemo()) return null;
  return (
    <div className="notice" role="note">
      Demo mode: replaying recorded missions. No simulator is connected. <a href="?demo=0">Leave demo mode</a>
    </div>
  );
}

export function NavBar() {
  const { status, error } = useAgents();
  const [menuOpen, setMenuOpen] = useState(false);
  const [activityOpen, setActivityOpen] = useState(false);

  const down =
    status === "error" && !(error instanceof ApiError && error.category === "agents_unavailable");
  const label = isDemo()
    ? "Demo: recorded missions"
    : down
      ? "Can't reach MILO"
      : status === "success" || status === "error"
        ? "Simulator online"
        : "Connecting";

  return (
    <>
      <DemoBanner />
      <header className="topbar">
        <Link to="/" aria-label="MILO home" style={{ textDecoration: "none" }}>
          <MiloWordmark />
        </Link>
        <Tabs className="tabs" />
        <div className="topbar__right">
          <span className={"status" + (down && !isDemo() ? " status--down" : "")} role="status">
            <span className="status__dot" aria-hidden="true" />
            {label}
          </span>
          <div className="menu">
            <button
              type="button"
              className="btn btn--icon"
              aria-label="Settings and more"
              aria-expanded={menuOpen}
              onClick={() => setMenuOpen((open) => !open)}
            >
              <GearIcon />
            </button>
            {menuOpen && (
              <div className="card menu__panel" role="menu">
                <button
                  type="button"
                  className="menu__item"
                  role="menuitem"
                  onClick={() => {
                    setActivityOpen(true);
                    setMenuOpen(false);
                  }}
                >
                  Recent activity
                </button>
                <Link className="menu__item" role="menuitem" to="/settings" onClick={() => setMenuOpen(false)}>
                  Settings
                </Link>
                <Link className="menu__item" role="menuitem" to="/replay" onClick={() => setMenuOpen(false)}>
                  Replays
                </Link>
                <Link className="menu__item" role="menuitem" to="/leaderboard" onClick={() => setMenuOpen(false)}>
                  Leaderboard
                </Link>
                <Link className="menu__item" role="menuitem" to="/about" onClick={() => setMenuOpen(false)}>
                  About MILO
                </Link>
              </div>
            )}
          </div>
        </div>
      </header>
      <Tabs className="dock" />
      {activityOpen && (
        <aside className="drawer" aria-label="Recent activity">
          <button type="button" className="btn" onClick={() => setActivityOpen(false)}>
            Close
          </button>
          <ActivityPage />
        </aside>
      )}
    </>
  );
}
