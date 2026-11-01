import { useEffect, useMemo, useState } from "react";
import PageHeader from "../../components/PageHeader";
import StatusBadge from "../../components/StatusBadge";
import { getAdminExceptions, resolveException } from "../../services/exceptionsApi";
import "./Admin.css";

const ALL_TYPES = [
  "NAME_MISMATCH",
  "DOB_MISMATCH",
  "MISSING_DOCUMENT",
  "UNREADABLE_DOCUMENT",
  "VERIFICATION_UNAVAILABLE",
  "ACADEMIC_MISMATCH",
  "DUPLICATE_DOCUMENT",
  "INVALID_FILE",
  "ELIGIBILITY_CONFLICT",
];

export default function Exceptions() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [successMsg, setSuccessMsg] = useState(null);

  // Filters
  const [status, setStatus] = useState("ALL");
  const [severity, setSeverity] = useState("ALL");
  const [type, setType] = useState("ALL");

  // Detail / Resolution modal state
  const [selectedException, setSelectedException] = useState(null);
  const [resolutionReason, setResolutionReason] = useState("");
  const [resolving, setResolving] = useState(false);
  const [resolutionError, setResolutionError] = useState(null);

  const fetchExceptions = () => {
    setLoading(true);
    setError(null);
    getAdminExceptions({ status, severity, type })
      .then((data) => {
        setItems(Array.isArray(data) ? data : []);
        setLoading(false);
      })
      .catch((err) => {
        setError(err.message || "Failed to load exceptions.");
        setLoading(false);
      });
  };

  useEffect(() => {
    fetchExceptions();
  }, [status, severity, type]);

  const filtered = useMemo(() => {
    return items.filter((e) => {
      const matchStatus = status === "ALL" || e.status === status;
      const matchSeverity = severity === "ALL" || e.severity === severity;
      const matchType = type === "ALL" || e.type === type;
      return matchStatus && matchSeverity && matchType;
    });
  }, [items, status, severity, type]);

  const handleOpenDetail = (item) => {
    setSelectedException(item);
    setResolutionReason("");
    setResolutionError(null);
  };

  const handleCloseDetail = () => {
    setSelectedException(null);
    setResolutionReason("");
    setResolutionError(null);
  };

  const handleResolveSubmit = async (e) => {
    e.preventDefault();
    const trimmed = resolutionReason.trim();
    if (trimmed.length < 5) {
      setResolutionError("A meaningful resolution reason of at least 5 characters is required.");
      return;
    }

    setResolving(true);
    setResolutionError(null);
    const excId = selectedException.exceptionId || selectedException.id;

    try {
      const resolved = await resolveException(excId, trimmed);
      setSuccessMsg(`Exception ${excId} resolved successfully.`);
      setSelectedException(resolved);
      fetchExceptions();
      setTimeout(() => setSuccessMsg(null), 5000);
    } catch (err) {
      setResolutionError(err.message || "Failed to resolve exception. Please try again.");
    } finally {
      setResolving(false);
    }
  };

  return (
    <div>
      <PageHeader
        title="Exceptions"
        subtitle="Monitor cases where autonomous processing encountered missing, mismatched, or unverifiable information."
      />

      {successMsg && (
        <div className="admin-feedback" style={{ background: "#ecfdf5", borderColor: "#a7f3d0", color: "#065f46" }}>
          {successMsg}
        </div>
      )}

      {error && (
        <div className="admin-feedback" style={{ background: "#fef2f2", borderColor: "#fecaca", color: "#991b1b" }}>
          {error}
        </div>
      )}

      <section className="card admin-panel">
        <div className="admin-controls">
          {/* Index 0: Status select */}
          <select className="admin-control" value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="ALL">All statuses</option>
            <option value="OPEN">OPEN</option>
            <option value="MONITORING">MONITORING</option>
            <option value="RESOLVED">RESOLVED</option>
          </select>

          {/* Index 1: Severity select (Preserves Cypress index 1 selection) */}
          <select className="admin-control" value={severity} onChange={(e) => setSeverity(e.target.value)}>
            <option value="ALL">All severities</option>
            <option value="CRITICAL">CRITICAL</option>
            <option value="HIGH">HIGH</option>
            <option value="MEDIUM">MEDIUM</option>
            <option value="LOW">LOW</option>
          </select>

          {/* Index 2: Type filter */}
          <select className="admin-control" value={type} onChange={(e) => setType(e.target.value)}>
            <option value="ALL">All types</option>
            {ALL_TYPES.map((t) => (
              <option key={t} value={t}>
                {t.replaceAll("_", " ")}
              </option>
            ))}
          </select>
        </div>

        {loading ? (
          <div className="admin-empty">Loading exceptions...</div>
        ) : filtered.length === 0 ? (
          <div className="admin-empty">No exceptions found matching the selected criteria.</div>
        ) : (
          <div className="admin-table-wrap">
            <table className="admin-table">
              <thead>
                <tr>
                  <th>Exception</th>
                  <th>Application</th>
                  <th>Applicant</th>
                  <th>Type</th>
                  <th>Description</th>
                  <th>Severity</th>
                  <th>Created</th>
                  <th>Status</th>
                  <th>Action</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((e) => {
                  const excId = e.exceptionId || e.id;
                  return (
                    <tr key={excId}>
                      <td><strong>{excId}</strong></td>
                      <td>{e.applicationId}</td>
                      <td>{e.applicantName}</td>
                      <td>{e.type.replaceAll("_", " ")}</td>
                      <td>{e.description}</td>
                      <td>
                        <span className={`severity-${e.severity}`}>{e.severity}</span>
                      </td>
                      <td>{e.createdAt}</td>
                      <td>
                        <StatusBadge
                          label={e.status}
                          tone={
                            e.status === "RESOLVED"
                              ? "success"
                              : e.status === "OPEN"
                              ? "danger"
                              : "warning"
                          }
                        />
                      </td>
                      <td>
                        <button
                          type="button"
                          className="admin-link"
                          onClick={() => handleOpenDetail(e)}
                        >
                          View / Resolve
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* Exception Detail & Resolution Modal */}
      {selectedException && (
        <div
          style={{
            position: "fixed",
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            backgroundColor: "rgba(0, 0, 0, 0.45)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            zIndex: 1000,
            padding: "20px",
          }}
        >
          <div
            className="card admin-panel"
            style={{
              maxWidth: "680px",
              width: "100%",
              maxHeight: "90vh",
              overflowY: "auto",
              background: "#fff",
              position: "relative",
            }}
          >
            <div className="admin-panel-head">
              <span className="admin-panel-title">
                Exception Details: {selectedException.exceptionId || selectedException.id}
              </span>
              <button
                type="button"
                onClick={handleCloseDetail}
                style={{
                  background: "none",
                  border: "none",
                  fontSize: "18px",
                  cursor: "pointer",
                  color: "#6b7280",
                }}
              >
                ✕
              </button>
            </div>

            <div className="admin-detail-grid" style={{ marginBottom: "16px" }}>
              <dl className="admin-kv">
                <dt>Application ID</dt>
                <dd>{selectedException.applicationId}</dd>
                <dt>Applicant Name</dt>
                <dd>{selectedException.applicantName || "N/A"}</dd>
                <dt>Exception Type</dt>
                <dd>{selectedException.type.replaceAll("_", " ")}</dd>
                <dt>Severity</dt>
                <dd>
                  <span className={`severity-${selectedException.severity}`}>
                    {selectedException.severity}
                  </span>
                </dd>
              </dl>
              <dl className="admin-kv">
                <dt>Status</dt>
                <dd>
                  <StatusBadge
                    label={selectedException.status}
                    tone={
                      selectedException.status === "RESOLVED"
                        ? "success"
                        : selectedException.status === "OPEN"
                        ? "danger"
                        : "warning"
                    }
                  />
                </dd>
                <dt>Source</dt>
                <dd>{selectedException.source || "SYSTEM"}</dd>
                <dt>Created At</dt>
                <dd>{selectedException.createdAt}</dd>
                {selectedException.resolvedAt && (
                  <>
                    <dt>Resolved At</dt>
                    <dd>{selectedException.resolvedAt}</dd>
                  </>
                )}
              </dl>
            </div>

            <div style={{ marginBottom: "16px" }}>
              <strong>Description:</strong>
              <p style={{ marginTop: "4px", color: "#374151", fontSize: "14px" }}>
                {selectedException.description}
              </p>
            </div>

            {selectedException.status === "RESOLVED" ? (
              <div
                style={{
                  padding: "12px",
                  background: "#f0fdf4",
                  border: "1px solid #bbf7d0",
                  borderRadius: "6px",
                  fontSize: "13px",
                  color: "#166534",
                }}
              >
                <strong>Resolution Justification:</strong>
                <p style={{ marginTop: "4px" }}>
                  {selectedException.resolutionReason || "Manually verified by administrator."}
                </p>
                {selectedException.resolvedBy && (
                  <p style={{ marginTop: "4px", fontSize: "12px", color: "#15803d" }}>
                    Resolved by: {typeof selectedException.resolvedBy === "object" ? selectedException.resolvedBy.email || selectedException.resolvedBy.fullName : selectedException.resolvedBy}
                  </p>
                )}
              </div>
            ) : (
              <form onSubmit={handleResolveSubmit} style={{ marginTop: "16px" }}>
                <label
                  htmlFor="resolutionReason"
                  style={{ display: "block", fontWeight: "600", fontSize: "13.5px", marginBottom: "6px" }}
                >
                  Admin Resolution Reason (Mandatory)
                </label>
                <textarea
                  id="resolutionReason"
                  rows={3}
                  value={resolutionReason}
                  onChange={(e) => setResolutionReason(e.target.value)}
                  placeholder="Provide a clear, non-empty justification for resolving this exception (e.g., manual affidavit verified, corrected document provided)..."
                  style={{
                    width: "100%",
                    padding: "8px 10px",
                    border: "1px solid #d1d5db",
                    borderRadius: "6px",
                    fontSize: "13.5px",
                    fontFamily: "inherit",
                    boxSizing: "border-box",
                  }}
                  disabled={resolving}
                />
                {resolutionError && (
                  <div style={{ color: "#dc2626", fontSize: "12.5px", marginTop: "4px" }}>
                    {resolutionError}
                  </div>
                )}
                <div style={{ display: "flex", gap: "10px", justifyContent: "flex-end", marginTop: "14px" }}>
                  <button
                    type="button"
                    onClick={handleCloseDetail}
                    style={{
                      padding: "8px 16px",
                      border: "1px solid #d1d5db",
                      borderRadius: "6px",
                      background: "#fff",
                      cursor: "pointer",
                      fontSize: "13.5px",
                    }}
                    disabled={resolving}
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    style={{
                      padding: "8px 18px",
                      border: "none",
                      borderRadius: "6px",
                      background: "#2563eb",
                      color: "#fff",
                      fontWeight: "600",
                      cursor: "pointer",
                      fontSize: "13.5px",
                    }}
                    disabled={resolving}
                  >
                    {resolving ? "Resolving..." : "Resolve Exception"}
                  </button>
                </div>
              </form>
            )}
          </div>
        </div>
      )}

      <p className="admin-muted" style={{ marginTop: "12px" }}>
        Exceptions provide visibility into autonomous processing issues. Admission decisions are not manually approved or rejected from this screen.
      </p>
    </div>
  );
}
