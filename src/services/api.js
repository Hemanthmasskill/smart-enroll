/**
 * Smart Enroll API service layer.
 *
 * Every function here is a placeholder that currently resolves with
 * mock data (see src/data/mockData.js). Each one is written so that,
 * later, only the function body needs to change to call the real
 * FastAPI backend — nothing in the components needs to change.
 *
 * Future base URL:
 *   const BASE_URL = "http://localhost:8000/api/v1";
 */

import {
  mockApplicants,
  mockApplications,
  mockRecentActivity,
  mockPrograms,
  mockDocuments,
  mockDigiLockerRecords,
  mockEligibilityRules,
  mockNotifications,
  mockAdminApplications,
  mockExceptions,
  mockAgentActivity,
} from "../data/mockData";
import { countRequiredDocuments, deriveEligibility, deriveWorkflow } from "../utils/workflowUtils";

const BASE_URL = "http://localhost:8000/api/v1";

// Simulates network latency for a more realistic demo.
const delay = (ms = 500) => new Promise((resolve) => setTimeout(resolve, ms));

function getSynchronousEligibility(applicantId) {
  const application = mockApplications[applicantId];
  const documents = mockDocuments[applicantId] ?? [];
  const rules = application ? mockEligibilityRules[application.programmeId] : null;
  return deriveEligibility(application, documents, rules);
}

function syncPrimaryAdminApplication(applicantId) {
  const application = mockApplications[applicantId];
  if (!application) return;
  const adminRow = mockAdminApplications.find((row) => row.applicantId === applicantId);
  if (!adminRow) return;
  adminRow.status = application.status;
  adminRow.documentStatus = `${application.documentsSubmitted} of ${application.documentsRequired} Submitted`;
  adminRow.eligibilityStatus = application.eligibilityStatus;
  adminRow.currentAction = application.currentAction;
}

function syncApplicationState(applicantId) {
  const application = mockApplications[applicantId];
  if (!application) return null;

  const documents = mockDocuments[applicantId] ?? [];
  const notifications = mockNotifications[applicantId] ?? [];
  const counts = countRequiredDocuments(documents);
  const eligibility = getSynchronousEligibility(applicantId);
  const hasDocumentFailure = documents.some((doc) => ["MISMATCH", "REJECTED"].includes(doc.status));
  const hasVerificationPending = documents.some((doc) =>
    ["UPLOADED", "PROCESSING"].includes(doc.status) || doc.details?.authoritative?.status === "PENDING"
  );

  application.documentsSubmitted = counts.submitted;
  application.documentsRequired = counts.required;
  application.unreadNotifications = notifications.filter((item) => !item.read).length;

  const missingException = mockExceptions.find(
    (item) => item.applicationId === application.applicationId && item.type === "MISSING_DOCUMENT"
  );
  if (missingException) {
    const missingNames = documents
      .filter((doc) => doc.required !== false && doc.status === "NOT_UPLOADED")
      .map((doc) => doc.name);
    if (missingNames.length === 0) {
      missingException.status = "RESOLVED";
      missingException.description = "All previously missing required documents have now been submitted.";
    } else {
      missingException.status = "OPEN";
      missingException.description = `${missingNames.join(" and ")} ${missingNames.length === 1 ? "has" : "have"} not been submitted.`;
    }
  }

  application.eligibilityStatus =
    eligibility?.overall === "ELIGIBLE"
      ? "ELIGIBLE"
      : eligibility?.overall === "INELIGIBLE"
        ? "INELIGIBLE"
        : "PENDING";

  if (hasDocumentFailure) {
    application.status = "EXCEPTION";
    application.progressPercent = Math.max(application.progressPercent ?? 0, 65);
    application.nextAction = "Review the document issue shown in your application status.";
    application.currentAction = "Smart Enroll has paused automated processing because a document validation exception was detected.";
  } else if (counts.missing > 0) {
    application.status = "WAITING_FOR_DOCUMENTS";
    application.progressPercent = Math.min(65, 25 + counts.submitted * 5);
    application.nextAction = `${counts.missing} document${counts.missing === 1 ? " is" : "s are"} still required.`;
    application.currentAction =
      "Smart Enroll is verifying your submitted documents and waiting for the remaining required files.";
  } else if (hasVerificationPending) {
    application.status = "VERIFICATION_IN_PROGRESS";
    application.progressPercent = 72;
    application.nextAction = "No additional document upload is required right now.";
    application.currentAction = "Smart Enroll is completing OCR, content validation and supported authoritative verification checks.";
  } else if (eligibility?.overall === "ELIGIBLE") {
    application.status = "PROCESSING_COMPLETE";
    application.progressPercent = 100;
    application.nextAction = "No applicant action is currently required.";
    application.currentAction = "Configured eligibility checks are complete and the autonomous processing workflow has reached its current endpoint.";
  } else if (eligibility?.overall === "INELIGIBLE") {
    application.status = "INELIGIBLE";
    application.progressPercent = 92;
    application.nextAction = "Review the eligibility result and configured programme criteria.";
    application.currentAction = "Eligibility evaluation completed against configured programme rules.";
  } else {
    application.status = "ELIGIBILITY_CHECK";
    application.progressPercent = 84;
    application.nextAction = "No applicant action is currently required.";
    application.currentAction = "Smart Enroll is evaluating the application against configured deterministic programme rules.";
  }

  syncPrimaryAdminApplication(applicantId);
  return application;
}

/* ----------------------------- Auth ----------------------------- */
// Future: POST `${BASE_URL}/auth/login`
export async function loginRequest({ email, password, role }) {
  await delay(600);

  if (!email || !password) {
    throw new Error("Email and password are required.");
  }

  const applicant = mockApplicants.find(
    (a) => a.email.toLowerCase() === email.toLowerCase()
  );

  return {
    role,
    name: role === "admin" ? "Admin User" : applicant?.fullName ?? "Hemanth M.P.",
    email,
    applicantId: role === "user" ? applicant?.id ?? "APL-1001" : null,
    token: "mock-jwt-token",
  };
}

// Future: POST `${BASE_URL}/auth/register`
export async function registerRequest({ fullName, email }) {
  await delay(700);

  return {
    role: "user",
    name: fullName,
    email,
    applicantId: "APL-1001",
    token: "mock-jwt-token",
  };
}

/* --------------------------- Application --------------------------- */
// Future: GET `${BASE_URL}/applications/{id}`
export async function getApplication(applicantId) {
  await delay(400);
  return syncApplicationState(applicantId);
}

// Future: POST `${BASE_URL}/applications`
export async function createApplication(applicantId, formData) {
  await delay(700);
  return {
    ...mockApplications[applicantId],
    ...formData,
    status: "SUBMITTED",
    progressPercent: 20,
  };
}

// Future: PUT `${BASE_URL}/applications/{id}`
export async function updateApplication(applicantId, partialData) {
  await delay(500);
  return { ...mockApplications[applicantId], ...partialData };
}

export async function getRecentActivity() {
  await delay(300);
  return mockRecentActivity;
}

export async function getPrograms() {
  await delay(200);
  return mockPrograms;
}

/* ----------------------------- Profile ------------------------------ */
// Future: GET `${BASE_URL}/applicants/{id}`
export async function getApplicantProfile(applicantId) {
  await delay(300);
  return mockApplicants.find((a) => a.id === applicantId) ?? null;
}

// Future: PATCH `${BASE_URL}/applicants/{id}`
export async function updateApplicantProfile(applicantId, updates) {
  await delay(500);
  const applicant = mockApplicants.find((a) => a.id === applicantId);
  if (applicant) Object.assign(applicant, updates);
  return applicant;
}

/* ---------------------------- Documents ------------------------------ */
// Future: GET `${BASE_URL}/documents?applicationId={id}`
export async function getDocuments(applicantId) {
  await delay(400);
  return mockDocuments[applicantId] ?? [];
}

// Future: POST `${BASE_URL}/documents/upload`
// Accepts the applicantId, the document id being filled, and the browser
// File object. Returns the updated document record. The file itself is
// never sent anywhere in this mock — only its name is read.
export async function uploadDocument(applicantId, documentId, file) {
  await delay(900);
  const documents = mockDocuments[applicantId] ?? [];
  const doc = documents.find((d) => d.id === documentId);
  if (!doc) throw new Error("Document not found.");

  doc.status = "UPLOADED";
  doc.fileName = file?.name ?? "uploaded_file.pdf";
  doc.uploadedAt = new Date().toLocaleDateString("en-IN", {
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
  doc.details = null;
  syncApplicationState(applicantId);

  return { ...doc };
}

// Future: DELETE `${BASE_URL}/documents/{id}`
export async function removeDocument(applicantId, documentId) {
  await delay(400);
  const documents = mockDocuments[applicantId] ?? [];
  const doc = documents.find((d) => d.id === documentId);
  if (doc) {
    doc.status = "NOT_UPLOADED";
    doc.fileName = null;
    doc.uploadedAt = null;
    doc.details = null;
  }
  syncApplicationState(applicantId);
  return { ...doc };
}

// Future: GET `${BASE_URL}/documents/{id}/verification`
export async function getVerificationStatus(applicantId, documentId) {
  await delay(300);
  const documents = mockDocuments[applicantId] ?? [];
  return documents.find((d) => d.id === documentId) ?? null;
}

/* --------------------------- DigiLocker ------------------------------- */
// Future: POST `${BASE_URL}/digilocker/connect`
// Frontend simulation only — no live DigiLocker/NAD integration exists.
export async function connectDigiLocker(applicantId) {
  await delay(1400);
  return {
    connected: true,
    applicantName: mockApplicants.find((a) => a.id === applicantId)?.fullName ?? "Applicant",
    records: mockDigiLockerRecords[applicantId] ?? [],
  };
}

// Future: POST `${BASE_URL}/digilocker/records/{recordId}/use`
// Simulates linking an authoritative record to the matching uploaded document.
export async function useVerifiedDigiLockerRecord(applicantId, recordId) {
  await delay(650);
  const record = (mockDigiLockerRecords[applicantId] ?? []).find((item) => item.id === recordId);
  if (!record) throw new Error("Verified record not found.");

  const documents = mockDocuments[applicantId] ?? [];
  const target = record.id === "dl-degree" ? documents.find((doc) => doc.id === "doc-degree") : null;
  if (!target) throw new Error("No matching uploaded document was found for this record.");

  target.status = "VERIFIED";
  target.details = target.details ?? { extraction: {}, validation: {} };
  target.details.authoritative = {
    status: "VERIFIED",
    source: "DigiLocker/NAD simulation",
    recordId: record.id,
    issuer: record.issuer,
  };
  syncApplicationState(applicantId);
  return { document: { ...target }, application: { ...mockApplications[applicantId] } };
}

/* --------------------------- Eligibility ------------------------------ */
// Future: GET `${BASE_URL}/eligibility/{application_id}`
//
// Eligibility criteria are configured, deterministic programme rules
// (master prompt section 15) — this function only checks the
// applicant's existing document/application state against those
// fixed rules. It never invents or adjusts a rule; that is exactly
// what a real backend rule engine would do, just computed here so
// the demo can't drift out of sync with the Documents page.
export async function getEligibility(applicantId) {
  await delay(500);
  return getSynchronousEligibility(applicantId);
}

/* ----------------------------- Integrated Workflow ----------------------------- */
// Future: GET `${BASE_URL}/applications/{id}/workflow`
// Returns only observable workflow state/actions/results. No private reasoning.
export async function getApplicationWorkflow(applicantId) {
  await delay(350);
  const application = syncApplicationState(applicantId);
  if (!application) return null;
  return deriveWorkflow({
    application,
    documents: mockDocuments[applicantId] ?? [],
    eligibility: getSynchronousEligibility(applicantId),
    notifications: mockNotifications[applicantId] ?? [],
  });
}

/* ----------------------------- Application Status ----------------------------- */
const STATUS_STAGE_INDEX = {
  DRAFT: 0,
  SUBMITTED: 1,
  PROCESSING: 2,
  WAITING_FOR_DOCUMENTS: 2,
  VERIFICATION_IN_PROGRESS: 3,
  EXCEPTION: 3,
  ELIGIBILITY_CHECK: 4,
  ELIGIBLE: 4,
  INELIGIBLE: 4,
  PROCESSING_COMPLETE: 5,
};

const STATUS_STAGES = [
  "Application Created",
  "Application Submitted",
  "Documents Received",
  "Document Verification",
  "Eligibility Evaluation",
  "Admission Processing Complete",
];

// Future: GET `${BASE_URL}/applications/{id}/timeline`
export async function getApplicationTimeline(applicantId) {
  await delay(400);
  const application = syncApplicationState(applicantId);
  if (!application) return null;

  const currentIndex = STATUS_STAGE_INDEX[application.status] ?? 0;

  const stages = STATUS_STAGES.map((label, index) => ({
    label,
    state: index < currentIndex ? "COMPLETED" : index === currentIndex ? "CURRENT" : "PENDING",
  }));

  return {
    applicationId: application.applicationId,
    programmeId: application.programmeId,
    status: application.status,
    stages,
    currentAction: application.currentAction,
    applicantAction: application.nextAction,
  };
}

/* ----------------------------- Notifications ----------------------------- */
// Future: GET `${BASE_URL}/notifications`
export async function getNotifications(applicantId) {
  await delay(400);
  return mockNotifications[applicantId] ?? [];
}

// Future: PATCH `${BASE_URL}/notifications/{id}`
export async function markNotificationRead(applicantId, notificationId) {
  await delay(200);
  const notifications = mockNotifications[applicantId] ?? [];
  const notification = notifications.find((n) => n.id === notificationId);
  if (notification) notification.read = true;
  syncApplicationState(applicantId);
  return [...notifications];
}

// Future: PATCH `${BASE_URL}/notifications/mark-all-read`
export async function markAllNotificationsRead(applicantId) {
  await delay(300);
  const notifications = mockNotifications[applicantId] ?? [];
  notifications.forEach((n) => {
    n.read = true;
  });
  syncApplicationState(applicantId);
  return [...notifications];
}


/* ----------------------------- Admin ----------------------------- */
// Future: GET `${BASE_URL}/admin/dashboard`
export async function getAdminDashboard() {
  await delay(350);
  syncApplicationState("APL-1001");
  const applications = mockAdminApplications;
  return {
    stats: {
      total: applications.length,
      processing: applications.filter((a) => ["PROCESSING", "VERIFICATION_IN_PROGRESS", "ELIGIBILITY_CHECK"].includes(a.status)).length,
      waitingForDocuments: applications.filter((a) => a.status === "WAITING_FOR_DOCUMENTS").length,
      eligible: applications.filter((a) => ["ELIGIBLE", "PROCESSING_COMPLETE"].includes(a.status)).length,
      exceptions: mockExceptions.filter((e) => e.status !== "RESOLVED").length,
    },
    recentApplications: [...applications].slice(-4).reverse(),
    recentExceptions: mockExceptions.filter((e) => e.status !== "RESOLVED").slice(0, 3),
  };
}

// Future: GET `${BASE_URL}/admin/applications`
export async function getAdminApplications() {
  await delay(400);
  syncApplicationState("APL-1001");
  return [...mockAdminApplications];
}

// Future: GET `${BASE_URL}/admin/applications/{applicationId}`
export async function getAdminApplicationDetails(applicationId) {
  await delay(400);
  syncApplicationState("APL-1001");
  const application = mockAdminApplications.find((a) => a.applicationId === applicationId);
  if (!application) return null;

  const programme = mockPrograms.find((p) => p.id === application.programmeId) ?? null;
  const exceptions = mockExceptions.filter((e) => e.applicationId === applicationId);

  if (application.applicantId === "APL-1001") {
    const applicant = mockApplicants.find((a) => a.id === "APL-1001");
    const documents = mockDocuments["APL-1001"] ?? [];
    const eligibility = await getEligibility("APL-1001");
    const timeline = await getApplicationTimeline("APL-1001");
    const workflow = deriveWorkflow({
      application: mockApplications["APL-1001"],
      documents,
      eligibility,
      notifications: mockNotifications["APL-1001"] ?? [],
    });
    return { ...application, applicant, programme, documents, eligibility, timeline, workflow, exceptions };
  }

  const currentIndex = STATUS_STAGE_INDEX[application.status] ?? 0;
  return {
    ...application,
    applicant: { fullName: application.applicantName, email: application.email },
    programme,
    documents: [],
    eligibility: { overall: application.eligibilityStatus, evaluation: [] },
    timeline: {
      applicationId: application.applicationId,
      programmeId: application.programmeId,
      status: application.status,
      stages: STATUS_STAGES.map((label, index) => ({ label, state: index < currentIndex ? "COMPLETED" : index === currentIndex ? "CURRENT" : "PENDING" })),
      currentAction: application.currentAction,
      applicantAction: application.status === "WAITING_FOR_DOCUMENTS" ? "Upload remaining required documents." : "No applicant action currently required.",
    },
    exceptions,
  };
}

// Future: GET `${BASE_URL}/admin/exceptions`
export async function getAdminExceptions() {
  await delay(350);
  return [...mockExceptions];
}

/* ----------------------------- Programme Rules ----------------------------- */
// Future: GET `${BASE_URL}/admin/programs`
//
// Programme eligibility rules are system-owned, deterministic
// configuration (master prompt section 15/23). This returns exactly
// the same mockEligibilityRules object the applicant-facing
// getEligibility() reads from, so the Admin Programme Rules screen
// can never show different criteria than what Applicant Eligibility
// evaluates against.
export async function getProgrammeRules() {
  await delay(350);
  return mockPrograms.map((programme) => ({
    programme,
    rules: mockEligibilityRules[programme.id] ?? null,
  }));
}

// Future: PUT `${BASE_URL}/admin/programs/{programmeId}`
// Frontend/mock only — no backend persistence exists yet. Updates the
// same mockEligibilityRules object read by getEligibility(), so any
// change made here is immediately reflected on the applicant side too.
export async function updateProgrammeRules(programmeId, updates) {
  await delay(500);
  const existing = mockEligibilityRules[programmeId] ?? { programmeId };
  mockEligibilityRules[programmeId] = { ...existing, ...updates };
  return { ...mockEligibilityRules[programmeId] };
}

/* ----------------------------- Agent Activity ----------------------------- */
// Future: GET `${BASE_URL}/admin/agent-activity`
//
// This is an observable audit trail only — timestamps, tool calls,
// deterministic results and workflow status. It never includes
// private reasoning, internal chain-of-thought, or fabricated model
// thoughts (master prompt section 24/27).
export async function getAgentActivity() {
  await delay(400);
  return [...mockAgentActivity];
}

/* ------------------------------- Analytics ------------------------------- */
// Future: GET `${BASE_URL}/admin/analytics`
//
// Every figure below is derived from mockAdminApplications and
// mockExceptions at call time — nothing here is an independently
// hardcoded number, so Analytics can't drift out of sync with the
// Admin Dashboard or Applications list.
export async function getAdminAnalytics() {
  await delay(400);
  syncApplicationState("APL-1001");

  const applications = mockAdminApplications;
  const total = applications.length;

  const countBy = (list, key) => {
    const counts = {};
    list.forEach((item) => {
      const value = item[key];
      counts[value] = (counts[value] ?? 0) + 1;
    });
    return Object.entries(counts).map(([value, count]) => ({ value, count }));
  };

  const statusDistribution = countBy(applications, "status");
  const eligibilityDistribution = countBy(applications, "eligibilityStatus");

  const documentCompletionDistribution = [
    {
      value: "Fully Submitted",
      count: applications.filter((a) => a.documentStatus.startsWith("6 of 6")).length,
    },
    {
      value: "Partially Submitted",
      count: applications.filter((a) => !a.documentStatus.startsWith("6 of 6")).length,
    },
  ];

  const programmeDistribution = mockPrograms
    .map((programme) => ({
      value: programme.name,
      count: applications.filter((a) => a.programmeId === programme.id).length,
    }))
    .filter((row) => row.count > 0);

  const exceptionSeverityDistribution = countBy(mockExceptions, "severity");
  const exceptionStatusDistribution = countBy(mockExceptions, "status");

  const processingComplete = applications.filter((a) => a.status === "PROCESSING_COMPLETE").length;
  const completionRate = total ? Math.round((processingComplete / total) * 100) : 0;

  return {
    total,
    statusDistribution,
    eligibilityDistribution,
    documentCompletionDistribution,
    programmeDistribution,
    exceptionSeverityDistribution,
    exceptionStatusDistribution,
    completionRate,
    totalExceptions: mockExceptions.length,
    openExceptions: mockExceptions.filter((e) => e.status !== "RESOLVED").length,
  };
}
