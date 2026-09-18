import { useEffect, useState } from "react";
import PageHeader from "../../components/PageHeader";
import StatCard from "../../components/StatCard";
import { getAdminAnalytics } from "../../services/api";
import { getStatusLabel } from "../../utils/statusUtils";
import "./Admin.css";

function BarList({ rows, labelFormatter }) {
  const max = Math.max(1, ...rows.map((r) => r.count));
  return (
    <div className="bar-list">
      {rows.map((row) => (
        <div key={row.value}>
          <div className="bar-row-top">
            <span className="bar-row-label">{labelFormatter ? labelFormatter(row.value) : row.value}</span>
            <span className="bar-row-count">{row.count}</span>
          </div>
          <div className="bar-track" role="progressbar" aria-label={`${labelFormatter ? labelFormatter(row.value) : row.value}: ${row.count}`} aria-valuemin="0" aria-valuemax={max} aria-valuenow={row.count}>
            <div className="bar-fill" style={{ width: `${(row.count / max) * 100}%` }} />
          </div>
        </div>
      ))}
      {!rows.length && <p className="admin-muted">No data available.</p>}
    </div>
  );
}

export default function Analytics() {
  const [data, setData] = useState(null);

  useEffect(() => {
    getAdminAnalytics().then(setData);
  }, []);

  if (!data) return <p>Loading analytics...</p>;

  return (
    <div>
      <PageHeader
        title="Admission Analytics"
        subtitle="Prototype analytics computed from the current demo dataset."
      />

      <div className="admin-stat-grid">
        <StatCard label="Total Applications" value={data.total} />
        <StatCard label="Processing Complete Rate" value={`${data.completionRate}%`} />
        <StatCard label="Total Exceptions" value={data.totalExceptions} />
        <StatCard label="Open Exceptions" value={data.openExceptions} />
      </div>

      <div className="analytics-grid">
        <section className="card admin-panel">
          <div className="admin-panel-head">
            <span className="admin-panel-title">Applications by Workflow Status</span>
          </div>
          <BarList rows={data.statusDistribution} labelFormatter={getStatusLabel} />
        </section>

        <section className="card admin-panel">
          <div className="admin-panel-head">
            <span className="admin-panel-title">Eligibility Distribution</span>
          </div>
          <BarList rows={data.eligibilityDistribution} labelFormatter={getStatusLabel} />
        </section>

        <section className="card admin-panel">
          <div className="admin-panel-head">
            <span className="admin-panel-title">Document Verification Distribution</span>
          </div>
          <BarList rows={data.documentCompletionDistribution} />
        </section>

        <section className="card admin-panel">
          <div className="admin-panel-head">
            <span className="admin-panel-title">Programme-wise Applications</span>
          </div>
          <BarList rows={data.programmeDistribution} />
        </section>

        <section className="card admin-panel">
          <div className="admin-panel-head">
            <span className="admin-panel-title">Exception Severity</span>
          </div>
          <BarList rows={data.exceptionSeverityDistribution} />
        </section>

        <section className="card admin-panel">
          <div className="admin-panel-head">
            <span className="admin-panel-title">Exception Status</span>
          </div>
          <BarList rows={data.exceptionStatusDistribution} />
        </section>
      </div>

      <p className="admin-muted" style={{ marginTop: "var(--space-4)" }}>
        These figures are computed from prototype/demo data for illustration only and will be
        replaced by live processing metrics once the backend is connected.
      </p>
    </div>
  );
}
