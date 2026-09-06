/**
 * Central place for turning system status codes into user-friendly
 * labels and consistent badge colors. Keeping this in one file avoids
 * every page inventing its own wording for the same status.
 */

export const APPLICATION_STATES = {
  DRAFT: "Draft",
  SUBMITTED: "Submitted",
  PROCESSING: "Processing",
  WAITING_FOR_DOCUMENTS: "Waiting for Documents",
  VERIFICATION_IN_PROGRESS: "Verification In Progress",
  EXCEPTION: "Exception",
  ELIGIBILITY_CHECK: "Eligibility Check",
  ELIGIBLE: "Eligible",
  INELIGIBLE: "Not Eligible",
  PROCESSING_COMPLETE: "Processing Complete",
};

export const DOCUMENT_STATES = {
  NOT_UPLOADED: "Not Uploaded",
  UPLOADED: "Uploaded",
  PROCESSING: "Processing",
  VALIDATED: "Validated",
  VERIFIED: "Verified",
  MISMATCH: "Mismatch",
  REJECTED: "Rejected",
  UNVERIFIED: "Unverified",
};

// Semantic tone drives the StatusBadge color — not the raw status string.
const TONE_MAP = {
  // application states
  DRAFT: "neutral",
  SUBMITTED: "info",
  PROCESSING: "info",
  WAITING_FOR_DOCUMENTS: "warning",
  VERIFICATION_IN_PROGRESS: "info",
  EXCEPTION: "danger",
  ELIGIBILITY_CHECK: "info",
  ELIGIBLE: "success",
  INELIGIBLE: "danger",
  PROCESSING_COMPLETE: "success",
  // document states
  NOT_UPLOADED: "neutral",
  UPLOADED: "info",
  VALIDATED: "info",
  VERIFIED: "success",
  MISMATCH: "danger",
  REJECTED: "danger",
  UNVERIFIED: "warning",
};

export function getStatusLabel(code) {
  return APPLICATION_STATES[code] ?? DOCUMENT_STATES[code] ?? code;
}

export function getStatusTone(code) {
  return TONE_MAP[code] ?? "neutral";
}
