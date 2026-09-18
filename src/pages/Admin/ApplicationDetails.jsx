import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import PageHeader from "../../components/PageHeader";
import StatusBadge from "../../components/StatusBadge";
import WorkflowPipeline from "../../components/WorkflowPipeline";
import PrototypeNotice from "../../components/PrototypeNotice";
import { EmptyState, LoadingState } from "../../components/AsyncState";
import { getAdminApplicationDetails } from "../../services/api";
import "./Admin.css";

export default function ApplicationDetails() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [data, setData] = useState(undefined);

  useEffect(() => {
    getAdminApplicationDetails(id).then(setData);
  }, [id]);

  if (data === undefined) return <LoadingState message="Loading application details…" />;
  if (!data) {
    return (
      <div>
        <PageHeader title="Application not found" />
        <EmptyState title="Application not found" message="The requested application could not be located." />
        <button className="btn btn-secondary" onClick={() => navigate("/admin/applications")}>Back to Applications</button>
      </div>
    );
  }

  return (
    <div>
      <PageHeader
        title={data.applicationId}
        subtitle={`${data.applicantName} · ${data.programme?.fullName ?? data.programmeId}`}
        actions={<button className="btn btn-secondary btn-sm" onClick={() => navigate("/admin/applications")}>Back</button>}
      />

      <PrototypeNotice>
        This admin view reads the same centralized frontend demo state as the applicant portal. No
        live backend, OCR engine or external verification API is connected yet.
      </PrototypeNotice>

      <div className="admin-detail-grid">
        <section className="card admin-section">
          <h2>Applicant &amp; Application</h2>
          <dl className="admin-kv">
            <dt>Name</dt><dd>{data.applicantName}</dd>
            <dt>Email</dt><dd>{data.email}</dd>
            <dt>Programme</dt><dd>{data.programme?.name ?? data.programmeId}</dd>
            <dt>Submitted</dt><dd>{data.submittedAt}</dd>
            <dt>Application Status</dt><dd><StatusBadge code={data.status} /></dd>
            <dt>Eligibility</dt><dd><StatusBadge code={data.eligibility?.overall ?? data.eligibilityStatus} /></dd>
          </dl>
        </section>

        <section className="card admin-section">
          <h2>Academic Information</h2>
          <dl className="admin-kv">
            <dt>Qualification</dt><dd>{data.academic?.qualification ?? "—"}</dd>
            <dt>Institution</dt><dd>{data.academic?.institution ?? "—"}</dd>
            <dt>Result</dt><dd>{data.academic?.result ?? "—"}</dd>
            <dt>Current Smart Enroll Action</dt><dd>{data.currentAction}</dd>
          </dl>
        </section>
      </div>

      {data.workflow && <WorkflowPipeline workflow={data.workflow} />}

      <section className="card admin-section">
        <h2>Documents &amp; Verification</h2>
        {data.documents.length ? (
          <div className="admin-table-wrap">
            <table className="admin-table">
              <thead><tr><th>Document</th><th>File</th><th>Status</th><th>Authoritative Verification</th></tr></thead>
              <tbody>
                {data.documents.map((doc) => (
                  <tr key={doc.id}>
                    <td>{doc.name}</td>
                    <td>{doc.fileName ?? "Not uploaded"}</td>
                    <td><StatusBadge code={doc.status} /></td>
                    <td>
                      {doc.details?.authoritative?.status
                        ? <StatusBadge code={doc.details.authoritative.status} />
                        : <span className="admin-muted">Not available / pending</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="admin-muted">Detailed document records are not populated for this demonstration applicant.</p>
        )}
      </section>

      <div className="admin-detail-grid">
        <section className="card admin-section">
          <h2>Processing Timeline</h2>
          <div className="admin-timeline">
            {data.timeline?.stages?.map((stage) => (
              <div className={`admin-stage ${stage.state.toLowerCase()}`} key={stage.label}>
                <span className="admin-stage-dot" />
                <div><span className="admin-stage-label">{stage.label}</span><div className="admin-muted">{stage.state}</div></div>
              </div>
            ))}
          </div>
          <p className="admin-muted">Applicant action: {data.timeline?.applicantAction}</p>
        </section>

        <section className="card admin-section">
          <h2>Exceptions</h2>
          {data.exceptions.length ? (
            <div className="admin-exception-list">
              {data.exceptions.map((exception) => (
                <div className="admin-exception" key={exception.id}>
                  <div className="admin-exception-top">
                    <b>{exception.type.replaceAll("_", " ")}</b>
                    <StatusBadge label={exception.status} tone={exception.status === "RESOLVED" ? "success" : exception.status === "OPEN" ? "danger" : "warning"} />
                  </div>
                  <p style={{ fontSize: "13px" }}>{exception.description}</p>
                  <span className="admin-muted">{exception.id} · {exception.createdAt}</span>
                </div>
              ))}
            </div>
          ) : (
            <p className="admin-muted">No exceptions are associated with this application.</p>
          )}
        </section>
      </div>
    </div>
  );
}
