import { NavLink } from "react-router-dom";
import "./Sidebar.css";

/**
 * Generic sidebar navigation. Pass `items` as
 * [{ to, label, icon }] and it renders active-state links.
 * Used inside ApplicantLayout and AdminLayout so both dashboards
 * share one consistent sidebar behavior (including the mobile drawer).
 */
export default function Sidebar({ items, open, onNavigate }) {
  return (
    <aside className={`sidebar ${open ? "sidebar-open" : ""}`}>
      <nav className="sidebar-nav">
        {items.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end}
            onClick={onNavigate}
            className={({ isActive }) => `sidebar-link ${isActive ? "active" : ""}`}
          >
            <span className="sidebar-icon" aria-hidden="true">
              {item.icon}
            </span>
            {item.label}
          </NavLink>
        ))}
      </nav>
    </aside>
  );
}
