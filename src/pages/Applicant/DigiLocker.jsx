import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../../context/AuthContext";
import { connectDigiLocker, useVerifiedDigiLockerRecord } from "../../services/api";
import PageHeader from "../../components/PageHeader";
import StatusBadge from "../../components/StatusBadge";
import PrototypeNotice from "../../components/PrototypeNotice";
import "./DigiLocker.css";

const CONNECTION_STATES = {
  IDLE: "idle",
  CONNECTING: "connecting",
  CONNECTED: "connected",
};

export default function DigiLocker() {
  const { session } = useAuth();
  const navigate = useNavigate();

  const [connectionState, setConnectionState] = useState(CONNECTION_STATES.IDLE);
  const [result, setResult] = useState(null);
  const [usedRecordIds, setUsedRecordIds] = useState([]);
  const [feedback, setFeedback] = useState("");
  const [isUsingRecord, setIsUsingRecord] = useState(false);

  const handleConnect = async () => {
    setConnectionState(CONNECTION_STATES.CONNECTING);
    setFeedback("");
    try {
      const response = await connectDigiLocker(session?.applicantId);
      setResult(response);
      setConnectionState(CONNECTION_STATES.CONNECTED);
    } catch (error) {
      setConnectionState(CONNECTION_STATES.IDLE);
      setFeedback(`Connection failed: ${error.message}`);
    }
  };

  const handleUseRecord = async (recordId) => {
    setIsUsingRecord(true);
    setFeedback("");
    try {
      const response = await useVerifiedDigiLockerRecord(session?.applicantId, recordId);
      setUsedRecordIds((prev) => (prev.includes(recordId) ? prev : [...prev, recordId]));
      setFeedback(
        `${response.document.name} is now authoritatively verified in the frontend simulation.`
      );
    } catch (error) {
      setFeedback(`Unable to use verified record: ${error.message}`);
    } finally {
      setIsUsingRecord(false);
    }
  };

  return (
    <div>
      <PageHeader
        title="Verify Academic Records with DigiLocker"
        subtitle="Smart Enroll can verify supported academic records using authoritative credentials available through DigiLocker/NAD with your consent."
      />

      <PrototypeNotice>
        DigiLocker/NAD integration on this page is a frontend simulation only. A production system
        requires authorized APIs, applicant consent and issuer-record availability.
      </PrototypeNotice>

      {feedback && (
        <div className="digilocker-feedback" role="status" aria-live="polite">
          {feedback}
        </div>
      )}

      <div className="card digilocker-card">
        {connectionState === CONNECTION_STATES.IDLE && (
          <div className="digilocker-connect">
            <p className="digilocker-copy">
              Connecting DigiLocker lets Smart Enroll check whether your academic records can be
              confirmed directly with the issuing institution, in addition to the documents you
              upload manually.
            </p>
            <button className="btn btn-accent" onClick={handleConnect}>
              Connect DigiLocker
            </button>
          </div>
        )}

        {connectionState === CONNECTION_STATES.CONNECTING && (
          <div className="digilocker-connect" role="status" aria-live="polite">
            <div className="digilocker-spinner" aria-hidden="true" />
            <p className="digilocker-copy">Connecting...</p>
          </div>
        )}

        {connectionState === CONNECTION_STATES.CONNECTED && (
          <div>
            <div className="digilocker-status-row">
              <StatusBadge label="DigiLocker Connected" tone="success" />
              <span className="digilocker-applicant-name">{result.applicantName}</span>
            </div>

            <h3 className="digilocker-section-heading">Academic Records Found</h3>

            {result.records.length === 0 ? (
              <p className="digilocker-empty">
                No academic records were found for this applicant through DigiLocker/NAD.
              </p>
            ) : (
              <div className="digilocker-records">
                {result.records.map((record) => {
                  const isUsed = usedRecordIds.includes(record.id);
                  return (
                    <div key={record.id} className="digilocker-record">
                      <div className="digilocker-record-details">
                        <span className="digilocker-record-type">{record.documentType}</span>
                        <span className="digilocker-record-issuer">{record.issuer}</span>
                        <span className="digilocker-record-meta">Year: {record.year}</span>
                      </div>
                      <div className="digilocker-record-status">
                        <StatusBadge code={record.status} />
                        <button
                          className="btn btn-secondary btn-sm"
                          onClick={() => handleUseRecord(record.id)}
                          disabled={isUsed || isUsingRecord}
                        >
                          {isUsed ? "Record in Use" : isUsingRecord ? "Linking…" : "Use Verified Record"}
                        </button>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}

            <div className="digilocker-footer-actions">
              <button className="btn btn-ghost" onClick={() => navigate("/documents")}>
                Back to Documents
              </button>
            </div>
          </div>
        )}

        <p className="digilocker-disclaimer">
          DigiLocker verification depends on credential availability and authorized integration.
          This page is a frontend simulation only — no live DigiLocker or NAD connection exists yet.
        </p>
      </div>
    </div>
  );
}
