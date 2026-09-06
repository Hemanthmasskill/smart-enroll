import "./StatCard.css";

export default function StatCard({ label, value, hint }) {
  return (
    <div className="stat-card card">
      <span className="stat-card-label">{label}</span>
      <span className="stat-card-value">{value}</span>
      {hint && <span className="stat-card-hint">{hint}</span>}
    </div>
  );
}
