import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../../context/AuthContext";
import { getApplicationTimeline, getPrograms } from "../../services/api";
import PageHeader from "../../components/PageHeader";
import StatusBadge from "../../components/StatusBadge";
import "./ApplicationStatus.css";

const STAGE_TONE = {
  COMPLETED: "success",
  CURRENT: "info",
  PENDING: "neutral",
};

const STAGE_TEXT = {
  COMPLETED: "Completed",
  CURRENT: "Current",
  PENDING: "Pending",
};

export default function ApplicationStatus() {
  const { session } = useAuth();
  const navigate = useNavigate();
  const [timeline, setTimeline] = useState(null);
  const [programme, setProgramme] = useState(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    let isMounted = true;

    Promise.all([getApplicationTimeline(session?.applicantId), getPrograms()]).then(
      ([timelineResult, programs]) => {
        if (!isMounted) return;
        setTimeline(timelineResult);
        setProgramme(programs.find((p) => p.id === timelineResult?.programmeId) ?? null);
        setIsLoading(false);
      }
    );

    return () => {
      isMounted = false;
    };
  }, [session]);

  if (isLoading) return <p>Loading your application status...</p>;
  if (!timeline) return <p>No application found.</p>;

  return (
    <div>
      <PageHeader
        title="Application Status"
        subtitle={programme ? `${programme.name} — ${programme.fullName}` : "Programme"}
      />

      <div className="card status-summary">
        <div className="status-summary-item">
          <span className="status-summary-label">Application ID</span>
          <span className="status-summary-value">{timeline.applicationId}</span>
        </div>
        <div className="status-summary-item">
          <span className="status-summary-label">Programme</span>
          <span className="status-summary-value">{programme?.name ?? "—"}</span>
        </div>
        <div className="status-summary-item">
          <span className="status-summary-label">Status</span>
          <StatusBadge code={timeline.status} />
        </div>
      </div>

      <div className="card timeline-card">
        <h3 className="status-card-heading">Processing Timeline</h3>
        <ol className="timeline-list">
          {timeline.stages.map((stage) => (
            <li key={stage.label} className={`timeline-item state-${stage.state}`}>
              <span className="timeline-marker" aria-hidden="true">
                {stage.state === "COMPLETED" ? "\u2713" : ""}
              </span>
              <div className="timeline-content">
                <span className="timeline-label">{stage.label}</span>
                <StatusBadge label={STAGE_TEXT[stage.state]} tone={STAGE_TONE[stage.state]} />
              </div>
            </li>
          ))}
        </ol>
      </div>

      <div className="card action-card">
        <div className="action-block">
          <span className="action-label">Current Smart Enroll Action</span>
          <p className="action-text">{timeline.currentAction}</p>
        </div>
        {timeline.applicantAction && (
          <div className="action-block">
            <span className="action-label applicant-action-label">Applicant Action Required</span>
            <p className="action-text">{timeline.applicantAction}</p>
            <button className="btn btn-accent" onClick={() => navigate("/documents")}>
              Upload Documents
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
