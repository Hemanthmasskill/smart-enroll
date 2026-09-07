import { useEffect, useState } from "react";
import { useAuth } from "../../context/AuthContext";
import { getEligibility, getPrograms } from "../../services/api";
import PageHeader from "../../components/PageHeader";
import StatusBadge from "../../components/StatusBadge";
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
  ELIGIBILITY_CHECK: {
    heading: "Eligibility Evaluation Pending",
    tone: "warning",
    description:
      "Evaluation is still in progress. Some criteria are waiting on document verification.",
  },
};

export default function Eligibility() {
  const { session } = useAuth();
  const [eligibility, setEligibility] = useState(null);
  const [programme, setProgramme] = useState(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    let isMounted = true;

    Promise.all([getEligibility(session?.applicantId), getPrograms()]).then(
      ([eligibilityResult, programs]) => {
        if (!isMounted) return;
        setEligibility(eligibilityResult);
        setProgramme(programs.find((p) => p.id === eligibilityResult?.programmeId) ?? null);
        setIsLoading(false);
      }
    );

    return () => {
      isMounted = false;
    };
  }, [session]);

  if (isLoading) return <p>Loading your eligibility status...</p>;
  if (!eligibility) return <p>No eligibility evaluation is available yet.</p>;

  const overall = OVERALL_COPY[eligibility.overall];

  return (
    <div>
      <PageHeader
        title="Eligibility Status"
        subtitle={programme ? `${programme.name} — ${programme.fullName}` : "Programme"}
      />

      <div className="card eligibility-overall">
        <div>
          <span className="eligibility-overall-label">Overall Result</span>
          <h2 className="eligibility-overall-heading">{overall.heading}</h2>
        </div>
        <StatusBadge label={overall.heading} tone={overall.tone} />
      </div>
      <p className="eligibility-overall-description">{overall.description}</p>

      <div className="card eligibility-card">
        <h3 className="eligibility-card-heading">Admission Criteria &amp; Evaluation</h3>
        <p className="eligibility-caption">
          Configured programme rules on the left, your application's evaluation against each rule
          on the right.
        </p>

        <div className="eligibility-rows">
          {eligibility.evaluation.map((item) => (
            <div className="eligibility-row" key={item.label}>
              <div className="eligibility-row-info">
                <span className="eligibility-row-label">{item.label}</span>
                <span className="eligibility-row-configured">{item.configured}</span>
              </div>
              <StatusBadge code={item.result} />
            </div>
          ))}
        </div>
      </div>

      <div className="card eligibility-explanation">
        <h3 className="eligibility-card-heading">How eligibility is evaluated</h3>
        <p>
          Eligibility criteria for each programme are configured system rules set by the
          institution. Smart Enroll checks your application and documents against these fixed
          rules — it does not invent, infer, or adjust admission criteria on its own.
        </p>
      </div>
    </div>
  );
}
