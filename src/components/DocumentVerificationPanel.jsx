import StatusBadge from "./StatusBadge";
import "./DocumentVerificationPanel.css";

const AUTHORITATIVE_LABELS = {
  SIMULATED_MATCH: { code: "SIMULATED_MATCH", text: "Simulated Match (Synthetic Fixture Only)" },
  SIMULATED_MISMATCH: { code: "SIMULATED_MISMATCH", text: "Simulated Mismatch (Conflict in fixture)" },
  SIMULATED_NOT_FOUND: { code: "SIMULATED_NOT_FOUND", text: "Simulated Record Not Found" },
  SIMULATION_UNAVAILABLE: { code: "SIMULATION_UNAVAILABLE", text: "Authoritative simulation unavailable" },
  PENDING: { code: "PROCESSING", text: "Authoritative verification pending" },
  UNAVAILABLE: { code: "UNAVAILABLE", text: "Authoritative verification unavailable" },
};

/**
 * Renders the three distinct layers of document checking used
 * throughout Smart Enroll (master prompt section 28):
 *   1. Extraction    — what OCR read from the document
 *   2. Validation     — does it structurally match the applicant/application
 *   3. Authoritative  — can it be confirmed via DigiLocker/NAD
 *
 * OCR success is never presented as proof of authenticity — that
 * distinction is intentional and should not be collapsed.
 */
export default function DocumentVerificationPanel({
  documentName,
  details,
  onRunAuthoritativeVerify,
  isAuthoritativeVerifying,
  authoritativeError,
  isEligibleForAuthoritative,
}) {
  if (!details) {
    return <p className="verification-empty">No verification data available yet.</p>;
  }

  const authStatus = details.authoritative?.status;
  let authoritative;
  if (authStatus === "VERIFIED") {
    // Only display a live-verification label when a genuine live provider result exists
    // and the application has reliable provider metadata supporting that claim.
    if (details.authoritative?.isLive && details.authoritative?.providerMetadata) {
      authoritative = { code: "VERIFIED", text: "Verified via Live DigiLocker/NAD" };
    } else {
      authoritative = { code: "UNAVAILABLE", text: "Authoritative verification unconfirmed" };
    }
  } else {
    authoritative = AUTHORITATIVE_LABELS[authStatus] ?? AUTHORITATIVE_LABELS.UNAVAILABLE;
  }

  const extractionEntries = details.extraction ? Object.entries(details.extraction) : [];
  const validationEntries = details.validation ? Object.entries(details.validation) : [];

  return (
    <div className="verification-panel">
      <p className="verification-doc-name">{documentName}</p>

      <section className="verification-section">
        <h4>OCR Extraction</h4>
        <p className="verification-caption">What the document contains, as read by OCR.</p>
        {extractionEntries.length > 0 ? (
          <dl className="verification-list">
            {extractionEntries.map(([label, value]) => (
              <div key={label} className="verification-row">
                <dt>{label}</dt>
                <dd>{value}</dd>
              </div>
            ))}
          </dl>
        ) : (
          <p className="verification-empty">No extraction data available.</p>
        )}
      </section>

      <section className="verification-section">
        <h4>Content Validation</h4>
        <p className="verification-caption">
          Whether the extracted content structurally matches the applicant and application.
        </p>
        {validationEntries.length > 0 ? (
          <dl className="verification-list">
            {validationEntries.map(([label, value]) => (
              <div key={label} className="verification-row">
                <dt>{label}</dt>
                <dd>{value}</dd>
              </div>
            ))}
          </dl>
        ) : (
          <dl className="verification-list">
            <div className="verification-row">
              <dt>Status</dt>
              <dd>Pending — validation not performed</dd>
            </div>
          </dl>
        )}
      </section>

      <section className="verification-section">
        <h4>Authoritative Verification</h4>
        <p className="verification-caption">
          Whether the academic record is confirmed through DigiLocker/NAD or a synthetic fixture simulation.
        </p>
        <div className="verification-row">
          <dt>DigiLocker / NAD Status</dt>
          <dd>
            <StatusBadge code={authoritative.code} label={authoritative.text} />
          </dd>
        </div>
        {details.authoritative?.recordId && (
          <div className="verification-row">
            <dt>Lookup Identifier</dt>
            <dd>{details.authoritative.recordId}</dd>
          </div>
        )}
        {details.authoritative?.message && (
          <div className="verification-row">
            <dt>Outcome Details</dt>
            <dd>{details.authoritative.message}</dd>
          </div>
        )}
        {onRunAuthoritativeVerify && (
          <div className="verification-action-group" style={{ marginTop: "1rem" }}>
            <button
              type="button"
              className="btn btn-secondary btn-sm"
              onClick={onRunAuthoritativeVerify}
              disabled={isAuthoritativeVerifying || !isEligibleForAuthoritative}
              data-testid="run-authoritative-verify-btn"
            >
              {isAuthoritativeVerifying
                ? "Verifying with Synthetic Provider…"
                : "Run Synthetic Verification"}
            </button>
            {!isEligibleForAuthoritative && (
              <p className="verification-hint" style={{ fontSize: "0.8rem", color: "var(--color-text-muted, #666)", marginTop: "0.25rem" }}>
                Document must complete OCR processing before running authoritative verification.
              </p>
            )}
            {authoritativeError && (
              <p className="verification-action-error" role="alert" style={{ color: "var(--color-danger, #dc2626)", fontSize: "0.85rem", marginTop: "0.5rem" }}>
                {authoritativeError}
              </p>
            )}
          </div>
        )}
      </section>

      <p className="verification-disclaimer">
        OCR extraction confirms only what the document states, not that it is genuine.
        Authenticity is established solely through live authoritative verification where available.
        Simulated fixture matches are synthetic evaluation aids only and do not establish document authenticity.
        The provider is synthetic and not connected to live DigiLocker, NAD, CBSE, or government APIs.
      </p>
    </div>
  );
}
