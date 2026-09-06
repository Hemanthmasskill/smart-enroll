import { Link } from "react-router-dom";

export default function NotFound() {
  return (
    <div
      style={{
        minHeight: "100vh",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        gap: "16px",
        textAlign: "center",
        padding: "24px",
      }}
    >
      <span style={{ fontSize: "13px", fontWeight: 600, color: "var(--color-primary-dark)" }}>
        Error 404
      </span>
      <h1 style={{ fontSize: "28px" }}>This page doesn't exist.</h1>
      <p style={{ color: "var(--color-text-secondary)", maxWidth: "420px" }}>
        The page you're looking for may have been moved or the link may be incorrect.
      </p>
      <Link to="/" className="btn btn-accent">
        Back to Home
      </Link>
    </div>
  );
}
