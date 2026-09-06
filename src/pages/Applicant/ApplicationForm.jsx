import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../../context/AuthContext";
import { createApplication, getPrograms } from "../../services/api";
import { required } from "../../utils/validators";
import PageHeader from "../../components/PageHeader";
import ProgressStepper from "../../components/ProgressStepper";
import "./ApplicationForm.css";

const steps = [
  "Personal Details",
  "Contact Details",
  "Academic Details",
  "Programme Selection",
  "Review & Submit",
];

const initialForm = {
  fullName: "",
  dob: "",
  gender: "",
  nationality: "",
  email: "",
  mobile: "",
  address: "",
  city: "",
  state: "",
  pinCode: "",
  tenthBoard: "",
  tenthPercentage: "",
  twelfthBoard: "",
  twelfthPercentage: "",
  ugDegree: "",
  university: "",
  graduationYear: "",
  cgpa: "",
  programmeId: "",
  applicationMode: "Regular",
};

export default function ApplicationForm() {
  const { session } = useAuth();
  const navigate = useNavigate();

  const [currentStep, setCurrentStep] = useState(0);
  const [form, setForm] = useState(initialForm);
  const [errors, setErrors] = useState({});
  const [programs, setPrograms] = useState([]);
  const [draftMessage, setDraftMessage] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isSubmitted, setIsSubmitted] = useState(false);

  useEffect(() => {
    getPrograms().then(setPrograms);
  }, []);

  const updateField = (field) => (event) => {
    setForm((prev) => ({ ...prev, [field]: event.target.value }));
  };

  const validateStep = () => {
    const nextErrors = {};
    if (currentStep === 0) {
      ["fullName", "dob", "gender", "nationality"].forEach((field) => {
        if (!required(form[field])) nextErrors[field] = "This field is required.";
      });
    }
    if (currentStep === 1) {
      ["email", "mobile", "address", "city", "state", "pinCode"].forEach((field) => {
        if (!required(form[field])) nextErrors[field] = "This field is required.";
      });
    }
    if (currentStep === 2) {
      [
        "tenthBoard",
        "tenthPercentage",
        "twelfthBoard",
        "twelfthPercentage",
        "ugDegree",
        "university",
        "graduationYear",
        "cgpa",
      ].forEach((field) => {
        if (!required(form[field])) nextErrors[field] = "This field is required.";
      });
    }
    if (currentStep === 3) {
      if (!required(form.programmeId)) nextErrors.programmeId = "Select a programme.";
    }
    setErrors(nextErrors);
    return Object.keys(nextErrors).length === 0;
  };

  const handleNext = () => {
    if (!validateStep()) return;
    setDraftMessage("");
    setCurrentStep((s) => Math.min(s + 1, steps.length - 1));
  };

  const handlePrevious = () => {
    setDraftMessage("");
    setCurrentStep((s) => Math.max(s - 1, 0));
  };

  const handleSaveDraft = () => {
    setDraftMessage("Draft saved. You can continue this application anytime.");
  };

  const handleSubmit = async () => {
    setIsSubmitting(true);
    try {
      await createApplication(session?.applicantId, form);
      setIsSubmitted(true);
    } finally {
      setIsSubmitting(false);
    }
  };

  const selectedProgramme = programs.find((p) => p.id === form.programmeId);

  if (isSubmitted) {
    return (
      <div className="card submit-success">
        <span className="submit-success-icon">&#10003;</span>
        <h2>Application submitted</h2>
        <p>
          Your MCA admission application has been received. Smart Enroll will now check your
          required documents and notify you of any next steps.
        </p>
        <button className="btn btn-accent" onClick={() => navigate("/dashboard")}>
          Go to Dashboard
        </button>
      </div>
    );
  }

  return (
    <div>
      <PageHeader
        title="Admission Application"
        subtitle="Complete each section to submit your application."
      />

      <div className="card application-card">
        <ProgressStepper steps={steps} currentStep={currentStep} />

        {currentStep === 0 && (
          <div className="form-grid">
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
            <div className="field">
              <label htmlFor="gender">Gender</label>
              <select
                id="gender"
                value={form.gender}
                onChange={updateField("gender")}
                className={errors.gender ? "input-error" : ""}
              >
                <option value="">Select</option>
                <option>Female</option>
                <option>Male</option>
                <option>Other</option>
                <option>Prefer not to say</option>
              </select>
              {errors.gender && <span className="error">{errors.gender}</span>}
            </div>
            <div className="field">
              <label htmlFor="nationality">Nationality</label>
              <input
                id="nationality"
                value={form.nationality}
                onChange={updateField("nationality")}
                className={errors.nationality ? "input-error" : ""}
              />
              {errors.nationality && <span className="error">{errors.nationality}</span>}
            </div>
          </div>
        )}

        {currentStep === 1 && (
          <div className="form-grid">
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
              <label htmlFor="mobile">Mobile</label>
              <input
                id="mobile"
                value={form.mobile}
                onChange={updateField("mobile")}
                className={errors.mobile ? "input-error" : ""}
              />
              {errors.mobile && <span className="error">{errors.mobile}</span>}
            </div>
            <div className="field form-grid-span-2">
              <label htmlFor="address">Address</label>
              <input
                id="address"
                value={form.address}
                onChange={updateField("address")}
                className={errors.address ? "input-error" : ""}
              />
              {errors.address && <span className="error">{errors.address}</span>}
            </div>
            <div className="field">
              <label htmlFor="city">City</label>
              <input
                id="city"
                value={form.city}
                onChange={updateField("city")}
                className={errors.city ? "input-error" : ""}
              />
              {errors.city && <span className="error">{errors.city}</span>}
            </div>
            <div className="field">
              <label htmlFor="state">State</label>
              <input
                id="state"
                value={form.state}
                onChange={updateField("state")}
                className={errors.state ? "input-error" : ""}
              />
              {errors.state && <span className="error">{errors.state}</span>}
            </div>
            <div className="field">
              <label htmlFor="pinCode">PIN Code</label>
              <input
                id="pinCode"
                value={form.pinCode}
                onChange={updateField("pinCode")}
                className={errors.pinCode ? "input-error" : ""}
              />
              {errors.pinCode && <span className="error">{errors.pinCode}</span>}
            </div>
          </div>
        )}

        {currentStep === 2 && (
          <div className="form-grid">
            <div className="field">
              <label htmlFor="tenthBoard">10th Board</label>
              <input
                id="tenthBoard"
                value={form.tenthBoard}
                onChange={updateField("tenthBoard")}
                className={errors.tenthBoard ? "input-error" : ""}
              />
              {errors.tenthBoard && <span className="error">{errors.tenthBoard}</span>}
            </div>
            <div className="field">
              <label htmlFor="tenthPercentage">10th Percentage</label>
              <input
                id="tenthPercentage"
                value={form.tenthPercentage}
                onChange={updateField("tenthPercentage")}
                className={errors.tenthPercentage ? "input-error" : ""}
              />
              {errors.tenthPercentage && <span className="error">{errors.tenthPercentage}</span>}
            </div>
            <div className="field">
              <label htmlFor="twelfthBoard">12th Board</label>
              <input
                id="twelfthBoard"
                value={form.twelfthBoard}
                onChange={updateField("twelfthBoard")}
                className={errors.twelfthBoard ? "input-error" : ""}
              />
              {errors.twelfthBoard && <span className="error">{errors.twelfthBoard}</span>}
            </div>
            <div className="field">
              <label htmlFor="twelfthPercentage">12th Percentage</label>
              <input
                id="twelfthPercentage"
                value={form.twelfthPercentage}
                onChange={updateField("twelfthPercentage")}
                className={errors.twelfthPercentage ? "input-error" : ""}
              />
              {errors.twelfthPercentage && (
                <span className="error">{errors.twelfthPercentage}</span>
              )}
            </div>
            <div className="field">
              <label htmlFor="ugDegree">UG Degree</label>
              <input
                id="ugDegree"
                value={form.ugDegree}
                onChange={updateField("ugDegree")}
                className={errors.ugDegree ? "input-error" : ""}
              />
              {errors.ugDegree && <span className="error">{errors.ugDegree}</span>}
            </div>
            <div className="field">
              <label htmlFor="university">University</label>
              <input
                id="university"
                value={form.university}
                onChange={updateField("university")}
                className={errors.university ? "input-error" : ""}
              />
              {errors.university && <span className="error">{errors.university}</span>}
            </div>
            <div className="field">
              <label htmlFor="graduationYear">Graduation Year</label>
              <input
                id="graduationYear"
                value={form.graduationYear}
                onChange={updateField("graduationYear")}
                className={errors.graduationYear ? "input-error" : ""}
              />
              {errors.graduationYear && <span className="error">{errors.graduationYear}</span>}
            </div>
            <div className="field">
              <label htmlFor="cgpa">CGPA / Percentage</label>
              <input
                id="cgpa"
                value={form.cgpa}
                onChange={updateField("cgpa")}
                className={errors.cgpa ? "input-error" : ""}
              />
              {errors.cgpa && <span className="error">{errors.cgpa}</span>}
            </div>
          </div>
        )}

        {currentStep === 3 && (
          <div className="form-grid">
            <div className="field form-grid-span-2">
              <label htmlFor="programmeId">Select Programme</label>
              <select
                id="programmeId"
                value={form.programmeId}
                onChange={updateField("programmeId")}
                className={errors.programmeId ? "input-error" : ""}
              >
                <option value="">Select a programme</option>
                {programs.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name} — {p.fullName}
                  </option>
                ))}
              </select>
              {errors.programmeId && <span className="error">{errors.programmeId}</span>}
            </div>
            <div className="field">
              <label htmlFor="applicationMode">Application Mode</label>
              <select id="applicationMode" value={form.applicationMode} onChange={updateField("applicationMode")}>
                <option>Regular</option>
              </select>
            </div>
          </div>
        )}

        {currentStep === 4 && (
          <div className="review-grid">
            <ReviewSection title="Personal Details">
              <ReviewRow label="Full Name" value={form.fullName} />
              <ReviewRow label="Date of Birth" value={form.dob} />
              <ReviewRow label="Gender" value={form.gender} />
              <ReviewRow label="Nationality" value={form.nationality} />
            </ReviewSection>
            <ReviewSection title="Contact Details">
              <ReviewRow label="Email" value={form.email} />
              <ReviewRow label="Mobile" value={form.mobile} />
              <ReviewRow label="Address" value={`${form.address}, ${form.city}, ${form.state} - ${form.pinCode}`} />
            </ReviewSection>
            <ReviewSection title="Academic Details">
              <ReviewRow label="10th" value={`${form.tenthBoard} · ${form.tenthPercentage}%`} />
              <ReviewRow label="12th" value={`${form.twelfthBoard} · ${form.twelfthPercentage}%`} />
              <ReviewRow label="UG Degree" value={`${form.ugDegree}, ${form.university}`} />
              <ReviewRow label="Graduation" value={`${form.graduationYear} · CGPA ${form.cgpa}`} />
            </ReviewSection>
            <ReviewSection title="Programme">
              <ReviewRow
                label="Programme"
                value={selectedProgramme ? `${selectedProgramme.name} — ${selectedProgramme.fullName}` : "—"}
              />
              <ReviewRow label="Mode" value={form.applicationMode} />
            </ReviewSection>
          </div>
        )}

        {draftMessage && <p className="draft-message">{draftMessage}</p>}

        <div className="application-actions">
          <button
            className="btn btn-secondary"
            onClick={handlePrevious}
            disabled={currentStep === 0}
          >
            Previous
          </button>
          <button className="btn btn-ghost" onClick={handleSaveDraft}>
            Save Draft
          </button>
          {currentStep < steps.length - 1 ? (
            <button className="btn btn-accent" onClick={handleNext}>
              Next
            </button>
          ) : (
            <button className="btn btn-accent" onClick={handleSubmit} disabled={isSubmitting}>
              {isSubmitting ? "Submitting..." : "Submit Application"}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

function ReviewSection({ title, children }) {
  return (
    <div className="review-section">
      <h3>{title}</h3>
      {children}
    </div>
  );
}

function ReviewRow({ label, value }) {
  return (
    <div className="review-row">
      <span>{label}</span>
      <span>{value || "—"}</span>
    </div>
  );
}
