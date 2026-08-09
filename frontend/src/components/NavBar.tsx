// NavBar.tsx
//
// Purpose
// -------
// Top navigation for the MILO application -- the seven routes exactly
// (spec: "The MILO frontend contains SEVEN pages, not eight... There
// is NO separate Mission Detail page"). Establishes MILO's identity
// (full name in the header, per spec's branding rule) and highlights
// the active route via `NavLink`'s built-in `isActive` styling hook,
// so this needs no manual `useLocation()` bookkeeping.
import { NavLink } from "react-router-dom";

const NAV_LINKS: Array<{ to: string; label: string; end?: boolean }> = [
  { to: "/", label: "🏠 Home", end: true },
  { to: "/mission-control", label: "🎮 Mission Control" },
  { to: "/memory", label: "🧠 Memory" },
  { to: "/activity", label: "📜 Activity" },
  { to: "/about", label: "👋 About MILO" },
  { to: "/lab", label: "🔬 MILO Lab" },
  { to: "/settings", label: "⚙ Settings" },
];

export function NavBar() {
  return (
    <header className="milo-navbar">
      <div className="milo-navbar__brand">
        <span className="milo-navbar__title">MILO</span>
        <span className="milo-navbar__subtitle">Memory Integrated Language Oriented Robot</span>
      </div>
      <nav className="milo-navbar__links" aria-label="Main navigation">
        {NAV_LINKS.map((link) => (
          <NavLink
            key={link.to}
            to={link.to}
            end={link.end}
            className={({ isActive }) =>
              "milo-navbar__link" + (isActive ? " milo-navbar__link--active" : "")
            }
          >
            {link.label}
          </NavLink>
        ))}
      </nav>
    </header>
  );
}
