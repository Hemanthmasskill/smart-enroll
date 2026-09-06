import { useEffect, useState } from "react";
import { useAuth } from "../../context/AuthContext";
import { getApplicantProfile, updateApplicantProfile } from "../../services/api";
import { isValidEmail, isValidMobile } from "../../utils/validators";
import PageHeader from "../../components/PageHeader";
import "./Profile.css";

export default function Profile() {
  const { session } = useAuth();
  const [profile, setProfile] = useState(null);
  const [isEditing, setIsEditing] = useState(false);
  const [form, setForm] = useState({ email: "", mobile: "" });
  const [errors, setErrors] = useState({});
  const [saveMessage, setSaveMessage] = useState("");
  const [showIdentityWarning, setShowIdentityWarning] = useState(false);

  useEffect(() => {
    getApplicantProfile(session?.applicantId).then((data) => {
      setProfile(data);
      setForm({ email: data?.email ?? "", mobile: data?.mobile ?? "" });
    });
  }, [session]);

  if (!profile) return <p>Loading your profile...</p>;

  const handleSave = async () => {
    const nextErrors = {};
    if (!isValidEmail(form.email)) nextErrors.email = "Enter a valid email address.";
    if (!isValidMobile(form.mobile)) nextErrors.mobile = "Enter a valid 10-digit mobile number.";
    setErrors(nextErrors);
    if (Object.keys(nextErrors).length > 0) return;

    const updated = await updateApplicantProfile(session?.applicantId, form);
    setProfile(updated);
    setIsEditing(false);
    setSaveMessage("Contact details updated.");
  };

  return (
    <div>
      <PageHeader title="Profile" subtitle="Manage your basic applicant information." />

      <div className="card profile-card">
        <div className="profile-row">
          <span className="profile-label">Applicant ID</span>
          <span className="profile-value">{profile.id}</span>
        </div>

        <div className="profile-row">
          <span className="profile-label">Full Name</span>
          <span className="profile-value">{profile.fullName}</span>
          <button
            type="button"
            className="identity-edit-link"
            onClick={() => setShowIdentityWarning(true)}
          >
            Edit
          </button>
        </div>

        <div className="profile-row">
          <span className="profile-label">Date of Birth</span>
          <span className="profile-value">{profile.dob}</span>
          <button
            type="button"
            className="identity-edit-link"
            onClick={() => setShowIdentityWarning(true)}
          >
            Edit
          </button>
        </div>

        {showIdentityWarning && (
          <p className="identity-warning">
            Name and date of birth are identity fields tied to your submitted application. Changing
            them after submission requires manual review — contact admissions support to proceed.
          </p>
        )}

        <hr className="profile-divider" />

        <div className="profile-row">
          <span className="profile-label">Email</span>
          {isEditing ? (
            <div className="profile-edit-field">
              <input
                value={form.email}
                onChange={(e) => setForm((p) => ({ ...p, email: e.target.value }))}
                className={errors.email ? "input-error" : ""}
              />
              {errors.email && <span className="error">{errors.email}</span>}
            </div>
          ) : (
            <span className="profile-value">{profile.email}</span>
          )}
        </div>

        <div className="profile-row">
          <span className="profile-label">Mobile</span>
          {isEditing ? (
            <div className="profile-edit-field">
              <input
                value={form.mobile}
                onChange={(e) => setForm((p) => ({ ...p, mobile: e.target.value }))}
                className={errors.mobile ? "input-error" : ""}
              />
              {errors.mobile && <span className="error">{errors.mobile}</span>}
            </div>
          ) : (
            <span className="profile-value">{profile.mobile}</span>
          )}
        </div>

        {saveMessage && !isEditing && <p className="save-message">{saveMessage}</p>}

        <div className="profile-actions">
          {isEditing ? (
            <>
              <button className="btn btn-secondary" onClick={() => setIsEditing(false)}>
                Cancel
              </button>
              <button className="btn btn-accent" onClick={handleSave}>
                Save Changes
              </button>
            </>
          ) : (
            <button className="btn btn-secondary" onClick={() => setIsEditing(true)}>
              Edit Contact Details
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
