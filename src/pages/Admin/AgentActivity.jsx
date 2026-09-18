import { useEffect, useMemo, useState } from "react";
import PageHeader from "../../components/PageHeader";
import StatusBadge from "../../components/StatusBadge";
import { getAgentActivity } from "../../services/api";
import "./Admin.css";

const STATUS_TONE = {
  COMPLETED: "success",
  PENDING: "warning",
  IN_PROGRESS: "info",
  PAUSED: "neutral",
  FLAGGED: "danger",
};

export default function AgentActivity() {
  const [logs, setLogs] = useState([]);
  const [applicationFilter, setApplicationFilter] = useState("ALL");
  const [stageFilter, setStageFilter] = useState("ALL");
  const [statusFilter, setStatusFilter] = useState("ALL");

  useEffect(() => {
    getAgentActivity().then(setLogs);
  }, []);

  const applicationOptions = useMemo(
    () => [...new Set(logs.map((l) => l.applicationId))],
    [logs]
  );
  const stageOptions = useMemo(() => [...new Set(logs.map((l) => l.stage))], [logs]);
  const statusOptions = useMemo(() => [...new Set(logs.map((l) => l.status))], [logs]);

  const filtered = useMemo(
    () =>
      logs.filter(
        (l) =>
          (applicationFilter === "ALL" || l.applicationId === applicationFilter) &&
          (stageFilter === "ALL" || l.stage === stageFilter) &&
          (statusFilter === "ALL" || l.status === statusFilter)
      ),
    [logs, applicationFilter, stageFilter, statusFilter]
  );

  return (
    <div>
      <PageHeader
        title="Agent Activity"
        subtitle="Observable audit trail of the Smart Enroll autonomous workflow — OBSERVE → PLAN → ACT → VERIFY → RE-PLAN."
      />

      <section className="card admin-panel">
        <div className="admin-controls">
          <label className="admin-filter-field">
            <span className="visually-hidden">Filter by application</span>
            <select
            aria-label="Filter by application"
            className="admin-control"
            value={applicationFilter}
            onChange={(e) => setApplicationFilter(e.target.value)}
          >
            <option value="ALL">All applications</option>
            {applicationOptions.map((id) => (
              <option key={id} value={id}>
                {id}
              </option>
            ))}
            </select>
          </label>
          <label className="admin-filter-field">
            <span className="visually-hidden">Filter by workflow stage</span>
            <select
            aria-label="Filter by workflow stage"
            className="admin-control"
            value={stageFilter}
            onChange={(e) => setStageFilter(e.target.value)}
          >
            <option value="ALL">All stages</option>
            {stageOptions.map((stage) => (
              <option key={stage} value={stage}>
                {stage}
              </option>
            ))}
            </select>
          </label>
          <label className="admin-filter-field">
            <span className="visually-hidden">Filter by status</span>
            <select
            aria-label="Filter by status"
            className="admin-control"
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
          >
            <option value="ALL">All statuses</option>
            {statusOptions.map((status) => (
              <option key={status} value={status}>
                {status}
              </option>
            ))}
            </select>
          </label>
        </div>

        <div className="admin-table-wrap">
          <table className="admin-table">
            <thead>
              <tr>
                <th>Timestamp</th>
                <th>Application</th>
                <th>Applicant</th>
                <th>Stage</th>
                <th>Action / Tool</th>
                <th>Result</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((log) => (
                <tr key={log.id}>
                  <td className="admin-muted">{log.timestamp}</td>
                  <td>{log.applicationId}</td>
                  <td>{log.applicantName}</td>
                  <td>
                    <span className={`stage-tag stage-${log.stage}`}>{log.stage}</span>
                  </td>
                  <td>
                    <div>{log.action}</div>
                    <div className="agent-tool">{log.tool}</div>
                  </td>
                  <td>{log.result}</td>
                  <td>
                    <StatusBadge label={log.status} tone={STATUS_TONE[log.status] ?? "neutral"} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {!filtered.length && <p className="admin-empty">No activity matches these filters.</p>}
        </div>
      </section>

      <p className="admin-muted" style={{ marginTop: "12px" }}>
        This is an audit trail of observable tool calls, deterministic decisions, and execution
        results. It does not display private reasoning, internal chain-of-thought, or fabricated
        model thoughts.
      </p>
    </div>
  );
}
