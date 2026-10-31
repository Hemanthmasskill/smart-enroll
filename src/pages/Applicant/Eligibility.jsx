import { useEffect, useState } from "react";
import { useAuth } from "../../context/AuthContext";
import { getEligibility, getPrograms } from "../../services/api";
import PageHeader from "../../components/PageHeader";
import StatusBadge from "../../components/StatusBadge";
import PrototypeNotice from "../../components/PrototypeNotice";
import { EmptyState, ErrorState, LoadingState } from "../../components/AsyncState";
import "./Eligibility.css";

const OVERALL_COPY = {
  ELIGIBLE: {
    heading: "Eligible",
    tone: "success",
    description: "All configured eligibility criteria for this programme have been satisfied.",
  },
  INELIGIBLE: {
    heading: "Not Eligible",
    tone: "danger",
    description: "One or more configured eligibility criteria were not satisfied.",
  },
  NEEDS_REVIEW: {
    heading: "Needs Manual Review",
    tone: "warning",
    description:
      "Deterministic evaluation completed. One or more criteria require manual verification by an admissions administrator.",
  },
  ELIGIBILITY_CHECK: {
    heading: "Eligibility Evaluation Pending",
    tone: "warning",
    description:
      "Evaluation is in progress. Criteria evaluation will run when document verification completes.",
  },
  DEPENDENCY_PENDING: {
    heading: "Eligibility Evaluation Pending",
    tone: "neutral",
    description:
      "Automated evaluation is pending completion of upstream workflow stages.",
  },
};

export default function Eligibility() {
  const { session } = useAuth();
  const [eligibility, setEligibility] = useState(null);
  const [programme, setProgramme] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let isMounted = true;

    Promise.all([getEligibility(session?.applicantId), getPrograms()])
      .then(([eligibilityResult, programs]) => {
        if (!isMounted) return;
        setEligibility(eligibilityResult);
        setProgramme(programs.find((p) => p.id === eligibilityResult?.programmeId) ?? null);
      })
      .catch((loadError) => {
        if (isMounted) setError(loadError.message || "Unable to load eligibility status.");
      })
      .finally(() => {
        if (isMounted) setIsLoading(false);
      });

    return () => {
      isMounted = false;
    };
  }, [session]);

  if (isLoading) return <LoadingState message="Loading your eligibility status…" />;
  if (error) return <ErrorState message={error} />;
  if (!eligibility) {
    return <EmptyState title="No eligibility evaluation yet" message="Submit an application to begin evaluation." />;
  }

  const overall = OVERALL_COPY[eligibility.overall] ?? OVERALL_COPY.ELIGIBILITY_CHECK;
  const isNeedsReview = eligibility.overall === "NEEDS_REVIEW";

  return (
    <div>
      <PageHeader
        title="Eligibility Status"
        subtitle={programme ? `${programme.name} — ${programme.fullName}` : "Programme"}
      />

      <PrototypeNotice>
        Eligibility is evaluated by the deterministic server-side Eligibility Engine (Increment 16)
        against canonical, versioned programme rules. The AI workflow does not create, infer, or modify
        admission criteria. Exceptions (Increment 17) and notifications (Increment 18) remain dependency boundaries.
      </PrototypeNotice>

      {isNeedsReview && (
        <div className="eligibility-review-banner" role="alert">
          <strong>Manual Administrative Review Required:</strong> Some eligibility criteria could not be
          definitively confirmed from automatic OCR extraction (e.g. subject mark verification or degree equivalency).
          An admissions officer will review your physical documents.
        </div>
      )}

      <div className="card eligibility-overall">
        <div>
          <span className="eligibility-overall-label">Overall Result</span>
          <h2 className="eligibility-overall-heading">{overall.heading}</h2>
        </div>
        <StatusBadge label={overall.heading} tone={overall.tone} />
      </div>
      <p className="eligibility-overall-description">{eligibility.summary || overall.description}</p>

      <div className="card eligibility-card">
        <h3 className="eligibility-card-heading">Admission Criteria &amp; Evaluation</h3>
        <p className="eligibility-caption">
          Configured programme rules on the left, deterministic server-side evaluation against verified document evidence
          on the right.
        </p>

        <div className="eligibility-rows">
          {eligibility.evaluation && eligibility.evaluation.length > 0 ? (
            eligibility.evaluation.map((item) => (
              <div className="eligibility-row" key={item.ruleId || item.label}>
                <div className="eligibility-row-info">
                  <span className="eligibility-row-label">{item.label}</span>
                  <span className="eligibility-row-configured">
                    <strong>Rule:</strong> {item.configured}
                  </span>
                  {item.observed && (
                    <span className="eligibility-row-observed">
                      <strong>Observed:</strong> {item.observed}
                    </span>
                  )}
                  {item.reason && (
                    <span className="eligibility-row-reason">{item.reason}</span>
                  )}
                  {item.evidence && item.evidence.length > 0 && (
                    <div className="eligibility-evidence-list">
                      {item.evidence.map((ev, idx) => (
                        <span key={idx} className="eligibility-evidence-tag">
                          {ev.documentType}: {ev.field} = {String(ev.value)}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
                <StatusBadge code={item.result} />
              </div>
            ))
          ) : (
            <p className="eligibility-caption">No per-rule evaluation records available yet.</p>
          )}
        </div>

        {(eligibility.ruleVersion || eligibility.inputHash) && (
          <div className="eligibility-meta-footer">
            {eligibility.ruleVersion && <span>Rule Version: v{eligibility.ruleVersion}</span>}
            {eligibility.evaluatorVersion && <span>Evaluator: v{eligibility.evaluatorVersion}</span>}
            {eligibility.inputHash && (
              <span>Input Hash: {eligibility.inputHash.slice(0, 16)}…</span>
            )}
            {eligibility.evaluatedAt && (
              <span>Evaluated: {new Date(eligibility.evaluatedAt).toLocaleString()}</span>
            )}
          </div>
        )}
      </div>

      <div className="card eligibility-explanation">
        <h3 className="eligibility-card-heading">How eligibility is evaluated</h3>
        <p>
          Eligibility criteria for each programme are versioned system rules configured by the
          institution. Smart Enroll evaluates your verified documents against these pure, deterministic
          rules — it does not invent, infer, or adjust admission criteria on its own, and never uses
          language models to guess or modify admission decisions.
        </p>
      </div>
    </div>
  );
}
