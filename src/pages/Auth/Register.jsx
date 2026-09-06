import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "../../context/AuthContext";
import {
  isValidEmail,
  isValidMobile,
  isStrongPassword,
  required,
} from "../../utils/validators";
import "./Auth.css";

const initialForm = {
  fullName: "",
  email: "",
  mobile: "",
  dob: "",
  password: "",
  confirmPassword: "",
  agree: false,
};

export default function Register() {
  const [form, setForm] = useState(initialForm);
  const [errors, setErrors] = useState({});
  const [submitError, setSubmitError] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  const { register } = useAuth();
  const navigate = useNavigate();

  const updateField = (field) => (event) => {
    const value = field === "agree" ? event.target.checked : event.target.value;
    setForm((prev) => ({ ...prev, [field]: value }));
  };

  const validate = () => {
    const nextErrors = {};

    if (!required(form.fullName)) nextErrors.fullName = "Full name is required.";

    if (!required(form.email)) nextErrors.email = "Email is required.";
    else if (!isValidEmail(form.email)) nextErrors.email = "Enter a valid email address.";

    if (!required(form.mobile)) nextErrors.mobile = "Mobile number is required.";
    else if (!isValidMobile(form.mobile)) nextErrors.mobile = "Enter a valid 10-digit mobile number.";

    if (!required(form.dob)) nextErrors.dob = "Date of birth is required.";

    if (!required(form.password)) nextErrors.password = "Password is required.";
    else if (!isStrongPassword(form.password))
      nextErrors.password = "Use at least 8 characters, including a letter and a number.";

    if (form.confirmPassword !== form.password)
      nextErrors.confirmPassword = "Passwords do not match.";

    if (!form.agree) nextErrors.agree = "You must accept the terms to continue.";

    setErrors(nextErrors);
    return Object.keys(nextErrors).length === 0;
  };

  const handleSubmit = async (event) => {
    event.preventDefault();
    setSubmitError("");
    if (!validate()) return;

    setIsSubmitting(true);
    try {
      await register(form);
      navigate("/dashboard");
    } catch (error) {
      setSubmitError(error.message || "Unable to create your account. Please try again.");
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="auth-page">
      <div className="auth-card card auth-card-wide">
        <Link to="/" className="brand auth-brand">
          <span className="brand-mark">S</span>
          <span className="brand-name">Smart Enroll</span>
        </Link>

        <h1 className="auth-heading">Create your applicant account</h1>
        <p className="auth-subheading">Start your admission application in a few minutes.</p>

        <form onSubmit={handleSubmit} noValidate>
          <div className="field">
            <label htmlFor="fullName">Full Name</label>
            <input
              id="fullName"
              value={form.fullName}
              onChange={updateField("fullName")}
              className={errors.fullName ? "input-error" : ""}
            />
            {errors.fullName && <span className="error">{errors.fullName}</span>}
          </div>

          <div className="field-row">
            <div className="field">
              <label htmlFor="email">Email</label>
              <input
                id="email"
                type="email"
                value={form.email}
                onChange={updateField("email")}
                className={errors.email ? "input-error" : ""}
              />
              {errors.email && <span className="error">{errors.email}</span>}
            </div>

            <div className="field">
              <label htmlFor="mobile">Mobile Number</label>
              <input
                id="mobile"
                value={form.mobile}
                onChange={updateField("mobile")}
                className={errors.mobile ? "input-error" : ""}
                inputMode="numeric"
              />
              {errors.mobile && <span className="error">{errors.mobile}</span>}
            </div>
          </div>

          <div className="field">
            <label htmlFor="dob">Date of Birth</label>
            <input
              id="dob"
              type="date"
              value={form.dob}
              onChange={updateField("dob")}
              className={errors.dob ? "input-error" : ""}
            />
            {errors.dob && <span className="error">{errors.dob}</span>}
          </div>

          <div className="field-row">
            <div className="field">
              <label htmlFor="password">Password</label>
              <input
                id="password"
                type="password"
                value={form.password}
                onChange={updateField("password")}
                className={errors.password ? "input-error" : ""}
              />
              {errors.password ? (
                <span className="error">{errors.password}</span>
              ) : (
                <span className="hint">At least 8 characters, with a letter and a number.</span>
              )}
            </div>

            <div className="field">
              <label htmlFor="confirmPassword">Confirm Password</label>
              <input
                id="confirmPassword"
                type="password"
                value={form.confirmPassword}
                onChange={updateField("confirmPassword")}
                className={errors.confirmPassword ? "input-error" : ""}
              />
              {errors.confirmPassword && <span className="error">{errors.confirmPassword}</span>}
            </div>
          </div>

          <label className="checkbox-label terms-row">
            <input type="checkbox" checked={form.agree} onChange={updateField("agree")} />
            I agree to the Terms and Privacy Policy.
          </label>
          {errors.agree && <span className="error">{errors.agree}</span>}

          {submitError && <p className="error" style={{ margin: "var(--space-3) 0" }}>{submitError}</p>}

          <button type="submit" className="btn btn-accent btn-block" disabled={isSubmitting}>
            {isSubmitting ? "Creating account..." : "Create Account"}
          </button>
        </form>

        <p className="auth-footnote">
          Already registered? <Link to="/login">Login</Link>
        </p>
      </div>
    </div>
  );
}
