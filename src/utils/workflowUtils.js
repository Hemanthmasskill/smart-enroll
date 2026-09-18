/**
 * Pure derivation helpers for Increment 7.
 *
 * The workflow is intentionally based on observable application/document state.
 * It does not expose model chain-of-thought. It only reports the processing
 * stage, visible system action and deterministic result available to the UI.
 */

export const WORKFLOW_STATE_META = {
  COMPLETED: { label: "Completed", tone: "success" },
  ACTIVE: { label: "In Progress", tone: "info" },
  ACTION_REQUIRED: { label: "Action Required", tone: "warning" },
  WAITING: { label: "Waiting", tone: "neutral" },
  FLAGGED: { label: "Flagged", tone: "danger" },
};

export function countRequiredDocuments(documents = []) {
  const required = documents.filter((doc) => doc.required !== false);
  const submitted = required.filter((doc) => doc.status !== "NOT_UPLOADED");
  return {
    required: required.length,
    submitted: submitted.length,
    missing: required.length - submitted.length,
  };
}

export function deriveEligibility(application, documents = [], rules) {
  if (!application || !rules) return null;

  const degreeDoc = documents.find((doc) => doc.id === "doc-degree");
  const ugDoc = documents.find((doc) => doc.id === "doc-ug-marksheet");
  const counts = countRequiredDocuments(documents);
  const allDocumentsSubmitted = counts.required > 0 && counts.missing === 0;

  const bachelorDegree = {
    label: "Bachelor's Degree",
    configured: rules.minimumQualification,
    result:
      ugDoc?.status !== "NOT_UPLOADED" && degreeDoc?.status !== "NOT_UPLOADED"
        ? "PASSED"
        : "PENDING",
  };

  const minimumPercentage = {
    label: "Minimum Percentage",
    configured: rules.minimumPercentage,
    result: degreeDoc?.details?.extraction?.CGPA ? "PASSED" : "PENDING",
  };

  const mathematicsRequirement = {
    label: "Mathematics Requirement",
    configured: rules.mathematicsRequirement,
    result: "PENDING",
  };

  const requiredDocuments = {
    label: "Required Documents",
    configured: rules.requiredDocuments,
    result: allDocumentsSubmitted ? "PASSED" : "PENDING",
  };

  const entranceRequirement = {
    label: "Entrance Requirement",
    configured: rules.entranceRequirement,
    result: "NOT_APPLICABLE",
  };

  const evaluation = [
    bachelorDegree,
    minimumPercentage,
    mathematicsRequirement,
    requiredDocuments,
    entranceRequirement,
  ];

  const hasFailed = evaluation.some((item) => item.result === "FAILED");
  const allDecided = evaluation.every(
    (item) => item.result === "PASSED" || item.result === "NOT_APPLICABLE"
  );

  return {
    programmeId: application.programmeId,
    rules,
    evaluation,
    overall: hasFailed ? "INELIGIBLE" : allDecided ? "ELIGIBLE" : "ELIGIBILITY_CHECK",
  };
}

function hasStructuredExtraction(doc) {
  return Boolean(doc?.details?.extraction && Object.keys(doc.details.extraction).length);
}

function hasContentValidation(doc) {
  return Boolean(doc?.details?.validation && Object.keys(doc.details.validation).length);
}

export function deriveWorkflow({ application, documents = [], eligibility, notifications = [] }) {
  if (!application) return null;

  const requiredDocuments = documents.filter((doc) => doc.required !== false);
  const submittedDocuments = requiredDocuments.filter((doc) => doc.status !== "NOT_UPLOADED");
  const missingDocuments = requiredDocuments.filter((doc) => doc.status === "NOT_UPLOADED");
  const hasDocumentFailure = requiredDocuments.some((doc) =>
    ["MISMATCH", "REJECTED"].includes(doc.status)
  );

  const extractionComplete =
    submittedDocuments.length > 0 && submittedDocuments.every(hasStructuredExtraction);
  const extractionStarted = submittedDocuments.some(hasStructuredExtraction);

  const validationComplete =
    submittedDocuments.length > 0 && submittedDocuments.every(hasContentValidation);
  const validationStarted = submittedDocuments.some(hasContentValidation);

  const authoritativePending = submittedDocuments.some(
    (doc) => doc.details?.authoritative?.status === "PENDING"
  );
  const authoritativeVerified = submittedDocuments.some(
    (doc) => doc.details?.authoritative?.status === "VERIFIED"
  );

  const notificationCount = notifications.length;
  const unreadCount = notifications.filter((notification) => !notification.read).length;

  let eligibilityState = "WAITING";
  let eligibilityDetail = "Waiting for document requirements and verification to be ready.";
  if (missingDocuments.length === 0 && eligibility) {
    if (eligibility.overall === "ELIGIBLE") {
      eligibilityState = "COMPLETED";
      eligibilityDetail = "All configured programme rules are satisfied.";
    } else if (eligibility.overall === "INELIGIBLE") {
      eligibilityState = "FLAGGED";
      eligibilityDetail = "One or more configured programme rules were not satisfied.";
    } else {
      eligibilityState = "ACTIVE";
      eligibilityDetail = "Deterministic programme rules are being evaluated against verified data.";
    }
  }

  let decisionState = "WAITING";
  let decisionDetail = "No final admission outcome is produced while prerequisite checks remain pending.";
  if (hasDocumentFailure || eligibility?.overall === "INELIGIBLE") {
    decisionState = "FLAGGED";
    decisionDetail = "The case requires exception handling based on observable validation results.";
  } else if (eligibility?.overall === "ELIGIBLE") {
    decisionState = "COMPLETED";
    decisionDetail = "Eligibility outcome is ready for the next configured admission-processing action.";
  }

  return {
    applicationId: application.applicationId,
    generatedFrom: "current centralized frontend demo state",
    model: ["OBSERVE", "PLAN", "ACT", "VERIFY", "RE-PLAN"],
    stages: [
      {
        id: "application-submitted",
        label: "Application Submitted",
        state: application.submittedAt ? "COMPLETED" : "ACTIVE",
        detail: application.submittedAt
          ? `Application ${application.applicationId} was received on ${application.submittedAt}.`
          : "Waiting for the applicant to submit the application.",
        observableAction: "Read application record",
      },
      {
        id: "document-check",
        label: "Document Check",
        state: hasDocumentFailure
          ? "FLAGGED"
          : missingDocuments.length > 0
            ? "ACTION_REQUIRED"
            : "COMPLETED",
        detail: hasDocumentFailure
          ? "A submitted document has a mismatch or rejection result."
          : missingDocuments.length > 0
            ? `${missingDocuments.length} required document${missingDocuments.length === 1 ? " is" : "s are"} still missing.`
            : "All required documents are present.",
        observableAction: "Check required-document completeness",
      },
      {
        id: "ocr-extraction",
        label: "OCR Extraction",
        state: extractionComplete ? "COMPLETED" : extractionStarted ? "ACTIVE" : "WAITING",
        detail: extractionComplete
          ? "Structured fields are available for all currently submitted documents."
          : extractionStarted
            ? "OCR extraction is still pending for one or more submitted documents."
            : "Waiting for submitted documents before OCR can run.",
        observableAction: "Extract document text and structured fields",
      },
      {
        id: "content-validation",
        label: "Content Validation",
        state: hasDocumentFailure
          ? "FLAGGED"
          : validationComplete
            ? "COMPLETED"
            : validationStarted
              ? "ACTIVE"
              : "WAITING",
        detail: hasDocumentFailure
          ? "A cross-document or structural validation issue is present."
          : validationComplete
            ? "Extracted fields have completed structural/cross-document checks for submitted documents."
            : validationStarted
              ? "Content validation is still running for one or more submitted documents."
              : "Waiting for OCR output before content validation can run.",
        observableAction: "Validate extracted fields and cross-document consistency",
      },
      {
        id: "authoritative-verification",
        label: "Authoritative Verification",
        state: hasDocumentFailure
          ? "FLAGGED"
          : authoritativePending
            ? "ACTIVE"
            : authoritativeVerified
              ? "COMPLETED"
              : "WAITING",
        detail: authoritativePending
          ? "At least one supported record is awaiting issuer/DigiLocker/NAD confirmation."
          : authoritativeVerified
            ? "At least one supported record has authoritative confirmation in the simulation."
            : "No authoritative result is currently available for the submitted records.",
        observableAction: "Check supported authoritative credential sources",
      },
      {
        id: "eligibility-evaluation",
        label: "Eligibility Evaluation",
        state: eligibilityState,
        detail: eligibilityDetail,
        observableAction: "Apply configured deterministic programme rules",
      },
      {
        id: "decision-exception",
        label: "Decision / Exception",
        state: decisionState,
        detail: decisionDetail,
        observableAction: "Route the case according to configured workflow outcome",
      },
      {
        id: "notification",
        label: "Notification",
        state: notificationCount > 0 ? "COMPLETED" : "WAITING",
        detail:
          notificationCount > 0
            ? `${notificationCount} notification${notificationCount === 1 ? " has" : "s have"} been generated; ${unreadCount} unread.`
            : "No notification has been generated yet.",
        observableAction: "Publish applicant-facing status updates",
      },
    ],
  };
}
