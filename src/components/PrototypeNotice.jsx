import "./PrototypeNotice.css";

export default function PrototypeNotice({ children }) {
  return (
    <aside className="prototype-notice" aria-label="Prototype implementation notice">
      <strong>Prototype boundary</strong>
      <span>
        {children ??
          "This frontend currently uses centralized mock services and simulated processing. Live FastAPI, MongoDB, OCR and authorized verification integrations will replace these mocks in the backend phase."}
      </span>
    </aside>
  );
}
