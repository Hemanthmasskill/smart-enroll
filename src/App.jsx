import {
  Routes,
  Route,
  Link,
} from "react-router-dom";

import "./App.css";
import Login from "./pages/Login";

const features = [
  {
    title: "Document Verification",
    text: "Validate academic documents and support authoritative verification through DigiLocker/NAD.",
  },
  {
    title: "Eligibility Check",
    text: "Evaluate applications using configured programme eligibility rules.",
  },
  {
    title: "Application Tracking",
    text: "Track every stage of the admission process.",
  },
  {
    title: "Automated Updates",
    text: "Notify applicants when action is required.",
  },
];

const steps = [
  "Apply",
  "Upload Documents",
  "Verify",
  "Evaluate",
  "Enroll",
];

function LandingPage() {
  return (
    <div className="app">
      <header className="navbar">
        <a href="#home" className="brand">
          <span className="brand-mark">S</span>
          <span>Smart Enroll</span>
        </a>

        <nav className="nav-links">
          <a href="#features">Features</a>
          <a href="#process">How It Works</a>
          <a href="#trust">Security</a>
        </nav>

        <div className="nav-actions">
          <Link
            to="/login"
            className="btn btn-ghost"
          >
            Login
          </Link>

          <button className="btn btn-primary">
            Apply Now
          </button>
        </div>
      </header>

      {/* Keep the rest of your existing landing page here */}
    </div>
  );
}

function App() {
  return (
    <Routes>
      <Route
        path="/"
        element={<LandingPage />}
      />

      <Route
        path="/login"
        element={<Login />}
      />
    </Routes>
  );
}

export default App;