import StatusBadge from "./StatusBadge";
import "./DocumentVerificationPanel.css";

const AUTHORITATIVE_LABELS = {
  VERIFIED: { code: "VERIFIED", text: "Verified via DigiLocker/NAD" },
  PENDING: { code: "PROCESSING", text: "Authoritative verification pending" },
  UNAVAILABLE: { code: "UNVERIFIED", text: "Authoritative verification unavailable" },
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
export default function DocumentVerificationPanel({ documentName, details }) {
  if (!details) {
    return <p className="verification-empty">No verification data available yet.</p>;
  }

  const authoritative = AUTHORITATIVE_LABELS[details.authoritative?.status] ?? AUTHORITATIVE_LABELS.UNAVAILABLE;

  return (
    <div className="verification-panel">
      <p className="verification-doc-name">{documentName}</p>

      <section className="verification-section">
        <h4>OCR Extraction</h4>
        <p className="verification-caption">What the document contains, as read by OCR.</p>
        <dl className="verification-list">
          {Object.entries(details.extraction).map(([label, value]) => (
            <div key={label} className="verification-row">
              <dt>{label}</dt>
              <dd>{value}</dd>
            </div>
          ))}
        </dl>
      </section>

      <section className="verification-section">
        <h4>Content Validation</h4>
        <p className="verification-caption">
          Whether the extracted content structurally matches the applicant and application.
        </p>
        <dl className="verification-list">
          {Object.entries(details.validation).map(([label, value]) => (
            <div key={label} className="verification-row">
              <dt>{label}</dt>
              <dd>{value}</dd>
            </div>
          ))}
        </dl>
      </section>

      <section className="verification-section">
        <h4>Authoritative Verification</h4>
        <p className="verification-caption">
          Whether the academic record is confirmed through DigiLocker/NAD or another authoritative
          issuer source.
        </p>
        <div className="verification-row">
          <dt>DigiLocker/NAD</dt>
          <dd>
            <StatusBadge code={authoritative.code} label={authoritative.text} />
          </dd>
        </div>
      </section>

      <p className="verification-disclaimer">
        OCR extraction confirms only what the document states, not that it is genuine.
        Authenticity is established solely through authoritative verification where available.
      </p>
    </div>
  );
}
