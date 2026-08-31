import "./App.css";

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
    text: "Track every stage of the admission process clearly and efficiently.",
  },
  {
    title: "Automated Updates",
    text: "Notify applicants when documents, corrections, or additional actions are required.",
  },
];

const steps = [
  "Apply",
  "Upload Documents",
  "Verify",
  "Evaluate",
  "Enroll",
];

function App() {
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
          <button className="btn btn-ghost">Login</button>
          <button className="btn btn-primary">Apply Now</button>
        </div>
      </header>

      <main>
        <section className="hero" id="home">
          <div className="hero-badge">
            AI-powered admission processing
          </div>

          <h1>
            Smarter Admissions.
            <span> Simpler Enrollment.</span>
          </h1>

          <p className="hero-copy">
            Smart Enroll streamlines application processing,
            document verification, eligibility checks, and
            admission tracking in one intelligent platform.
          </p>

          <div className="hero-actions">
            <button className="btn btn-primary btn-large">
              Start Application
            </button>

            <button className="btn btn-secondary btn-large">
              Track Application
            </button>
          </div>

          <div className="hero-panel">
            {steps.map((step, index) => (
              <div className="workflow-item" key={step}>
                <div className="workflow-number">
                  {String(index + 1).padStart(2, "0")}
                </div>

                <div className="workflow-label">
                  {step}
                </div>

                {index < steps.length - 1 && (
                  <div className="workflow-line" />
                )}
              </div>
            ))}
          </div>
        </section>

        <section className="section" id="features">
          <div className="section-heading">
            <span className="eyebrow">
              Built for modern admissions
            </span>

            <h2>
              Everything needed to move an application forward.
            </h2>
          </div>

          <div className="feature-grid">
            {features.map((feature, index) => (
              <article
                className="feature-card"
                key={feature.title}
              >
                <span className="feature-index">
                  0{index + 1}
                </span>

                <h3>{feature.title}</h3>

                <p>{feature.text}</p>
              </article>
            ))}
          </div>
        </section>

        <section
          className="section process-section"
          id="process"
        >
          <div className="process-copy">
            <span className="eyebrow">
              How it works
            </span>

            <h2>
              From application to decision,
              without unnecessary friction.
            </h2>

            <p>
              Smart Enroll coordinates document checks,
              applicant data validation, eligibility
              evaluation, exception handling, and status
              updates as one connected workflow.
            </p>
          </div>

          <div className="process-list">
            {[
              [
                "01",
                "Submit application",
                "Enter programme and applicant details.",
              ],
              [
                "02",
                "Upload documents",
                "Provide the required academic and identity documents.",
              ],
              [
                "03",
                "Verify information",
                "Extract, validate, and verify available academic records.",
              ],
              [
                "04",
                "Check eligibility",
                "Evaluate the application against configured programme rules.",
              ],
              [
                "05",
                "Track progress",
                "Receive updates until application processing is complete.",
              ],
            ].map(([number, title, text]) => (
              <div
                className="process-row"
                key={number}
              >
                <span>{number}</span>

                <div>
                  <h3>{title}</h3>
                  <p>{text}</p>
                </div>
              </div>
            ))}
          </div>
        </section>

        <section className="trust-section" id="trust">
          <div>
            <span className="eyebrow">
              Verification & Trust
            </span>

            <h2>
              Designed around reliable evidence,
              not just document appearance.
            </h2>
          </div>

          <p>
            Smart Enroll can combine document processing
            with authoritative academic verification
            sources such as DigiLocker/NAD where
            integration and applicant consent are
            available.
          </p>

          <div className="trust-tags">
            <span>DigiLocker / NAD ready</span>
            <span>Rule-based eligibility</span>
            <span>Audit trail</span>
            <span>Secure application flow</span>
          </div>
        </section>

        <section className="cta-section">
          <div>
            <span className="eyebrow">
              Start your application
            </span>

            <h2>
              A cleaner admission experience starts here.
            </h2>
          </div>

          <button className="btn btn-primary btn-large">
            Apply Now
          </button>
        </section>
      </main>

      <footer className="footer">
        <a href="#home" className="brand">
          <span className="brand-mark">S</span>
          <span>Smart Enroll</span>
        </a>

        <p>
          Intelligent admission processing and
          document verification.
        </p>

        <span>© 2026 Smart Enroll</span>
      </footer>
    </div>
  );
}

export default App;