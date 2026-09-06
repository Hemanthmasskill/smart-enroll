import { Link, useNavigate } from "react-router-dom";
import { useState } from "react";
import "./Navbar.css";

export default function Navbar() {
  const [menuOpen, setMenuOpen] = useState(false);
  const navigate = useNavigate();

  const closeMenu = () => setMenuOpen(false);

  return (
    <header className="navbar">
      <div className="container navbar-inner">
        <Link to="/" className="brand" onClick={closeMenu}>
          <span className="brand-mark">S</span>
          <span className="brand-name">Smart Enroll</span>
        </Link>

        <nav className={`nav-links ${menuOpen ? "open" : ""}`}>
          <a href="#features" onClick={closeMenu}>
            Features
          </a>
          <a href="#how-it-works" onClick={closeMenu}>
            How It Works
          </a>
          <a href="#security" onClick={closeMenu}>
            Security
          </a>
          <Link to="/login" onClick={closeMenu}>
            Login
          </Link>
          <button
            className="btn btn-accent nav-apply-btn"
            onClick={() => {
              closeMenu();
              navigate("/register");
            }}
          >
            Apply Now
          </button>
        </nav>

        <button
          className="menu-toggle"
          aria-label="Toggle navigation menu"
          aria-expanded={menuOpen}
          onClick={() => setMenuOpen((v) => !v)}
        >
          <span />
          <span />
          <span />
        </button>
      </div>
    </header>
  );
}
