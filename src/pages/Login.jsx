import { useState } from "react";
import { Link } from "react-router-dom";
import "./Login.css";

function Login() {
  const [role, setRole] = useState("user");
  const [formData, setFormData] = useState({
    email: "",
    password: "",
  });

  const handleChange = (e) => {
    setFormData({
      ...formData,
      [e.target.name]: e.target.value,
    });
  };

  const handleSubmit = (e) => {
    e.preventDefault();

    console.log({
      role,
      email: formData.email,
      password: formData.password,
    });

    // FastAPI authentication will be connected later.
  };

  return (
    <div className="login-page">
      <div className="login-navbar">
        <Link to="/" className="login-brand">
          <span className="login-brand-mark">S</span>
          <span>Smart Enroll</span>
        </Link>

        <Link to="/" className="back-home">
          Back to Home
        </Link>
      </div>

      <main className="login-main">
        <div className="login-container">
          <div className="login-heading">
            <span className="login-eyebrow">
              Welcome back
            </span>

            <h1>Login to Smart Enroll</h1>

            <p>
              Access your admission account and continue your
              application process.
            </p>
          </div>

          <div className="role-toggle">
            <button
              type="button"
              className={
                role === "user"
                  ? "role-button active"
                  : "role-button"
              }
              onClick={() => setRole("user")}
            >
              User
            </button>

            <button
              type="button"
              className={
                role === "admin"
                  ? "role-button active"
                  : "role-button"
              }
              onClick={() => setRole("admin")}
            >
              Admin
            </button>
          </div>

          <form
            className="login-form"
            onSubmit={handleSubmit}
          >
            <div className="form-group">
              <label htmlFor="email">
                Email Address
              </label>

              <input
                id="email"
                type="email"
                name="email"
                placeholder={
                  role === "admin"
                    ? "admin@example.com"
                    : "student@example.com"
                }
                value={formData.email}
                onChange={handleChange}
                required
              />
            </div>

            <div className="form-group">
              <div className="password-label">
                <label htmlFor="password">
                  Password
                </label>

                <button
                  type="button"
                  className="forgot-password"
                >
                  Forgot password?
                </button>
              </div>

              <input
                id="password"
                type="password"
                name="password"
                placeholder="Enter your password"
                value={formData.password}
                onChange={handleChange}
                required
              />
            </div>

            <button
              type="submit"
              className="login-submit"
            >
              Login as {role === "admin" ? "Admin" : "User"}
            </button>
          </form>

          {role === "user" && (
            <p className="signup-text">
              New applicant?{" "}
              <button type="button">
                Create an account
              </button>
            </p>
          )}

          {role === "admin" && (
            <div className="admin-note">
              Admin access is restricted to authorized
              Smart Enroll personnel.
            </div>
          )}
        </div>
      </main>
    </div>
  );
}

export default Login;