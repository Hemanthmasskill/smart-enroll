/**
 * Temporary placeholder used only for routes not yet implemented in
 * the current increment. Each one is replaced with a real page as
 * that module is built — see the project's increment plan.
 */
export default function ComingSoon({ title }) {
  return (
    <div style={{ padding: "48px" }}>
      <p style={{ fontSize: "13px", fontWeight: 600, color: "var(--color-primary-dark)", marginBottom: "8px" }}>
        Coming in a later increment
      </p>
      <h1 style={{ fontSize: "22px" }}>{title}</h1>
    </div>
  );
}
