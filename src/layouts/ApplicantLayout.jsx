import { useState } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import Sidebar from "../components/Sidebar";
import { useAuth } from "../context/AuthContext";
import "./ApplicantLayout.css";

const navItems = [
  { to: "/dashboard", label: "Dashboard", icon: "\u2302", end: true },
  { to: "/application", label: "Application", icon: "\u270E" },
  { to: "/documents", label: "Documents", icon: "\u2637" },
  { to: "/digilocker", label: "DigiLocker", icon: "\u26C1" },
  { to: "/eligibility", label: "Eligibility", icon: "\u2713" },
  { to: "/status", label: "Status", icon: "\u25CE" },
  { to: "/notifications", label: "Notifications", icon: "\u25CF" },
  { to: "/profile", label: "Profile", icon: "\u263A" },
];

export default function ApplicantLayout({ children }) {
  const [drawerOpen, setDrawerOpen] = useState(false);
  const { session, logout } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();

  const activeLabel = navItems.find((item) =>
    item.end ? location.pathname === item.to : location.pathname.startsWith(item.to)
  )?.label;

  const handleLogout = () => {
    logout();
    navigate("/");
  };

  return (
    <div className="applicant-layout">
      <header className="app-topbar">
        <button
          className="drawer-toggle"
          aria-label="Toggle navigation menu"
          onClick={() => setDrawerOpen((v) => !v)}
        >
          <span />
          <span />
          <span />
        </button>

        <div className="brand app-topbar-brand">
          <span className="brand-mark">S</span>
          <span className="brand-name">Smart Enroll</span>
        </div>

        <span className="app-topbar-page">{activeLabel}</span>

        <div className="app-topbar-user">
          <span className="app-topbar-name">{session?.name ?? "Applicant"}</span>
          <button className="btn btn-secondary btn-sm" onClick={handleLogout}>
            Logout
          </button>
        </div>
      </header>

      <div className="applicant-layout-body">
        <Sidebar items={navItems} open={drawerOpen} onNavigate={() => setDrawerOpen(false)} />
        {drawerOpen && (
          <button
            className="drawer-scrim"
            aria-label="Close navigation menu"
            onClick={() => setDrawerOpen(false)}
          />
        )}
        <main className="applicant-content">{children}</main>
      </div>
    </div>
  );
}
