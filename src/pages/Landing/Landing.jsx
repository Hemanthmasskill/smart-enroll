import { Link } from "react-router-dom";
import Navbar from "../../components/Navbar";
import Footer from "../../components/Footer";
import "./Landing.css";

const workflowSteps = [
  { step: "01", title: "Apply", description: "Submit programme and personal details." },
  { step: "02", title: "Upload Documents", description: "Add academic records and identity proof." },
  { step: "03", title: "Verify", description: "Documents are extracted, validated and cross-checked." },
  { step: "04", title: "Evaluate", description: "Eligibility is assessed against programme rules." },
  { step: "05", title: "Enroll", description: "Eligible applicants complete admission." },
];

const features = [
  {
    title: "Document Verification",
    description:
      "Validate academic documents and support authoritative verification through DigiLocker/NAD.",
  },
  {
    title: "Eligibility Check",
    description: "Evaluate applications using configured programme eligibility criteria.",
  },
  {
    title: "Application Tracking",
    description: "Track every stage of the admission process, from submission to enrollment.",
  },
  {
    title: "Automated Updates",
    description:
      "Notify applicants when documents, corrections, or additional actions are required.",
  },
];

const howItWorks = [
  "Submit Application",
  "Upload Documents",
  "Verify Information",
  "Check Eligibility",
  "Track Progress",
];

const trustTags = [
  "DigiLocker / NAD Ready",
  "Rule-Based Eligibility",
  "Audit Trail",
  "Secure Application Flow",
];

export default function Landing() {
  return (
    <div className="landing">
      <Navbar />

      <section className="hero">
        <div className="container hero-inner">
          <span className="hero-label">AI-powered admission processing</span>
          <h1 className="hero-heading">
            Smarter admissions.
            <br />
            Simpler enrollment.
          </h1>
          <p className="hero-description">
            Smart Enroll streamlines application processing, document verification, eligibility
            checks, and admission tracking in one intelligent platform.
          </p>
          <div className="hero-actions">
            <Link to="/register" className="btn btn-accent">
              Start Application
            </Link>
            <Link to="/status" className="btn btn-secondary">
              Track Application
            </Link>
          </div>

          <div className="workflow-strip">
            {workflowSteps.map((item, index) => (
              <div className="workflow-item" key={item.step}>
                <div className="workflow-top">
                  <span className="workflow-number">{item.step}</span>
                  <span className="workflow-title">{item.title}</span>
                </div>
                <p className="workflow-description">{item.description}</p>
                {index < workflowSteps.length - 1 && <span className="workflow-connector" />}
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="section" id="features">
        <div className="container">
          <h2 className="section-heading">Everything needed to move an application forward.</h2>
          <div className="feature-grid">
            {features.map((feature) => (
              <div className="feature-item" key={feature.title}>
                <h3>{feature.title}</h3>
                <p>{feature.description}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="section section-muted" id="how-it-works">
        <div className="container">
          <h2 className="section-heading">How it works</h2>
          <ol className="how-list">
            {howItWorks.map((item, index) => (
              <li key={item}>
                <span className="how-index">{index + 1}</span>
                <span>{item}</span>
              </li>
            ))}
          </ol>
        </div>
      </section>

      <section className="section" id="security">
        <div className="container security-section">
          <div>
            <h2 className="section-heading">Verification you can rely on</h2>
            <p className="security-copy">
              Smart Enroll combines document processing with authoritative academic verification
              where available, so decisions rest on more than an automated reading of a file.
            </p>
          </div>
          <div className="trust-tags">
            {trustTags.map((tag) => (
              <span className="trust-tag" key={tag}>
                {tag}
              </span>
            ))}
          </div>
        </div>
      </section>

      <section className="cta-section">
        <div className="container cta-inner">
          <h2>A cleaner admission experience starts here.</h2>
          <Link to="/register" className="btn btn-accent">
            Apply Now
          </Link>
        </div>
      </section>

      <Footer />
    </div>
  );
}
