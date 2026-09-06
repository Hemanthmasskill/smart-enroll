import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../../context/AuthContext";
import { getApplication, getRecentActivity, getPrograms } from "../../services/api";
import PageHeader from "../../components/PageHeader";
import StatCard from "../../components/StatCard";
import StatusBadge from "../../components/StatusBadge";
import "./Dashboard.css";

export default function Dashboard() {
  const { session } = useAuth();
  const navigate = useNavigate();

  const [application, setApplication] = useState(null);
  const [activity, setActivity] = useState([]);
  const [programme, setProgramme] = useState(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    let isMounted = true;

    async function load() {
      const [app, recentActivity, programs] = await Promise.all([
        getApplication(session?.applicantId),
        getRecentActivity(),
        getPrograms(),
      ]);
      if (!isMounted) return;
      setApplication(app);
      setActivity(recentActivity);
      setProgramme(programs.find((p) => p.id === app?.programmeId) ?? null);
      setIsLoading(false);
    }

    load();
    return () => {
      isMounted = false;
    };
  }, [session]);

  const firstName = session?.name?.split(" ")[0] ?? "Applicant";

  if (isLoading) {
    return <p>Loading your dashboard...</p>;
  }

  return (
    <div>
      <PageHeader
        title={`Welcome, ${firstName}`}
        subtitle="Track and manage your admission application."
      />

      <div className="progress-card card">
        <div className="progress-card-top">
          <div>
            <span className="progress-card-label">Current Stage</span>
            <StatusBadge code={application?.status} />
          </div>
          <span className="progress-card-percent">{application?.progressPercent}% Complete</span>
        </div>
        <div className="progress-track">
          <div
            className="progress-fill"
            style={{ width: `${application?.progressPercent ?? 0}%` }}
          />
        </div>
      </div>

      <div className="stat-grid">
        <StatCard label="Application Status" value="Under Processing" hint={programme?.name} />
        <StatCard
          label="Documents"
          value={`${application?.documentsSubmitted} of ${application?.documentsRequired} Submitted`}
        />
        <StatCard label="Eligibility" value="Pending" />
        <StatCard
          label="Notifications"
          value={`${application?.unreadNotifications} New`}
        />
      </div>

      <div className="dashboard-columns">
        <div className="card next-action-card">
          <span className="next-action-label">Next Action</span>
          <p className="next-action-text">{application?.nextAction}</p>
          <div className="next-action-buttons">
            <button className="btn btn-accent" onClick={() => navigate("/documents")}>
              Upload Documents
            </button>
            <button className="btn btn-secondary" onClick={() => navigate("/application")}>
              Continue Application
            </button>
          </div>
        </div>

        <div className="card activity-card">
          <span className="activity-card-heading">Recent Activity</span>
          <ul className="activity-list">
            {activity.map((item) => (
              <li key={item.id}>
                <span className="activity-dot" />
                <div>
                  <p className="activity-label">{item.label}</p>
                  <span className="activity-timestamp">{item.timestamp}</span>
                </div>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  );
}
