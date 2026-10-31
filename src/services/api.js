/**
 * Smart Enroll API service layer.
 */

import apiClient, { API_BASE_URL, USE_MOCKS, ApiError } from "./apiClient";
import {
  resetMockData,
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

export const BASE_URL = API_BASE_URL;
export { resetMockData };

export function shouldUseMock(token) {
  if (!USE_MOCKS) return false;
  if (token && token !== "test-auth-token" && token !== "mock-jwt-token") {
    return false;
  }
  return true;
}

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
// POST `${BASE_URL}/auth/login`
export async function loginRequest({ email, password, role }) {
  if (USE_MOCKS) {
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
      token: "test-auth-token",
    };
  }

  const data = await apiClient.post("/auth/login", { email, password, role });
  return {
    role: data.role,
    name: data.name,
    email: data.email,
    applicantId: data.applicantId ?? null,
    token: data.token,
  };
}

// POST `${BASE_URL}/auth/register`
export async function registerRequest(formData) {
  if (USE_MOCKS) {
    await delay(700);
    return {
      role: "user",
      name: formData.fullName,
      email: formData.email,
      applicantId: "APL-1001",
      token: "test-auth-token",
    };
  }

  const data = await apiClient.post("/auth/register", {
    fullName: formData.fullName,
    email: formData.email,
    mobile: formData.mobile,
    dob: formData.dob,
    password: formData.password,
  });
  return {
    role: data.role,
    name: data.name,
    email: data.email,
    applicantId: data.applicantId ?? null,
    token: data.token,
  };
}

/* --------------------------- Application --------------------------- */
// GET `${BASE_URL}/applications/me`
export async function getApplication(applicantId, token) {
  if (USE_MOCKS) {
    await delay(400);
    return syncApplicationState(applicantId);
  }

  const headers = token ? { Authorization: `Bearer ${token}` } : {};
  try {
    const app = await apiClient.get("/applications/me", { headers });
    if (!app) return null;

    const progressPercent =
      app.status === "DRAFT" ? 20 :
      app.status === "SUBMITTED" ? 30 :
      app.status === "WAITING_FOR_DOCUMENTS" ? 50 :
      app.status === "VERIFICATION_IN_PROGRESS" ? 70 :
      app.status === "EXCEPTION" ? 65 :
      app.status === "ELIGIBILITY_CHECK" ? 85 :
      100;

    return {
      applicationId: app.applicationId,
      applicantId: app.applicantId,
      programmeId: app.programmeId,
      status: app.status,
      progressPercent,
      documentsSubmitted: 0,
      documentsRequired: 6,
      unreadNotifications: 0,
      eligibilityStatus:
        app.status === "ELIGIBLE"
          ? "ELIGIBLE"
          : app.status === "INELIGIBLE"
            ? "INELIGIBLE"
            : "PENDING",
      nextAction:
        app.status === "WAITING_FOR_DOCUMENTS"
          ? "Upload the remaining required documents."
          : app.status === "EXCEPTION"
            ? "Review the document issue shown in your application status."
            : app.status === "DRAFT"
              ? "Complete and submit your application."
              : "No applicant action is currently required.",
      currentAction: `Application is currently in ${app.status} status.`,
      fullName: app.fullName,
      email: app.email,
      mobile: app.mobile,
      dob: app.dob,
      gender: app.gender,
      nationality: app.nationality,
      address: app.address,
      city: app.city,
      state: app.state,
      pinCode: app.pinCode,
      tenthBoard: app.tenthBoard,
      tenthPercentage: app.tenthPercentage,
      twelfthBoard: app.twelfthBoard,
      twelfthPercentage: app.twelfthPercentage,
      ugDegree: app.ugDegree,
      university: app.university,
      graduationYear: app.graduationYear,
      cgpa: app.cgpa,
      submittedAt: app.submittedAt,
      createdAt: app.createdAt,
      updatedAt: app.updatedAt,
    };
  } catch (err) {
    if (err.status === 404) {
      return null;
    }
    throw err;
  }
}

// POST `${BASE_URL}/applications`
export async function createApplication(applicantId, formData, token) {
  if (USE_MOCKS) {
    await delay(700);
    return {
      ...mockApplications[applicantId],
      ...formData,
      status: "SUBMITTED",
      progressPercent: 20,
    };
  }

  const headers = token ? { Authorization: `Bearer ${token}` } : {};
  const created = await apiClient.post("/applications", formData, { headers });
  try {
    const submitted = await apiClient.post(`/applications/${created.applicationId}/submit`, {}, { headers });
    return submitted;
  } catch {
    return created;
  }
}

// PUT `${BASE_URL}/applications/{id}`
export async function updateApplication(applicationId, partialData, token) {
  if (USE_MOCKS) {
    await delay(500);
    return { ...mockApplications[applicationId], ...partialData };
  }

  const headers = token ? { Authorization: `Bearer ${token}` } : {};
  return await apiClient.put(`/applications/${applicationId}`, partialData, { headers });
}

// POST `${BASE_URL}/applications/{id}/submit`
export async function submitApplication(applicationId, token) {
  if (USE_MOCKS) {
    await delay(500);
    const app = mockApplications[applicationId];
    if (app) app.status = "SUBMITTED";
    return app;
  }

  const headers = token ? { Authorization: `Bearer ${token}` } : {};
  return await apiClient.post(`/applications/${applicationId}/submit`, {}, { headers });
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
// GET `${BASE_URL}/auth/me`
export async function getApplicantProfile(applicantId, token) {
  if (USE_MOCKS) {
    await delay(300);
    return mockApplicants.find((a) => a.id === applicantId) ?? null;
  }

  const headers = token ? { Authorization: `Bearer ${token}` } : {};
  const user = await apiClient.get("/auth/me", { headers });
  return {
    id: user.applicant_id || user.applicantId || applicantId,
    fullName: user.full_name || user.fullName || user.name || "Applicant",
    email: user.email,
    mobile: user.mobile || "",
    dob: user.dob || "",
  };
}

// Future: PATCH `${BASE_URL}/applicants/{id}`
export async function updateApplicantProfile(applicantId, updates) {
  await delay(500);
  const applicant = mockApplicants.find((a) => a.id === applicantId);
  if (applicant) Object.assign(applicant, updates);
  return applicant;
}

/* ---------------------------- Documents ------------------------------ */
const FRONTEND_ID_TO_DOC_TYPE = {
  "doc-10th": "10TH_MARKSHEET",
  "doc-12th": "12TH_MARKSHEET",
  "doc-ug-marksheet": "UG_MARKSHEET",
  "doc-degree": "DEGREE_CERTIFICATE",
  "doc-transfer": "TRANSFER_CERTIFICATE",
  "doc-govt-id": "GOVERNMENT_ID",
};

const DOC_TYPE_TO_FRONTEND_ID = {
  "10TH_MARKSHEET": "doc-10th",
  "12TH_MARKSHEET": "doc-12th",
  "UG_MARKSHEET": "doc-ug-marksheet",
  "DEGREE_CERTIFICATE": "doc-degree",
  "TRANSFER_CERTIFICATE": "doc-transfer",
  "GOVERNMENT_ID": "doc-govt-id",
};

// GET `${BASE_URL}/documents` (uses backend via apiClient; no silent mock fallback)
export async function getDocuments(applicantId, token) {
  if (shouldUseMock(token)) {
    await delay(400);
    return mockDocuments[applicantId] ?? [];
  }

  const headers = token ? { Authorization: `Bearer ${token}` } : {};
  const slots = await apiClient.get("/documents", { headers });
  return (slots || []).map((s) => ({
    id: s.id || DOC_TYPE_TO_FRONTEND_ID[s.documentType] || s.documentType.toLowerCase(),
    documentId: s.documentId,
    documentType: s.documentType,
    documentVariant: s.documentVariant,
    variant: s.documentVariant,
    name: s.name,
    required: s.required ?? true,
    status: s.status,
    processingStatus: s.processingStatus || null,
    processingConfidence: s.processingConfidence || null,
    fileName: s.originalFileName || s.fileName,
    uploadedAt: s.uploadedAt
      ? new Date(s.uploadedAt).toLocaleDateString("en-IN", {
          day: "2-digit",
          month: "short",
          year: "numeric",
        })
      : null,
    details: null,
  }));
}

// POST `${BASE_URL}/documents/upload`
export async function uploadDocument(applicantId, documentId, file, variant, token) {
  if (shouldUseMock(token)) {
    await delay(900);
    const documents = mockDocuments[applicantId] ?? [];
    const doc = documents.find((d) => d.id === documentId);
    if (!doc) throw new Error("Document not found.");

    doc.status = "UPLOADED";
    doc.fileName = file?.name ?? "uploaded_file.pdf";
    if (variant) {
      doc.documentVariant = variant;
      doc.variant = variant;
    }
    doc.uploadedAt = new Date().toLocaleDateString("en-IN", {
      day: "2-digit",
      month: "short",
      year: "numeric",
    });
    doc.details = null;
    syncApplicationState(applicantId);

    return { ...doc };
  }

  const formData = new FormData();
  formData.append("file", file);
  const docType = FRONTEND_ID_TO_DOC_TYPE[documentId] || documentId;
  formData.append("documentType", docType);
  if (variant) {
    formData.append("documentVariant", variant);
  }

  const headers = token ? { Authorization: `Bearer ${token}` } : {};
  const saved = await apiClient.post("/documents/upload", formData, { headers });

  return {
    id: documentId,
    documentId: saved.documentId,
    documentType: saved.documentType,
    documentVariant: saved.documentVariant,
    variant: saved.documentVariant,
    name: saved.name || documentId,
    required: saved.required ?? true,
    status: saved.status,
    processingStatus: saved.processingStatus || null,
    processingConfidence: saved.processingConfidence || null,
    fileName: saved.originalFileName || saved.fileName,
    uploadedAt: new Date(saved.uploadedAt).toLocaleDateString("en-IN", {
      day: "2-digit",
      month: "short",
      year: "numeric",
    }),
    details: null,
  };
}

// DELETE `${BASE_URL}/documents/{id}`
export async function removeDocument(applicantId, documentSlotId, token, backendDocumentId, docContext) {
  if (shouldUseMock(token)) {
    await delay(400);
    const documents = mockDocuments[applicantId] ?? [];
    const doc = documents.find((d) => d.id === documentSlotId);
    if (doc) {
      doc.status = "NOT_UPLOADED";
      doc.fileName = null;
      doc.documentVariant = null;
      doc.variant = null;
      doc.uploadedAt = null;
      doc.processingStatus = null;
      doc.processingConfidence = null;
      doc.details = null;
    }
    syncApplicationState(applicantId);
    return { ...doc };
  }

  const targetDocId = backendDocumentId || docContext?.documentId;
  if (!targetDocId) {
    throw new Error("Cannot delete document: missing backend document identifier.");
  }

  const headers = token ? { Authorization: `Bearer ${token}` } : {};
  await apiClient.delete(`/documents/${targetDocId}`, { headers });

  // Successfully deleted on real backend: return slot in NOT_UPLOADED state
  return {
    id: docContext?.id || documentSlotId,
    documentId: null,
    documentType: docContext?.documentType || FRONTEND_ID_TO_DOC_TYPE[documentSlotId] || documentSlotId,
    documentVariant: null,
    variant: null,
    name: docContext?.name || documentSlotId,
    required: docContext?.required ?? true,
    status: "NOT_UPLOADED",
    processingStatus: null,
    processingConfidence: null,
    fileName: null,
    uploadedAt: null,
    details: null,
  };
}

// POST `${BASE_URL}/documents/{document_id}/process`
export async function processDocument(applicantId, documentSlotId, token, backendDocumentId) {
  if (shouldUseMock(token)) {
    await delay(700);
    const documents = mockDocuments[applicantId] ?? [];
    const doc = documents.find((d) => d.id === documentSlotId);
    if (!doc) throw new Error("Document not found for processing.");

    doc.processingStatus = "COMPLETED";
    doc.processingConfidence = 0.90;
    doc.details = doc.details ?? {
      extraction: {
        "Candidate Name": "Hemanth M.P.",
        "Roll Number": "2022MCA041",
        "Marks/Percentage": "86.5%",
        "Institution": "B.S. Abdur Rahman Crescent Institute",
        "Overall Confidence": "90%",
      },
      validation: {
        "Name Match": "Matches application record",
        "DOB Match": "Matches application record",
        "Academic Qualification": "Meets criteria",
      },
      authoritative: {
        status: "PENDING",
      },
    };
    syncApplicationState(applicantId);

    return {
      documentId: backendDocumentId || documentSlotId,
      processingState: "COMPLETED",
      overallConfidence: 0.90,
      textExtracted: true,
      classification: {
        predictedType: FRONTEND_ID_TO_DOC_TYPE[documentSlotId] || "10TH_MARKSHEET",
        confidence: 0.92,
        typeMismatch: false,
      },
      fields: {
        candidateName: { rawValue: "Hemanth M.P.", normalizedValue: "Hemanth M.P.", confidence: 0.92 },
        registrationNumber: { rawValue: "2022MCA041", normalizedValue: "2022MCA041", confidence: 0.88 },
        percentage: { rawValue: "86.5%", normalizedValue: 86.5, confidence: 0.90 },
      },
    };
  }

  if (!backendDocumentId) {
    throw new Error("Cannot process document: missing backend document identifier.");
  }

  const headers = token ? { Authorization: `Bearer ${token}` } : {};
  return await apiClient.post(`/documents/${backendDocumentId}/process`, {}, { headers });
}

// GET `${BASE_URL}/documents/{document_id}/processing-result`
export async function getDocumentProcessingResult(applicantId, documentSlotId, token, backendDocumentId) {
  if (shouldUseMock(token)) {
    await delay(300);
    return {
      documentId: backendDocumentId || documentSlotId,
      processingState: "COMPLETED",
      overallConfidence: 0.90,
      textExtracted: true,
      classification: {
        predictedType: FRONTEND_ID_TO_DOC_TYPE[documentSlotId] || "10TH_MARKSHEET",
        confidence: 0.92,
        typeMismatch: false,
      },
    };
  }

  if (!backendDocumentId) {
    throw new Error("Cannot retrieve processing result: missing backend document identifier.");
  }

  const headers = token ? { Authorization: `Bearer ${token}` } : {};
  return await apiClient.get(`/documents/${backendDocumentId}/processing-result`, { headers });
}

// GET `${BASE_URL}/documents/{id}/verification`
export async function getVerificationStatus(applicantId, documentSlotId, token, backendDocumentId) {
  if (shouldUseMock(token)) {
    await delay(300);
    const documents = mockDocuments[applicantId] ?? [];
    return documents.find((d) => d.id === documentSlotId) ?? null;
  }

  if (!backendDocumentId) {
    throw new Error("Cannot fetch verification status: missing backend document identifier.");
  }

  const headers = token ? { Authorization: `Bearer ${token}` } : {};
  return await apiClient.get(`/documents/${backendDocumentId}/verification`, { headers });
}

// POST `${BASE_URL}/documents/{id}/verify`
export async function verifyDocument(applicantId, documentSlotId, token, backendDocumentId) {
  if (shouldUseMock(token)) {
    await delay(500);
    const documents = mockDocuments[applicantId] ?? [];
    const doc = documents.find((d) => d.id === documentSlotId);
    if (!doc) throw new Error("Document not found for verification.");
    doc.validationStatus = "VALIDATED";
    syncApplicationState(applicantId);
    return {
      documentId: backendDocumentId || documentSlotId,
      documentType: FRONTEND_ID_TO_DOC_TYPE[documentSlotId] || "10TH_MARKSHEET",
      validationStatus: "VALIDATED",
      fieldResults: {},
      crossDocumentResults: [],
      reasons: [],
    };
  }

  if (!backendDocumentId) {
    throw new Error("Cannot verify document: missing backend document identifier.");
  }

  const headers = token ? { Authorization: `Bearer ${token}` } : {};
  return await apiClient.post(`/documents/${backendDocumentId}/verify`, {}, { headers });
}

// POST `${BASE_URL}/documents/{id}/authoritative-verify`
export async function authoritativeVerifyDocument(applicantId, documentSlotId, token, backendDocumentId) {
  if (shouldUseMock(token)) {
    await delay(600);
    return {
      provider: "SyntheticDigiLockerProvider",
      status: "SIMULATED_MATCH",
      isSimulated: true,
      disclaimer: "Simulated record for testing/evaluation. Not connected to live DigiLocker/government APIs.",
      message: "Simulated authoritative credential verified via DigiLocker simulation.",
    };
  }

  if (!backendDocumentId) {
    throw new Error("Cannot run authoritative verification: missing backend document identifier.");
  }

  const headers = token ? { Authorization: `Bearer ${token}` } : {};
  return await apiClient.post(`/documents/${backendDocumentId}/authoritative-verify`, {}, { headers });
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
export async function getEligibility(applicantId, token) {
  if (USE_MOCKS) {
    await delay(500);
    return getSynchronousEligibility(applicantId);
  }

  // Live backend path: do not derive eligibility in browser code
  const app = await getApplication(applicantId, token);
  if (!app) return null;

  if (app.status === "ELIGIBLE") {
    return {
      programmeId: app.programmeId,
      overall: "ELIGIBLE",
      evaluation: [],
    };
  }
  if (app.status === "INELIGIBLE") {
    return {
      programmeId: app.programmeId,
      overall: "INELIGIBLE",
      evaluation: [],
    };
  }

  return {
    programmeId: app.programmeId,
    overall: "DEPENDENCY_PENDING",
    evaluation: [
      {
        label: "Autonomous Eligibility Engine",
        configured: "Increments 16+ Backend Service",
        result: "DEPENDENCY_PENDING",
      },
    ],
  };
}

/* ----------------------------- Integrated Workflow ----------------------------- */
// Future: GET `${BASE_URL}/applications/{id}/workflow`
// Returns only observable workflow state/actions/results. No private reasoning.
export async function getApplicationWorkflow(applicantId, token) {
  if (USE_MOCKS) {
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

  // Live backend path: do not synthesize eligibility in browser
  const app = await getApplication(applicantId, token);
  if (!app) return null;
  return deriveWorkflow({
    application: app,
    documents: [],
    eligibility: {
      overall: app.status === "ELIGIBLE" ? "ELIGIBLE" : app.status === "INELIGIBLE" ? "INELIGIBLE" : "PENDING",
      evaluation: [],
    },
    notifications: [],
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

// GET `${BASE_URL}/applications/{id}/timeline`
export async function getApplicationTimeline(applicantId, token) {
  if (USE_MOCKS) {
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

  // Live backend path
  const app = await getApplication(applicantId, token);
  if (!app) return null;

  const currentIndex = STATUS_STAGE_INDEX[app.status] ?? 0;
  const stages = STATUS_STAGES.map((label, index) => ({
    label,
    state: index < currentIndex ? "COMPLETED" : index === currentIndex ? "CURRENT" : "PENDING",
  }));

  return {
    applicationId: app.applicationId,
    programmeId: app.programmeId,
    status: app.status,
    stages,
    currentAction: app.currentAction,
    applicantAction: app.nextAction,
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

// GET `${BASE_URL}/applications`
export async function getAdminApplications(token) {
  if (USE_MOCKS) {
    await delay(400);
    syncApplicationState("APL-1001");
    return [...mockAdminApplications];
  }

  const headers = token ? { Authorization: `Bearer ${token}` } : {};
  const data = await apiClient.get("/applications", { headers });
  return (data || []).map((app) => ({
    applicationId: app.applicationId,
    applicantId: app.applicantId,
    applicantName: app.applicantName || app.fullName || "Applicant",
    email: app.email,
    programmeId: app.programmeId,
    submittedAt: app.submittedAt ? new Date(app.submittedAt).toLocaleDateString("en-IN", {
      day: "2-digit",
      month: "short",
      year: "numeric",
    }) : "-",
    documentStatus: app.documentStatus || "N/A",
    eligibilityStatus: app.eligibilityStatus || "PENDING",
    status: app.status,
  }));
}

// GET `${BASE_URL}/applications/{applicationId}`
export async function getAdminApplicationDetails(applicationId, token) {
  if (USE_MOCKS) {
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

  // Live backend path
  const headers = token ? { Authorization: `Bearer ${token}` } : {};
  const app = await apiClient.get(`/applications/${applicationId}`, { headers });
  if (!app) return null;

  const programme = mockPrograms.find((p) => p.id === app.programmeId) ?? { id: app.programmeId, name: app.programmeId, fullName: app.programmeId };
  const currentIndex = STATUS_STAGE_INDEX[app.status] ?? 0;

  return {
    applicationId: app.applicationId,
    applicantId: app.applicantId,
    applicantName: app.fullName || "Applicant",
    email: app.email,
    programmeId: app.programmeId,
    programme,
    submittedAt: app.submittedAt ? new Date(app.submittedAt).toLocaleDateString("en-IN", {
      day: "2-digit",
      month: "short",
      year: "numeric",
    }) : "-",
    status: app.status,
    eligibilityStatus: app.status === "ELIGIBLE" ? "ELIGIBLE" : app.status === "INELIGIBLE" ? "INELIGIBLE" : "PENDING",
    eligibility: {
      overall: app.status === "ELIGIBLE" ? "ELIGIBLE" : app.status === "INELIGIBLE" ? "INELIGIBLE" : "PENDING",
      evaluation: [],
    },
    academic: {
      qualification: app.ugDegree || "N/A",
      institution: app.university || "N/A",
      result: app.cgpa ? `CGPA: ${app.cgpa}` : app.twelfthPercentage ? `12th: ${app.twelfthPercentage}%` : "N/A",
    },
    currentAction: `Application status is ${app.status}.`,
    documents: [],
    timeline: {
      applicationId: app.applicationId,
      programmeId: app.programmeId,
      status: app.status,
      stages: STATUS_STAGES.map((label, index) => ({
        label,
        state: index < currentIndex ? "COMPLETED" : index === currentIndex ? "CURRENT" : "PENDING",
      })),
      currentAction: `Application status is ${app.status}.`,
      applicantAction: app.status === "WAITING_FOR_DOCUMENTS" ? "Upload remaining required documents." : "No applicant action currently required.",
    },
    exceptions: [],
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

/* ----------------------------- Agent Activity & Orchestration ----------------------------- */
// GET `${BASE_URL}/agents/activity`
export async function getAgentActivity(filters = {}, token) {
  if (shouldUseMock(token)) {
    await delay(400);
    return [...mockAgentActivity];
  }

  const params = new URLSearchParams();
  if (filters.applicationId && filters.applicationId !== "ALL") params.append("applicationId", filters.applicationId);
  if (filters.stage && filters.stage !== "ALL") params.append("stage", filters.stage);
  if (filters.status && filters.status !== "ALL") params.append("status", filters.status);
  params.append("limit", "100");

  const headers = token ? { Authorization: `Bearer ${token}` } : {};
  const data = await apiClient.get(`/agents/activity?${params.toString()}`, { headers });
  return (data || []).map((r) => ({ ...r, isLive: true }));
}

// GET `${BASE_URL}/agents/system-status`
export async function getAgentSystemStatus() {
  try {
    const data = await apiClient.get("/agents/system-status");
    return { isLive: true, ...data };
  } catch {
    // Backend offline or unreachable
  }

  // Safe fallback static config reflecting repository default
  return {
    llmProvider: "disabled",
    llmEnabled: false,
    llmModel: "gpt-4o-mini",
    isLocalEndpoint: false,
    allowLocalEndpoints: false,
    fallbackEnabled: true,
    timeoutSeconds: 15.0,
    temperature: 0.0,
    availableToolsCount: 13,
    registeredTools: [
      "check_document_completeness",
      "check_eligibility",
      "compare_applicant_details",
      "create_exception",
      "extract_document_data",
      "get_application",
      "get_program_requirements",
      "process_document",
      "record_audit_event",
      "request_missing_document",
      "send_notification",
      "update_application_status",
      "verify_document",
    ],
    isLive: false,
  };
}

// GET `${BASE_URL}/agents/runs`
export async function getRecentOrchestrationRuns(token) {
  if (shouldUseMock(token)) {
    await delay(300);
    return {
      runs: [
        {
          runId: "demo-run-001",
          applicationId: "SE20260001",
          status: "COMPLETED",
          outcome: "WAITING_FOR_APPLICANT",
          currentApplicationStatus: "WAITING_FOR_DOCUMENTS",
          stepsCompleted: 2,
          summary: "Missing required documents detected; application safely transitioned to WAITING_FOR_DOCUMENTS.",
          planner: "LLM",
          fallbackOccurred: false,
          fallbackCount: 0,
          startedAt: "2026-10-26T14:30:00Z",
          completedAt: "2026-10-26T14:30:02Z",
          isDemoMock: true,
          steps: [
            {
              stepIndex: 1,
              stage: "ACT",
              tool: "check_document_completeness",
              action: "Inspect uploaded documents against programme requirements",
              resultSummary: "4 of 6 required documents present. Missing: 12TH_MARKSHEET, TRANSFER_CERTIFICATE",
              status: "COMPLETED",
              planner: "LLM",
              fallbackUsed: false,
              executedAt: "2026-10-26T14:30:01Z",
            },
            {
              stepIndex: 2,
              stage: "ACT",
              tool: "update_application_status",
              action: "Update application status to WAITING_FOR_DOCUMENTS",
              resultSummary: "Application SE20260001 status updated from SUBMITTED to WAITING_FOR_DOCUMENTS.",
              status: "COMPLETED",
              planner: "LLM",
              fallbackUsed: false,
              executedAt: "2026-10-26T14:30:02Z",
            },
          ],
        },
        {
          runId: "demo-run-002",
          applicationId: "SE20260002",
          status: "COMPLETED",
          outcome: "WAITING_FOR_APPLICANT",
          currentApplicationStatus: "WAITING_FOR_DOCUMENTS",
          stepsCompleted: 2,
          summary: "Model proposed invalid tool call for missing documents; domain guardrail (Rule 2) triggered safe deterministic fallback.",
          planner: "LLM",
          fallbackOccurred: true,
          fallbackCount: 1,
          startedAt: "2026-10-26T15:10:00Z",
          completedAt: "2026-10-26T15:10:03Z",
          isDemoMock: true,
          steps: [
            {
              stepIndex: 1,
              stage: "ACT",
              tool: "check_document_completeness",
              action: "Inspect uploaded documents",
              resultSummary: "5 of 6 required documents present",
              status: "COMPLETED",
              planner: "LLM",
              fallbackUsed: false,
              executedAt: "2026-10-26T15:10:01Z",
            },
            {
              stepIndex: 2,
              stage: "ACT",
              tool: "update_application_status",
              action: "Transition to WAITING_FOR_DOCUMENTS via deterministic fallback",
              resultSummary: "Fallback updated status safely after out-of-policy model proposal was rejected.",
              status: "COMPLETED",
              planner: "FALLBACK",
              fallbackUsed: true,
              fallbackReason: "Model proposed request_missing_document before status transition; rejected by Rule 2 guardrail.",
              executedAt: "2026-10-26T15:10:03Z",
            },
          ],
        },
        {
          runId: "demo-run-003",
          applicationId: "SE20260003",
          status: "COMPLETED",
          outcome: "DEPENDENCY_PENDING",
          currentApplicationStatus: "ELIGIBILITY_CHECK",
          stepsCompleted: 3,
          summary: "Verification completed; academic eligibility check paused awaiting Increment 16 engine.",
          planner: "DETERMINISTIC",
          fallbackOccurred: false,
          fallbackCount: 0,
          startedAt: "2026-10-26T16:00:00Z",
          completedAt: "2026-10-26T16:00:04Z",
          isDemoMock: true,
          steps: [
            {
              stepIndex: 1,
              stage: "ACT",
              tool: "check_document_completeness",
              action: "Verify all 6 documents present",
              resultSummary: "6 of 6 required documents present. Complete.",
              status: "COMPLETED",
              planner: "DETERMINISTIC",
              fallbackUsed: false,
              executedAt: "2026-10-26T16:00:01Z",
            },
            {
              stepIndex: 2,
              stage: "ACT",
              tool: "verify_document",
              action: "Validate degree certificate extractions",
              resultSummary: "Layer 2 validation completed: VALIDATED",
              status: "COMPLETED",
              planner: "DETERMINISTIC",
              fallbackUsed: false,
              executedAt: "2026-10-26T16:00:03Z",
            },
            {
              stepIndex: 3,
              stage: "ACT",
              tool: "check_eligibility",
              action: "Evaluate candidate against programme requirements",
              resultSummary: "Deterministic eligibility evaluation service is pending backend implementation in Increment 16.",
              status: "DEPENDENCY_PENDING",
              planner: "DETERMINISTIC",
              fallbackUsed: false,
              executedAt: "2026-10-26T16:00:04Z",
            },
          ],
        },
      ],
      isLive: false,
      error: null,
    };
  }

  try {
    const headers = token ? { Authorization: `Bearer ${token}` } : {};
    const data = await apiClient.get("/agents/runs", { headers });
    return { runs: data || [], isLive: true, error: null };
  } catch (err) {
    return { runs: [], isLive: false, error: err.message };
  }
}

// POST `${BASE_URL}/agents/orchestrate/{application_id}`
export async function triggerAgentOrchestration(applicationId, token) {
  const headers = token ? { Authorization: `Bearer ${token}` } : {};
  return await apiClient.post(`/agents/orchestrate/${applicationId}`, {}, { headers });
}

// Backend Admin Login (for live evaluator connection)
export async function backendAdminLogin({ email, password }) {
  try {
    return await apiClient.post("/auth/login", { email, password, role: "admin" });
  } catch (err) {
    if (err.status === 0 || (err.message && err.message.includes("connection"))) {
      throw new Error(
        `Unable to connect to live backend at ${BASE_URL}. Ensure the FastAPI server is running on port 8000.`
      );
    }
    throw err;
  }
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
