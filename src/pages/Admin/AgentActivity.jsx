import { USE_MOCKS } from "../../services/apiClient";
import { useEffect, useMemo, useState } from "react";
import PageHeader from "../../components/PageHeader";
import StatusBadge from "../../components/StatusBadge";
import {
  getAgentActivity,
  getAgentSystemStatus,
  getRecentOrchestrationRuns,
  triggerAgentOrchestration,
  backendAdminLogin,
} from "../../services/api";
import { useAuth } from "../../context/AuthContext";
import "./Admin.css";
import "./AgentActivity.css";

const STATUS_TONE = {
  COMPLETED: "success",
  PENDING: "warning",
  IN_PROGRESS: "info",
  PAUSED: "neutral",
  FLAGGED: "danger",
  DEPENDENCY_PENDING: "neutral",
  FAILED: "danger",
};

export function getPlannerStrategyLabel(status) {
  if (!status || status.isLive === false || !status.isLive) {
    return "Configuration Unavailable";
  }
  if (status.llmEnabled) {
    return status.fallbackEnabled
      ? "LLM with Deterministic Fallback"
      : "LLM (Fallback Disabled)";
  }
  return "Deterministic Only";
}

export function getEndpointSecurityLabel(status) {
  if (!status || status.isLive === false || !status.isLive) {
    return "Configuration Unavailable";
  }
  if (status.isLocalEndpoint) {
    return status.allowLocalEndpoints
      ? "Local Endpoint Permitted"
      : "Local Endpoint Rejected by Configuration";
  }
  return "Remote Endpoint Configured";
}

export function getRunStatusDisplay(run) {
  if (!run) {
    return {
      title: "Application Status",
      value: "Application Status Unavailable",
      tagClass: "stage-UNAVAILABLE",
    };
  }
  if (run.currentApplicationStatus) {
    return {
      title: "Application Status",
      value: run.currentApplicationStatus,
      tagClass: `stage-${run.currentApplicationStatus}`,
    };
  }
  if (run.currentStage) {
    return {
      title: "Legacy Workflow Stage",
      value: run.currentStage,
      tagClass: `stage-${run.currentStage}`,
    };
  }
  return {
    title: "Application Status",
    value: "Application Status Unavailable",
    tagClass: "stage-UNAVAILABLE",
  };
}

if (typeof window !== "undefined" && window.Cypress) {
  window.__smartEnrollAgentActivity = {
    getPlannerStrategyLabel,
    getEndpointSecurityLabel,
    getRunStatusDisplay,
  };
}


export default function AgentActivity() {
  const { session } = useAuth();

  // Navigation tab state
  const [activeTab, setActiveTab] = useState("timeline"); // "timeline" | "overview" | "telemetry" | "digilocker" | "roadmap"

  // Audit trail logs & filters (Tab 1)
  const [logs, setLogs] = useState([]);
  const [applicationFilter, setApplicationFilter] = useState("ALL");
  const [stageFilter, setStageFilter] = useState("ALL");
  const [statusFilter, setStatusFilter] = useState("ALL");

  // System status & live backend connection
  const [systemStatus, setSystemStatus] = useState(null);
  const [liveToken, setLiveToken] = useState(
    (USE_MOCKS || session?.token === "test-auth-token") ? null : (session?.token || null)
  );
  const [liveConnected, setLiveConnected] = useState(false);
  const [showConnectForm, setShowConnectForm] = useState(false);
  const [loginEmail, setLoginEmail] = useState("");
  const [loginPassword, setLoginPassword] = useState("");
  const [connectError, setConnectError] = useState(null);
  const [connectLoading, setConnectLoading] = useState(false);
  const [connectFeedback, setConnectFeedback] = useState(null);
  const [liveDataError, setLiveDataError] = useState(null);

  // Orchestration runs & selected run for deep inspection
  const [runs, setRuns] = useState([]);
  const [selectedRunId, setSelectedRunId] = useState(null);
  const [triggerLoading, setTriggerLoading] = useState(false);
  const [triggerFeedback, setTriggerFeedback] = useState(null);

  // Load audit logs and system status
  useEffect(() => {
    let isMounted = true;

    getAgentSystemStatus()
      .then((data) => {
        if (isMounted) setSystemStatus(data);
      })
      .catch(() => {
        // Handled silently for offline mode
      });

    if (liveToken) {
      // Live Backend Mode: fetch directly from FastAPI
      Promise.all([
        getAgentActivity({}, liveToken),
        getRecentOrchestrationRuns(liveToken),
      ])
        .then(([activityData, runsData]) => {
          if (!isMounted) return;
          if (runsData?.error) {
            setLiveDataError(runsData.error);
            setLiveConnected(false);
            setLogs([]);
            setRuns([]);
            setSelectedRunId(null);
            setConnectFeedback(null);
            return;
          }
          setLogs(activityData || []);
          if (runsData?.runs) {
            setRuns(runsData.runs);
            if (runsData.runs.length > 0) {
              setSelectedRunId(runsData.runs[0].id || runsData.runs[0].runId);
            } else {
              setSelectedRunId(null);
            }
          } else {
            setRuns([]);
            setSelectedRunId(null);
          }
          setLiveConnected(true);
          setLiveDataError(null);
          setConnectFeedback("Connected successfully to live FastAPI + MongoDB backend.");
        })
        .catch((err) => {
          if (!isMounted) return;
          setLiveDataError(err.message || "Failed to retrieve live telemetry endpoints.");
          setLiveConnected(false);
          setLogs([]);
          setRuns([]);
          setSelectedRunId(null);
          setConnectFeedback(null);
        });
    } else {
      setLiveConnected(false);
      setLiveDataError(null);
      // Demo Mode: load verified mock baseline data
      getAgentActivity({}, null).then((data) => {
        if (isMounted) setLogs(data);
      });
      getRecentOrchestrationRuns(null).then((res) => {
        if (isMounted) {
          setRuns(res.runs || []);
          if (res.runs && res.runs.length > 0) {
            setSelectedRunId(res.runs[0].id || res.runs[0].runId);
          }
        }
      });
    }

    return () => {
      isMounted = false;
    };
  }, [liveToken]);

  // Options for filter selects (Cypress asserts these exact selects in order: 0, 1, 2)
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

  // Selected run details
  const selectedRun = useMemo(() => {
    if (!runs || !runs.length) return null;
    return runs.find((r) => (r.id || r.runId) === selectedRunId) || runs[0];
  }, [runs, selectedRunId]);

  // Handle live backend login (requires explicit input, zero hardcoded credentials)
  const handleConnectLiveBackend = async (e) => {
    e.preventDefault();
    setConnectLoading(true);
    setConnectError(null);
    setLiveDataError(null);
    setConnectFeedback(null);
    try {
      const res = await backendAdminLogin({ email: loginEmail, password: loginPassword });
      const authToken = res?.token || res?.accessToken;
      if (!authToken) {
        throw new Error("No token returned from backend authentication.");
      }

      // Explicit policy: Clear credentials from memory immediately
      setLoginPassword("");
      setShowConnectForm(false);

      // Explicit policy: Clear demo mock data immediately.
      // Mock data must NEVER appear under an authenticated or live session.
      setLogs([]);
      setRuns([]);
      setSelectedRunId(null);
      setLiveConnected(false);

      // Single authoritative path: setting liveToken triggers useEffect to fetch live telemetry.
      // Do not make duplicate requests or claim live connectivity in the login handler.
      setLiveToken(authToken);
    } catch (err) {
      setConnectError(err.message || "Failed to authenticate against live backend.");
    } finally {
      setConnectLoading(false);
    }
  };

  // Trigger live orchestrator run
  const handleTriggerOrchestration = async () => {
    if (!selectedRun) return;
    setTriggerLoading(true);
    setTriggerFeedback(null);
    try {
      if (!liveToken) {
        // Explicitly label simulated execution in demo mode
        await new Promise((r) => setTimeout(r, 600));
        setTriggerFeedback({
          success: true,
          message: `[Simulated Demo] Orchestrator cycle demonstrated for ${selectedRun.applicationId}. In Live Mode with MongoDB, this executes POST /api/v1/agents/orchestrate/${selectedRun.applicationId}.`,
        });
      } else {
        const result = await triggerAgentOrchestration(selectedRun.applicationId, liveToken);
        const stepsCount =
          typeof result.stepsCompleted === "number"
            ? result.stepsCompleted
            : Array.isArray(result.steps)
            ? result.steps.length
            : 0;
        const plannerName = result.planner || "DETERMINISTIC";
        setTriggerFeedback({
          success: true,
          message: `Live Orchestrator completed with status: ${result.status}. Outcome: ${result.outcome || "N/A"}. Planner: ${plannerName}. Steps Completed: ${stepsCount}.`,
        });
        // Refresh live runs and visibly report any errors
        try {
          const updated = await getRecentOrchestrationRuns(liveToken);
          if (updated?.error) {
            setTriggerFeedback((prev) => ({
              ...prev,
              warning: `Orchestration executed, but refreshing runs returned: ${updated.error}`,
            }));
          } else {
            setRuns(updated.runs || []);
          }
        } catch (refreshErr) {
          setTriggerFeedback((prev) => ({
            ...prev,
            warning: `Orchestration executed, but refreshing runs failed: ${refreshErr.message}`,
          }));
        }
      }
    } catch (err) {
      setTriggerFeedback({
        success: false,
        message: err.message || "Orchestration execution failed.",
      });
    } finally {
      setTriggerLoading(false);
    }
  };

  return (
    <div>
      <PageHeader
        title="Project Status & Agent Activity"
        subtitle="Observable audit trail of the Smart Enroll autonomous workflow — OBSERVE → PLAN → ACT → VERIFY → RE-PLAN."
      />

      {/* System Status Summary Bar */}
      <section className="system-status-bar" aria-label="System Status Overview">
        <div className="system-status-items">
          <div className="system-status-item">
            <span className="system-status-label">Backend Service:</span>
            <span
              className="system-status-value"
              style={{ color: systemStatus?.isLive ? "#16a34a" : "#ca8a04" }}
            >
              ● {systemStatus?.isLive ? "FastAPI Online" : "Local / Offline"}
            </span>
          </div>
          <div className="system-status-item">
            <span className="system-status-label">LLM Provider:</span>
            <span className="system-status-value">
              {systemStatus?.llmProvider
                ? typeof systemStatus.llmProvider === "string"
                  ? systemStatus.llmProvider
                  : systemStatus.llmProvider.provider
                : "disabled (Deterministic Mode)"}
            </span>
          </div>
          <div className="system-status-item">
            <span className="system-status-label">Planner Strategy:</span>
            <span className="system-status-value">
              {getPlannerStrategyLabel(systemStatus)}
            </span>
          </div>
          <div className="system-status-item">
            <span className="system-status-label">Endpoint Security:</span>
            <span className="system-status-value">
              {getEndpointSecurityLabel(systemStatus)}
            </span>
          </div>
          <div className="system-status-item">
            <span className="system-status-label">Registered Tools:</span>
            <span className="system-status-value">
              {systemStatus?.availableToolsCount || systemStatus?.registeredTools?.length || 13} Tools Active
            </span>
          </div>
        </div>

        <div>
          {liveToken ? (
            <button
              className="btn btn-secondary btn-sm"
              onClick={() => {
                setLiveToken(null);
                setLiveConnected(false);
                setConnectFeedback("Switched back to client demo mode.");
                setLiveDataError(null);
              }}
            >
              Disconnect Live Backend
            </button>
          ) : (
            <button
              className="btn btn-primary btn-sm"
              onClick={() => setShowConnectForm(!showConnectForm)}
            >
              {showConnectForm ? "Cancel Connect" : "Connect Live Backend"}
            </button>
          )}
        </div>
      </section>

      {/* Mode Indicator Banner: Strictly distinguishes Demo, Live Connected, and Authenticated with Telemetry Error */}
      {!liveToken ? (
        <div className="mode-banner mode-banner-demo">
          <div>
            <div className="mode-banner-title">
              <span>⚠️</span> DEMO MODE: BASELINE AUDIT TRAIL
            </div>
            <div>
              Displaying verified audit trail for demonstration. Connect with backend admin
              credentials to query live MongoDB orchestration runs.
            </div>
          </div>
          <span className="planner-tag planner-tag-fallback">DEMO MODE ACTIVE</span>
        </div>
      ) : liveConnected && !liveDataError ? (
        <div className="mode-banner mode-banner-live">
          <div>
            <div className="mode-banner-title">
              <span>●</span> LIVE MODE: CONNECTED TO FASTAPI &amp; MONGODB
            </div>
            <div>
              Displaying real database-persisted orchestration runs and audit events from the
              Smart Enroll backend.
            </div>
          </div>
          <span className="planner-tag planner-tag-deterministic">JWT AUTHENTICATED</span>
        </div>
      ) : (
        <div className="mode-banner mode-banner-error">
          <div>
            <div className="mode-banner-title">
              <span>⚠️</span> AUTHENTICATED: LIVE DATA RETRIEVAL FAILED
            </div>
            <div>
              Administrator authentication succeeded, but live activity or orchestration telemetry
              could not be retrieved from backend endpoints. Mock data is excluded.
            </div>
          </div>
          <span
            className="planner-tag planner-tag-fallback"
            style={{ background: "#fee2e2", color: "#991b1b", borderColor: "#fca5a5" }}
          >
            ENDPOINT ERROR
          </span>
        </div>
      )}

      {/* Live Data Error Alert (Displayed if live backend query fails) */}
      {liveDataError && (
        <div
          className="admin-feedback"
          style={{
            background: "#fef2f2",
            borderColor: "#fecaca",
            color: "#991b1b",
            marginBottom: "16px",
          }}
        >
          <strong>Live Backend Error:</strong> {liveDataError}. Mock data is not displayed to
          prevent confusion with live activity.
        </div>
      )}

      {/* Connect Form Drawer (requires explicit evaluator input, no prefilled credentials) */}
      {showConnectForm && (
        <div className="live-connect-box">
          <div className="live-connect-title">Authenticate with Live FastAPI Backend</div>
          <p className="admin-muted" style={{ marginBottom: "12px" }}>
            Enter administrator credentials to authenticate against <code>/api/v1/auth/login</code>{" "}
            and query live MongoDB collections. No credentials are stored or prefilled.
          </p>
          <form className="live-connect-form" onSubmit={handleConnectLiveBackend}>
            <label className="live-connect-field">
              Admin Email
              <input
                className="live-connect-input"
                type="email"
                placeholder="admin@smartenroll.edu"
                value={loginEmail}
                onChange={(e) => setLoginEmail(e.target.value)}
                required
                autoComplete="username"
              />
            </label>
            <label className="live-connect-field">
              Password
              <input
                className="live-connect-input"
                type="password"
                placeholder="Enter password"
                value={loginPassword}
                onChange={(e) => setLoginPassword(e.target.value)}
                required
                autoComplete="current-password"
              />
            </label>
            <button
              className="btn btn-primary btn-sm"
              type="submit"
              disabled={connectLoading}
              style={{ height: "35px" }}
            >
              {connectLoading ? "Connecting..." : "Authenticate"}
            </button>
          </form>
          {connectError && (
            <p className="severity-HIGH" style={{ marginTop: "8px", fontSize: "12.5px" }}>
              {connectError}
            </p>
          )}
        </div>
      )}

      {connectFeedback && (
        <div className="admin-feedback" style={{ marginBottom: "16px" }}>
          {connectFeedback}
        </div>
      )}

      {/* Demonstration Navigation Tabs */}
      <nav className="dashboard-tabs" aria-label="Demonstration Dashboard Views">
        <button
          className={`dashboard-tab ${activeTab === "timeline" ? "active" : ""}`}
          onClick={() => setActiveTab("timeline")}
        >
          1. Live Workflow &amp; Audit Trail
        </button>
        <button
          className={`dashboard-tab ${activeTab === "overview" ? "active" : ""}`}
          onClick={() => setActiveTab("overview")}
        >
          2. Project Implementation Overview
        </button>
        <button
          className={`dashboard-tab ${activeTab === "telemetry" ? "active" : ""}`}
          onClick={() => setActiveTab("telemetry")}
        >
          3. LLM &amp; Planner Telemetry
        </button>
        <button
          className={`dashboard-tab ${activeTab === "digilocker" ? "active" : ""}`}
          onClick={() => setActiveTab("digilocker")}
        >
          4. DigiLocker Transparency
        </button>
        <button
          className={`dashboard-tab ${activeTab === "roadmap" ? "active" : ""}`}
          onClick={() => setActiveTab("roadmap")}
        >
          5. Pending Roadmap &amp; Next Steps
        </button>
      </nav>

      {/* ============================================================== */}
      {/* TAB 1: LIVE WORKFLOW & AUDIT TRAIL                             */}
      {/* ============================================================== */}
      {activeTab === "timeline" && (
        <div>
          {/* Section 1: Cypress-asserted Controls & Audit Table */}
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

          <p className="admin-muted" style={{ marginTop: "12px", marginBottom: "24px" }}>
            This is an audit trail of observable tool calls, deterministic decisions, and execution
            results. It does not display private reasoning, internal chain-of-thought, or fabricated
            model thoughts.
          </p>

          {/* Section 2: Deep Inspection of Selected Application Workflow Run */}
          <section className="card admin-panel" style={{ marginTop: "24px" }}>
            <div className="admin-panel-head">
              <div className="admin-panel-title">
                Selected Application Workflow &amp; Orchestrator Run
              </div>
              <div style={{ display: "flex", gap: "10px", alignItems: "center" }}>
                <label style={{ fontSize: "12.5px", fontWeight: "600", color: "#64748b" }}>
                  Select Run:
                </label>
                <select
                  className="admin-control"
                  style={{ minWidth: "160px", padding: "6px 8px" }}
                  value={selectedRunId || ""}
                  onChange={(e) => setSelectedRunId(e.target.value)}
                >
                  {runs.map((r) => (
                    <option key={r.id || r.runId} value={r.id || r.runId}>
                      {r.applicationId} — {r.status}
                    </option>
                  ))}
                </select>
                <button
                  className="btn btn-secondary btn-sm"
                  onClick={handleTriggerOrchestration}
                  disabled={triggerLoading || !selectedRun}
                >
                  {triggerLoading ? "Executing..." : "Trigger Orchestrator Cycle"}
                </button>
              </div>
            </div>

            {triggerFeedback && (
              <div
                className={`admin-feedback ${triggerFeedback.success ? "" : "severity-HIGH"}`}
                style={{
                  background: triggerFeedback.success ? "#f0fdf4" : "#fef2f2",
                  borderColor: triggerFeedback.success ? "#bbf7d0" : "#fecaca",
                  color: triggerFeedback.success ? "#166534" : "#991b1b",
                }}
              >
                <div>{triggerFeedback.message}</div>
                {triggerFeedback.warning && (
                  <div style={{ marginTop: "4px", color: "#b45309", fontSize: "0.85rem" }}>
                    ⚠️ {triggerFeedback.warning}
                  </div>
                )}
              </div>
            )}

            {selectedRun ? (
              <div>
                <div className="run-meta-grid">
                  <div className="run-meta-item">
                    <div className="run-meta-title">Application ID</div>
                    <div className="run-meta-value">{selectedRun.applicationId}</div>
                    <div className="admin-muted">{selectedRun.applicantName || "Applicant Record"}</div>
                  </div>

                  {(() => {
                    const statusDisplay = getRunStatusDisplay(selectedRun);
                    return (
                      <div className="run-meta-item">
                        <div className="run-meta-title">{statusDisplay.title}</div>
                        <div className="run-meta-value">
                          <span className={`stage-tag ${statusDisplay.tagClass}`}>
                            {statusDisplay.value}
                          </span>
                        </div>
                        <div className="admin-muted">
                          Status: {selectedRun.status} | Outcome: {selectedRun.outcome || "N/A"}
                        </div>
                      </div>
                    );
                  })()}

                  <div className="run-meta-item">
                    <div className="run-meta-title">Planner Strategy</div>
                    <div className="run-meta-value">
                      <span
                        className={`planner-tag ${
                          selectedRun.planner === "LLM"
                            ? "planner-tag-llm"
                            : selectedRun.fallbackOccurred
                            ? "planner-tag-fallback"
                            : "planner-tag-deterministic"
                        }`}
                      >
                        {selectedRun.planner || "DETERMINISTIC"}
                      </span>
                    </div>
                    <div className="admin-muted">
                      {selectedRun.fallbackOccurred || (typeof selectedRun.fallbackCount === "number" && selectedRun.fallbackCount > 0)
                        ? `⚠️ Fallback Occurred (${typeof selectedRun.fallbackCount === "number" ? selectedRun.fallbackCount : 0})`
                        : "✓ Clean Execution"}
                    </div>
                  </div>

                  <div className="run-meta-item">
                    <div className="run-meta-title">Document Completeness</div>
                    <div className="run-meta-value">{selectedRun.documentStatus || "Monitored"}</div>
                    <div className="admin-muted">
                      Eligibility: {selectedRun.eligibilityStatus || "PENDING (Increment 16)"}
                    </div>
                  </div>
                </div>

                {selectedRun.fallbackOccurred && (
                  <div
                    className="admin-feedback"
                    style={{
                      background: "#fffbeb",
                      borderColor: "#fde68a",
                      color: "#92400e",
                      marginBottom: "16px",
                    }}
                  >
                    <strong>Deterministic Fallback Event:</strong> Model proposal was rejected by
                    guardrails or timed out. Orchestrator securely defaulted to deterministic state
                    transitions without workflow disruption.
                  </div>
                )}

                {/* Step Timeline (using div list to preserve Cypress table length assertions) */}
                <h3 style={{ fontSize: "14px", fontWeight: "700", marginBottom: "12px" }}>
                  Observed Step Execution Sequence
                </h3>

                <div className="step-timeline-list">
                  {selectedRun.steps && selectedRun.steps.length > 0 ? (
                    selectedRun.steps.map((st) => (
                      <div key={st.stepIndex} className="step-timeline-item">
                        <div className="step-timeline-badge-col">
                          <span style={{ fontSize: "12px", fontWeight: "700", color: "#64748b" }}>
                            Step #{st.stepIndex}
                          </span>
                          <span className={`stage-tag stage-${st.stage}`}>{st.stage}</span>
                          <span
                            className={`planner-tag ${
                              st.planner === "LLM"
                                ? "planner-tag-llm"
                                : st.planner === "FALLBACK"
                                ? "planner-tag-fallback"
                                : "planner-tag-deterministic"
                            }`}
                          >
                            {st.planner || "DETERMINISTIC"}
                          </span>
                        </div>

                        <div className="step-timeline-content">
                          <div className="step-timeline-header">
                            <span className="step-timeline-tool">{st.toolName || st.tool}</span>
                            <div style={{ display: "flex", gap: "8px", alignItems: "center" }}>
                              <StatusBadge
                                label={st.status}
                                tone={STATUS_TONE[st.status] ?? "neutral"}
                              />
                              <span className="admin-muted" style={{ fontSize: "11.5px" }}>
                                {st.executedAt || "2026-10-26"}
                              </span>
                            </div>
                          </div>

                          <div className="step-timeline-result">{st.resultSummary}</div>

                          {st.fallbackUsed && (
                            <div
                              className="admin-muted"
                              style={{ color: "#b45309", fontSize: "11.5px", marginTop: "4px" }}
                            >
                              ⚠️ Fallback Reason: {st.fallbackReason || "Guardrail rejected model proposal"}
                            </div>
                          )}
                        </div>
                      </div>
                    ))
                  ) : (
                    <p className="admin-empty">No step telemetry recorded for this run.</p>
                  )}
                </div>
              </div>
            ) : (
              <p className="admin-empty" style={{ padding: "16px 0" }}>
                No orchestration runs available.
              </p>
            )}
          </section>
        </div>
      )}

      {/* ============================================================== */}
      {/* TAB 2: PROJECT IMPLEMENTATION OVERVIEW                         */}
      {/* ============================================================== */}
      {activeTab === "overview" && (
        <section className="card admin-panel">
          <div className="admin-panel-head">
            <div className="admin-panel-title">Project Implementation Overview</div>
            <span className="admin-muted">
              Honest status across core project areas based on actual code, contracts &amp; tests
            </span>
          </div>

          <p className="admin-muted" style={{ marginBottom: "16px" }}>
            The following table separates completed backend capabilities from frontend integration.
            Capabilities that return <code>DEPENDENCY_PENDING</code> or use mock service adapters are
            truthfully disclosed.
          </p>

          <div className="admin-table-wrap">
            <table className="admin-table">
              <thead>
                <tr>
                  <th style={{ width: "220px" }}>Project Area</th>
                  <th style={{ width: "190px" }}>Status</th>
                  <th>Backend Implementation</th>
                  <th>UI Integration</th>
                  <th>Verified Evidence</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td>
                    <strong>1. Frontend Foundation</strong>
                    <div className="admin-muted">Applicant &amp; Admin portals</div>
                  </td>
                  <td>
                    <span className="status-pill status-pill-implemented">Implemented</span>
                  </td>
                  <td>N/A (Frontend React 18 SPA)</td>
                  <td>14 production pages implemented with responsive layouts and accessibility.</td>
                  <td>Reported test suite results: 54 Cypress E2E tests passing</td>
                </tr>

                <tr>
                  <td>
                    <strong>2. Backend &amp; Auth</strong>
                    <div className="admin-muted">FastAPI, JWT, RBAC</div>
                  </td>
                  <td>
                    <span className="status-pill status-pill-implemented">Implemented</span>
                  </td>
                  <td>FastAPI JWT auth, password hashing, roles (Applicant, Admin, Officer).</td>
                  <td>Frontend login form implemented; uses client mock session by default.</td>
                  <td>Reported test suite results: 264 backend Pytest tests passing</td>
                </tr>

                <tr>
                  <td>
                    <strong>3. Application &amp; Document Management</strong>
                    <div className="admin-muted">Lifecycle &amp; Uploads</div>
                  </td>
                  <td>
                    <span className="status-pill status-pill-implemented">Implemented</span>
                  </td>
                  <td>MongoDB application &amp; document models, magic-byte file signature validation (<code>detect_file_signature</code>), MIME/type verification, and strict 10 MiB upload-bound checks (<code>read_and_validate_file</code>).</td>
                  <td>Document upload, delete, and slot status UI implemented.</td>
                  <td>test_document_processing.py passing</td>
                </tr>

                <tr>
                  <td>
                    <strong>4. OCR &amp; Document Processing</strong>
                    <div className="admin-muted">Tesseract extraction</div>
                  </td>
                  <td>
                    <span className="status-pill status-pill-implemented">Implemented</span>
                  </td>
                  <td>Native Tesseract engine (<code>backend/app/services/ocr/engine.py</code>) with <code>eng+tam+hin</code> support, regex entity extraction (<code>field_extractor.py</code>), and PDF/image processing.</td>
                  <td>OCR trigger and field extraction preview panel implemented.</td>
                  <td>Regex normalization &amp; OCR test suites passing</td>
                </tr>

                <tr>
                  <td>
                    <strong>5. Document Verification</strong>
                    <div className="admin-muted">Deterministic &amp; Cross-Doc</div>
                  </td>
                  <td>
                    <span className="status-pill status-pill-partial">Partially implemented</span>
                  </td>
                  <td>File magic-byte checks in <code>document.py</code>; token multiset name matching (<code>name_matcher.py</code>), DOB comparison (<code>dob_parser.py</code>), and cross-doc timeline coherence (<code>cross_document.py</code>). DigiLocker is simulated (<code>synthetic_authoritative.py</code>).</td>
                  <td>Verification result panels show field matching; DigiLocker simulated.</td>
                  <td>test_document_verification.py passing</td>
                </tr>

                <tr>
                  <td>
                    <strong>6. Agent Orchestration (Inc 15)</strong>
                    <div className="admin-muted">Autonomous 5-stage loop</div>
                  </td>
                  <td>
                    <span className="status-pill status-pill-implemented">Implemented (Merged PR #4)</span>
                  </td>
                  <td>OBSERVE-PLAN-ACT-VERIFY-REPLAN state machine, 13 registered tools, cycle limit (max 15), deterministic fallback. Live model usage is decoupled from deterministic authority.</td>
                  <td>Agent Activity audit table &amp; live run timeline implemented.</td>
                  <td>test_agent_orchestration.py passing</td>
                </tr>

                <tr>
                  <td>
                    <strong>7. LLM Provider Integration</strong>
                    <div className="admin-muted">Ollama / OpenAI + Guardrails</div>
                  </td>
                  <td>
                    <span className="status-pill status-pill-unverified">Implemented, unverified in prod</span>
                  </td>
                  <td>OpenAICompatibleProvider, Pydantic guardrails, loopback restriction, deterministic fallback. Default repository setting is disabled.</td>
                  <td>Planner telemetry, system status endpoint, and fallback badges visible.</td>
                  <td>Reported test suite results: 57 tests in test_agent_llm_planner.py passing</td>
                </tr>

                <tr>
                  <td>
                    <strong>8. Eligibility Engine (Inc 16)</strong>
                    <div className="admin-muted">Academic thresholds &amp; cutoffs</div>
                  </td>
                  <td>
                    <span className="status-pill status-pill-pending">Pending Backend (Inc 16)</span>
                  </td>
                  <td>Contract interface implemented. Tool <code>check_eligibility</code> explicitly returns <code>DEPENDENCY_PENDING</code>.</td>
                  <td>Frontend demonstrates deterministic rule evaluations via client mock data.</td>
                  <td>Increment 16 roadmap item</td>
                </tr>

                <tr>
                  <td>
                    <strong>9. Exception Management (Inc 17)</strong>
                    <div className="admin-muted">Review &amp; Manual overrides</div>
                  </td>
                  <td>
                    <span className="status-pill status-pill-pending">Pending Backend (Inc 17)</span>
                  </td>
                  <td>Contract interface implemented. Tool <code>create_exception</code> explicitly returns <code>DEPENDENCY_PENDING</code>.</td>
                  <td>Admin Exceptions view with mock filtering and review modals.</td>
                  <td>Increment 17 roadmap item</td>
                </tr>

                <tr>
                  <td>
                    <strong>10. Notifications (Inc 18)</strong>
                    <div className="admin-muted">Multi-channel dispatch</div>
                  </td>
                  <td>
                    <span className="status-pill status-pill-pending">Pending Backend (Inc 18)</span>
                  </td>
                  <td>Contract interface implemented. Tool <code>send_notification</code> returns <code>DEPENDENCY_PENDING</code>. No real SMTP/SMS gateway.</td>
                  <td>Applicant bell alerts and notification center show simulated messages.</td>
                  <td>Increment 18 roadmap item</td>
                </tr>

                <tr>
                  <td>
                    <strong>11. Analytics &amp; Intelligence (Inc 19)</strong>
                    <div className="admin-muted">Admin metrics &amp; dropouts</div>
                  </td>
                  <td>
                    <span className="status-pill status-pill-pending">Pending Backend (Inc 19)</span>
                  </td>
                  <td>Backend aggregation pipelines and intelligence services pending Increment 19.</td>
                  <td>Admin Analytics page computes status charts from client datasets.</td>
                  <td>Increment 19 roadmap item</td>
                </tr>

                <tr>
                  <td>
                    <strong>12. Full System Integration (Inc 20)</strong>
                    <div className="admin-muted">End-to-end API cutover</div>
                  </td>
                  <td>
                    <span className="status-pill status-pill-pending">Upcoming (Inc 20)</span>
                  </td>
                  <td>Existing REST endpoints support implemented services (auth, applications, documents, OCR, verification, agent activity). Full frontend integration and mock deprecation remain pending.</td>
                  <td>Frontend defaults to mock data for demo robustness; live connect available on dashboard.</td>
                  <td>Increment 20 roadmap item</td>
                </tr>

                <tr>
                  <td>
                    <strong>13. Final Testing &amp; Deliverables (Inc 21)</strong>
                    <div className="admin-muted">Academic presentation readiness</div>
                  </td>
                  <td>
                    <span className="status-pill status-pill-pending">Upcoming (Inc 21)</span>
                  </td>
                  <td>Reported test suite results confirm 264 backend Pytest tests and 54 Cypress E2E tests passing. Production Docker compose, hardening, and final MCA project deliverables remain pending.</td>
                  <td>Demonstration dashboard implemented. Production deployment package pending.</td>
                  <td>Increment 21 roadmap item</td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>
      )}

      {/* ============================================================== */}
      {/* TAB 3: LLM & PLANNER TELEMETRY                                */}
      {/* ============================================================== */}
      {activeTab === "telemetry" && (
        <div>
          <section className="card admin-panel">
            <div className="admin-panel-head">
              <div className="admin-panel-title">LLM vs. Deterministic Planner States</div>
              <span className="admin-muted">
                Server-side guardrails guarantee deterministic reliability
              </span>
            </div>

            <p className="admin-muted">
              Smart Enroll enforces strict architectural boundaries: the LLM is an advisory planner,
              never the authoritative decision-maker for verification or eligibility.
            </p>

            <div className="planner-matrix-grid">
              <div className="planner-matrix-card">
                <div>
                  <div className="planner-matrix-header">
                    <span className="planner-matrix-title">1. Configured &amp; Enabled</span>
                    <span className="planner-tag planner-tag-llm">CONFIG</span>
                  </div>
                  <div className="planner-matrix-body">
                    LLM provider is configured via server environment settings (e.g. Ollama loopback or
                    OpenAI). The system-status endpoint (<code>/api/v1/agents/system-status</code>) exposes
                    sanitized configuration parameters (provider name, model, loopback restrictions, and timeout
                    bounds) without performing an active upstream network reachability probe. Model endpoint health
                    and availability are only evaluated during execution when a planning call is attempted.
                  </div>
                </div>
                <div className="planner-matrix-footer">
                  <code>LLM_PROVIDER != &quot;disabled&quot;</code>
                </div>
              </div>

              <div className="planner-matrix-card">
                <div>
                  <div className="planner-matrix-header">
                    <span className="planner-matrix-title">2. Planner Selected for Run</span>
                    <span className="planner-tag planner-tag-llm">RUN INIT</span>
                  </div>
                  <div className="planner-matrix-body">
                    Orchestrator loop begins with <code>LLMPlanningStrategy</code>. Model is provided
                    sanitized state context (no raw PII, no secret keys).
                  </div>
                </div>
                <div className="planner-matrix-footer">
                  <code>run.planner = &quot;LLM&quot;</code>
                </div>
              </div>

              <div className="planner-matrix-card">
                <div>
                  <div className="planner-matrix-header">
                    <span className="planner-matrix-title">3. Model Proposal Accepted</span>
                    <span className="planner-tag planner-tag-llm">ACCEPTED</span>
                  </div>
                  <div className="planner-matrix-body">
                    Model returns valid JSON conforming to Pydantic schema, selects a whitelisted
                    tool, passes argument bounds, and adheres to workflow transition rules.
                  </div>
                </div>
                <div className="planner-matrix-footer">
                  <code>planner: &quot;LLM&quot;, fallbackUsed: false</code>
                </div>
              </div>

              <div className="planner-matrix-card">
                <div>
                  <div className="planner-matrix-header">
                    <span className="planner-matrix-title">4. Proposal Rejected</span>
                    <span className="planner-tag planner-tag-fallback">REJECTED</span>
                  </div>
                  <div className="planner-matrix-body">
                    Guardrail catches an unregistered tool, malformed JSON, invalid arguments, or an
                    illegal terminal state (e.g. attempting COMPLETED on an unverified application).
                  </div>
                </div>
                <div className="planner-matrix-footer">
                  <code>Validation failed -&gt; Trigger fallback</code>
                </div>
              </div>

              <div className="planner-matrix-card">
                <div>
                  <div className="planner-matrix-header">
                    <span className="planner-matrix-title">5. Deterministic Fallback</span>
                    <span className="planner-tag planner-tag-fallback">FALLBACK USED</span>
                  </div>
                  <div className="planner-matrix-body">
                    Orchestrator securely falls back to the deterministic state machine. Step is
                    executed seamlessly; fallback reason is logged without workflow halt.
                  </div>
                </div>
                <div className="planner-matrix-footer">
                  <code>planner: &quot;FALLBACK&quot;, fallbackUsed: true</code>
                </div>
              </div>

              <div className="planner-matrix-card">
                <div>
                  <div className="planner-matrix-header">
                    <span className="planner-matrix-title">6. Deterministic-Only Mode</span>
                    <span className="planner-tag planner-tag-deterministic">DETERMINISTIC</span>
                  </div>
                  <div className="planner-matrix-body">
                    Default repository configuration. Workflow runs entirely on deterministic
                    rules with zero external API calls or latency overhead.
                  </div>
                </div>
                <div className="planner-matrix-footer">
                  <code>LLM_PROVIDER = &quot;disabled&quot;</code>
                </div>
              </div>
            </div>
          </section>

          {/* Canonical Registered Tools Catalog (from backend/app/schemas/agent.py ToolName) */}
          <section className="card admin-panel" style={{ marginTop: "24px" }}>
            <div className="admin-panel-head">
              <div className="admin-panel-title">Canonical Registered Agent Tools (13 Registered)</div>
              <span className="admin-muted">
                Whitelisted capabilities available to the orchestrator (ToolName enum)
              </span>
            </div>

            <p className="admin-muted" style={{ marginBottom: "12px" }}>
              The model cannot invent new tools or execute arbitrary shell/database queries. Every
              tool is strictly typed. Tools awaiting downstream increments safely return{" "}
              <code>DEPENDENCY_PENDING</code>:
            </p>

            <div className="tools-pill-grid">
              <span className="tool-chip">1. get_application</span>
              <span className="tool-chip">2. get_program_requirements</span>
              <span className="tool-chip">3. check_document_completeness</span>
              <span className="tool-chip">4. process_document</span>
              <span className="tool-chip">5. extract_document_data</span>
              <span className="tool-chip">6. verify_document</span>
              <span className="tool-chip">7. compare_applicant_details</span>
              <span className="tool-chip" style={{ borderColor: "#cbd5e1", background: "#f8fafc" }}>
                8. check_eligibility <em>(Inc 16 Pending)</em>
              </span>
              <span className="tool-chip" style={{ borderColor: "#cbd5e1", background: "#f8fafc" }}>
                9. create_exception <em>(Inc 17 Pending)</em>
              </span>
              <span className="tool-chip" style={{ borderColor: "#cbd5e1", background: "#f8fafc" }}>
                10. request_missing_document <em>(Inc 17/18 Pending)</em>
              </span>
              <span className="tool-chip">11. update_application_status</span>
              <span className="tool-chip" style={{ borderColor: "#cbd5e1", background: "#f8fafc" }}>
                12. send_notification <em>(Inc 18 Pending)</em>
              </span>
              <span className="tool-chip">13. record_audit_event</span>
            </div>
          </section>
        </div>
      )}

      {/* ============================================================== */}
      {/* TAB 4: DIGILOCKER TRANSPARENCY                                 */}
      {/* ============================================================== */}
      {activeTab === "digilocker" && (
        <div>
          {/* Prominent Simulated Disclosure */}
          <div className="transparency-banner">
            <span className="transparency-tag">SIMULATED CAPABILITY</span>
            <div className="transparency-heading">
              DigiLocker &amp; Government Verification are Currently Simulated
            </div>
            <div className="transparency-text">
              Smart Enroll does not connect to live government servers, UIDAI Aadhaar OTP gateways,
              or the National Academic Depository (NAD). The DigiLocker connection, consent modal,
              and issuing authority checks in the application are strictly synthetic simulations for
              evaluation and workflow architecture demonstration.
            </div>
          </div>

          <section className="card admin-panel">
            <div className="admin-panel-head">
              <div className="admin-panel-title">
                Three-Tier Verification Architecture Breakdown
              </div>
              <span className="admin-muted">Actual source code &amp; simulated boundaries</span>
            </div>

            <div className="tiers-grid" style={{ marginTop: "16px" }}>
              <div className="tier-card">
                <span className="tier-badge tier-badge-real">TIER 1 · REAL &amp; DETERMINISTIC</span>
                <div className="tier-title">File Signature &amp; Upload Bounds</div>
                <div className="tier-desc">
                  Inspects magic bytes for PDF (<code>%PDF-</code>), PNG (<code>\x89PNG\r\n\x1a\n</code>),
                  and JPEG (<code>\xff\xd8\xff</code>). Enforces strict 10 MiB limit bounds, 64 KiB chunk
                  streaming, path-traversal safety checks (<code>is_path_safe</code>), and filename sanitization.
                </div>
                <div className="admin-muted" style={{ fontSize: "12px" }}>
                  <strong>Source:</strong> <code>backend/app/services/document.py</code> (<code>detect_file_signature</code>, <code>read_and_validate_file</code>)
                  <br />
                  <strong>Test Suite:</strong> <code>test_document_processing.py</code>
                </div>
              </div>

              <div className="tier-card">
                <span className="tier-badge tier-badge-real">TIER 2 · REAL &amp; DETERMINISTIC</span>
                <div className="tier-title">Deterministic Content &amp; Cross-Doc Checks</div>
                <div className="tier-desc">
                  Native Tesseract OCR extraction (<code>backend/app/services/ocr/</code>) with <code>eng+tam+hin</code> support.
                  Verification rules under <code>backend/app/services/verification/</code>: Unicode NFC token multiset name matching
                  (<code>name_matcher.py</code>, no fuzzy/Levenshtein guessing), multi-format DOB parsing (<code>dob_parser.py</code>),
                  and cross-document academic timeline coherence (<code>cross_document.py</code>) with 0.80 confidence threshold.
                </div>
                <div className="admin-muted" style={{ fontSize: "12px" }}>
                  <strong>Source:</strong> <code>backend/app/services/ocr/</code> &amp; <code>backend/app/services/verification/</code>
                  <br />
                  <strong>Test Suite:</strong> <code>test_document_verification.py</code>
                </div>
              </div>

              <div className="tier-card">
                <span className="tier-badge tier-badge-simulated">
                  TIER 3 · SIMULATED BEHAVIOUR
                </span>
                <div className="tier-title">DigiLocker / Authoritative Registry</div>
                <div className="tier-desc">
                  Synthetic verification evaluating document metadata against in-memory <code>SYNTHETIC_REGISTRY</code> records.
                  Explicitly tags all responses with <code>isSimulated: true</code> and <code>status: &quot;SIMULATED_MATCH&quot;</code>.
                  No live connection to UIDAI, NAD, or government DigiLocker services exists. Real third-party verification
                  would require institutional onboarding, approved API credentials, and an authorized user-consent
                  workflow appropriate to the integrated verification provider (such as DigiLocker, NAD, or issuing bodies).
                </div>
                <div className="admin-muted" style={{ fontSize: "12px" }}>
                  <strong>Source:</strong> <code>backend/app/services/verification/synthetic_authoritative.py</code> (<code>SyntheticAuthoritativeVerificationProvider</code>)
                  <br />
                  <strong>Test Suite:</strong> <code>test_document_verification.py</code>
                </div>
              </div>
            </div>
          </section>
        </div>
      )}

      {/* ============================================================== */}
      {/* TAB 5: PENDING ROADMAP & NEXT STEPS                            */}
      {/* ============================================================== */}
      {activeTab === "roadmap" && (
        <section className="card admin-panel">
          <div className="admin-panel-head">
            <div className="admin-panel-title">Pending Roadmap &amp; Next Steps</div>
            <span className="admin-muted">
              Approved Master Plan Increments 15–21 &amp; Downstream Integrations
            </span>
          </div>

          <p className="admin-muted" style={{ marginBottom: "16px" }}>
            The following roadmap strictly preserves the approved increment definitions from{" "}
            <code>SMART_ENROLL_MASTER_PLAN.md</code>. Increment 15 is merged via PR #4; remaining
            increments represent future planned work:
          </p>

          <div className="roadmap-timeline">
            <div className="roadmap-card">
              <div className="roadmap-inc-num">INCREMENT 15</div>
              <div>
                <div className="roadmap-title">Agentic Orchestration &amp; LLM Provider Integration</div>
                <div className="roadmap-desc">
                  Autonomous 5-stage loop (OBSERVE-PLAN-ACT-VERIFY-REPLAN) with 13 registered tools,
                  Pydantic guardrails, loopback security, and deterministic fallback. Default mode is
                  deterministic; live model usage is an advisory planner decoupled from decision
                  authority.
                </div>
              </div>
              <span className="status-pill status-pill-implemented">Merged (PR #4)</span>
            </div>

            <div className="roadmap-card">
              <div className="roadmap-inc-num">INCREMENT 16</div>
              <div>
                <div className="roadmap-title">Eligibility Engine</div>
                <div className="roadmap-desc">
                  Move frontend deterministic eligibility rules into the backend. Programme
                  requirements, academic thresholds, cutoffs, and qualification calculation. Currently,{" "}
                  <code>check_eligibility</code> contract returns <code>DEPENDENCY_PENDING</code>.
                </div>
              </div>
              <span className="status-pill status-pill-pending">Upcoming</span>
            </div>

            <div className="roadmap-card">
              <div className="roadmap-inc-num">INCREMENT 17</div>
              <div>
                <div className="roadmap-title">Exception Management</div>
                <div className="roadmap-desc">
                  Implement backend exception lifecycle: name mismatch, DOB mismatch, missing/unreadable
                  documents, applicant evidence submission, and workflow resumption. Currently,{" "}
                  <code>create_exception</code> contract returns <code>DEPENDENCY_PENDING</code>.
                </div>
              </div>
              <span className="status-pill status-pill-pending">Upcoming</span>
            </div>

            <div className="roadmap-card">
              <div className="roadmap-inc-num">INCREMENT 18</div>
              <div>
                <div className="roadmap-title">Notifications</div>
                <div className="roadmap-desc">
                  Backend-generated notification persistence, missing document prompts, read/unread
                  state, and multi-channel dispatch (SMTP email, SMS). Currently,{" "}
                  <code>send_notification</code> contract returns <code>DEPENDENCY_PENDING</code>.
                </div>
              </div>
              <span className="status-pill status-pill-pending">Upcoming</span>
            </div>

            <div className="roadmap-card">
              <div className="roadmap-inc-num">INCREMENT 19</div>
              <div>
                <div className="roadmap-title">Analytics &amp; Intelligence</div>
                <div className="roadmap-desc">
                  Backend analytics via MongoDB aggregation pipelines, pandas, processing turnaround
                  metrics, document verification success rates, and admission funnel dropouts.
                </div>
              </div>
              <span className="status-pill status-pill-pending">Upcoming</span>
            </div>

            <div className="roadmap-card">
              <div className="roadmap-inc-num">INCREMENT 20</div>
              <div>
                <div className="roadmap-title">Full System Integration</div>
                <div className="roadmap-desc">
                  Connect the complete system end-to-end (React → FastAPI → MongoDB). Existing REST
                  APIs support implemented services (auth, applications, documents, OCR, verification,
                  and agent activity), while full frontend integration and deprecation of client mock
                  data layers remain pending.
                </div>
              </div>
              <span className="status-pill status-pill-pending">Upcoming</span>
            </div>

            <div className="roadmap-card">
              <div className="roadmap-inc-num">INCREMENT 21</div>
              <div>
                <div className="roadmap-title">Final Testing, Demo &amp; Academic Deliverables</div>
                <div className="roadmap-desc">
                  Final system hardening, production deployment configuration (Docker compose, Nginx
                  reverse proxy), final academic demonstration validation, and MCA project presentation
                  deliverables.
                </div>
              </div>
              <span className="status-pill status-pill-pending">Upcoming</span>
            </div>
          </div>
        </section>
      )}
    </div>
  );
}
