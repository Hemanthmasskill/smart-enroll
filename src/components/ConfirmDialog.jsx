import Modal from "./Modal";

export default function ConfirmDialog({ title, message, confirmLabel = "Confirm", onConfirm, onCancel }) {
  return (
    <Modal
      title={title}
      onClose={onCancel}
      footer={
        <>
          <button className="btn btn-secondary" onClick={onCancel}>
            Cancel
          </button>
          <button className="btn btn-danger-ghost" onClick={onConfirm}>
            {confirmLabel}
          </button>
        </>
      }
    >
      <p style={{ fontSize: "14px", color: "var(--color-text-secondary)" }}>{message}</p>
    </Modal>
  );
}
