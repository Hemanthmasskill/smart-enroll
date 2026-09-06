import { getStatusLabel, getStatusTone } from "../utils/statusUtils";
import "./StatusBadge.css";

/**
 * Renders a consistent status pill anywhere in the app.
 * Pass a known status code (e.g. "VERIFIED", "WAITING_FOR_DOCUMENTS")
 * and it resolves both the label and the color automatically.
 * Alternatively pass `label` + `tone` directly for one-off cases.
 */
export default function StatusBadge({ code, label, tone }) {
  const resolvedLabel = label ?? getStatusLabel(code);
  const resolvedTone = tone ?? getStatusTone(code);

  return <span className={`status-badge tone-${resolvedTone}`}>{resolvedLabel}</span>;
}
