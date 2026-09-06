import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "../../context/AuthContext";
import { isValidEmail, required } from "../../utils/validators";
import "./Auth.css";

export default function Login() {
  const [role, setRole] = useState("user");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [rememberMe, setRememberMe] = useState(false);
  const [errors, setErrors] = useState({});
  const [submitError, setSubmitError] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  const { login } = useAuth();
  const navigate = useNavigate();

  const validate = () => {
    const nextErrors = {};
    if (!required(email)) {
      nextErrors.email = "Email is required.";
    } else if (!isValidEmail(email)) {
      nextErrors.email = "Enter a valid email address.";
    }
    if (!required(password)) {
      nextErrors.password = "Password is required.";
    }
    setErrors(nextErrors);
    return Object.keys(nextErrors).length === 0;
  };

  const handleSubmit = async (event) => {
    event.preventDefault();
    setSubmitError("");
    if (!validate()) return;

    setIsSubmitting(true);
    try {
      await login({ email, password, role });
      navigate(role === "admin" ? "/admin" : "/dashboard");
    } catch (error) {
      setSubmitError(error.message || "Unable to log in. Please try again.");
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="auth-page">
      <div className="auth-card card">
        <Link to="/" className="brand auth-brand">
          <span className="brand-mark">S</span>
          <span className="brand-name">Smart Enroll</span>
        </Link>

        <div className="role-toggle" role="tablist" aria-label="Login as">
          <button
            type="button"
            role="tab"
            aria-selected={role === "user"}
            className={role === "user" ? "active" : ""}
            onClick={() => setRole("user")}
          >
            User
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={role === "admin"}
            className={role === "admin" ? "active" : ""}
            onClick={() => setRole("admin")}
          >
            Admin
          </button>
        </div>

        <h1 className="auth-heading">Log in to Smart Enroll</h1>
        <p className="auth-subheading">
          {role === "user"
            ? "Access your admission application and documents."
            : "Restricted access for Smart Enroll administrators."}
        </p>

        <form onSubmit={handleSubmit} noValidate>
          <div className="field">
            <label htmlFor="email">Email Address</label>
            <input
              id="email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className={errors.email ? "input-error" : ""}
              autoComplete="email"
            />
            {errors.email && <span className="error">{errors.email}</span>}
          </div>

          <div className="field">
            <label htmlFor="password">Password</label>
            <div className="password-input">
              <input
                id="password"
                type={showPassword ? "text" : "password"}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className={errors.password ? "input-error" : ""}
                autoComplete="current-password"
              />
              <button
                type="button"
                className="password-toggle"
                onClick={() => setShowPassword((v) => !v)}
                aria-label={showPassword ? "Hide password" : "Show password"}
              >
                {showPassword ? "Hide" : "Show"}
              </button>
            </div>
            {errors.password && <span className="error">{errors.password}</span>}
          </div>

          <div className="auth-row">
            <label className="checkbox-label">
              <input
                type="checkbox"
                checked={rememberMe}
                onChange={(e) => setRememberMe(e.target.checked)}
              />
              Remember me
            </label>
            <Link to="/login" className="link-muted">
              Forgot password?
            </Link>
          </div>

          {submitError && <p className="error" style={{ marginBottom: "var(--space-3)" }}>{submitError}</p>}

          <button type="submit" className="btn btn-accent btn-block" disabled={isSubmitting}>
            {isSubmitting ? "Signing in..." : `Login as ${role === "user" ? "User" : "Admin"}`}
          </button>
        </form>

        {role === "user" ? (
          <p className="auth-footnote">
            New applicant? <Link to="/register">Create an account</Link>
          </p>
        ) : (
          <p className="auth-footnote admin-note">
            Admin access is restricted to authorized Smart Enroll personnel.
          </p>
        )}
      </div>
    </div>
  );
}
