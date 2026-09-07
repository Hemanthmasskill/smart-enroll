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
} from "../data/mockData";

const BASE_URL = "http://localhost:8000/api/v1";

// Simulates network latency for a more realistic demo.
const delay = (ms = 500) => new Promise((resolve) => setTimeout(resolve, ms));

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
  return mockApplications[applicantId] ?? null;
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

  const application = mockApplications[applicantId];
  const documents = mockDocuments[applicantId] ?? [];
  const rules = application ? mockEligibilityRules[application.programmeId] : null;
  if (!application || !rules) return null;

  const degreeDoc = documents.find((d) => d.id === "doc-degree");
  const ugDoc = documents.find((d) => d.id === "doc-ug-marksheet");
  const allDocumentsSubmitted = application.documentsSubmitted >= application.documentsRequired;

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

  const overall = hasFailed ? "INELIGIBLE" : allDecided ? "ELIGIBLE" : "ELIGIBILITY_CHECK";

  return {
    programmeId: application.programmeId,
    rules,
    evaluation,
    overall,
  };
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
  const application = mockApplications[applicantId];
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
  return [...notifications];
}

// Future: PATCH `${BASE_URL}/notifications/mark-all-read`
export async function markAllNotificationsRead(applicantId) {
  await delay(300);
  const notifications = mockNotifications[applicantId] ?? [];
  notifications.forEach((n) => {
    n.read = true;
  });
  return [...notifications];
}
