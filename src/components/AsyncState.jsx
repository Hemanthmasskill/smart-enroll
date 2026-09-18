import "./AsyncState.css";

export function LoadingState({ message = "Loading…" }) {
  return (
    <div className="card async-state" role="status" aria-live="polite">
      <span className="async-spinner" aria-hidden="true" />
      <p>{message}</p>
    </div>
  );
}

export function EmptyState({ title = "Nothing to show", message }) {
  return (
    <div className="card async-state async-state-empty">
      <strong>{title}</strong>
      {message && <p>{message}</p>}
    </div>
  );
}

export function ErrorState({ title = "Unable to load this section", message, onRetry }) {
  return (
    <div className="card async-state async-state-error" role="alert">
      <strong>{title}</strong>
      {message && <p>{message}</p>}
      {onRetry && (
        <button className="btn btn-secondary btn-sm" onClick={onRetry}>
          Try Again
        </button>
      )}
    </div>
  );
}
