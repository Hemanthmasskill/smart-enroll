import { useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import Sidebar from "../components/Sidebar";
import { useAuth } from "../context/AuthContext";
import "./ApplicantLayout.css";

const navItems = [
  { to: "/admin", label: "Dashboard", icon: "⌂", end: true },
  { to: "/admin/applications", label: "Applications", icon: "☷" },
  { to: "/admin/exceptions", label: "Exceptions", icon: "!" },
  { to: "/admin/programs", label: "Programme Rules", icon: "≡" },
  { to: "/admin/agent-activity", label: "Agent Activity", icon: "◎" },
  { to: "/admin/analytics", label: "Analytics", icon: "▥" },
];

export default function AdminLayout({ children }) {
  const [drawerOpen, setDrawerOpen] = useState(false);
  const { session, logout } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const activeLabel = navItems.find((item) => item.end ? location.pathname === item.to : location.pathname.startsWith(item.to))?.label;

  const handleLogout = () => { logout(); navigate("/"); };

  return (
    <div className="applicant-layout">
      <header className="app-topbar">
        <button className="drawer-toggle" aria-label="Toggle navigation menu" onClick={() => setDrawerOpen((v) => !v)}><span/><span/><span/></button>
        <div className="brand app-topbar-brand"><span className="brand-mark">S</span><span className="brand-name">Smart Enroll</span></div>
        <span className="app-topbar-page">Admin · {activeLabel}</span>
        <div className="app-topbar-user"><span className="app-topbar-name">{session?.name ?? "Admin"}</span><button className="btn btn-secondary btn-sm" onClick={handleLogout}>Logout</button></div>
      </header>
      <div className="applicant-layout-body">
        <Sidebar items={navItems} open={drawerOpen} onNavigate={() => setDrawerOpen(false)} />
        {drawerOpen && <button className="drawer-scrim" aria-label="Close navigation menu" onClick={() => setDrawerOpen(false)} />}
        <main className="applicant-content">{children}</main>
      </div>
    </div>
  );
}
