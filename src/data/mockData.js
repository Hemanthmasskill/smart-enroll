/**
 * Centralized mock data for Smart Enroll.
 *
 * This file is the single source of mock data for the whole frontend
 * so nothing gets hardcoded inside individual components. It grows as
 * each module (dashboard, documents, admin, etc.) is implemented.
 */

export const mockApplicants = [
  {
    id: "APL-1001",
    fullName: "Hemanth M.P.",
    email: "hemanth@example.com",
    mobile: "9876543210",
    dob: "2001-06-14",
    applicationId: "SE20260001",
  },
];

export const mockPrograms = [
  { id: "mca", name: "MCA", fullName: "Master of Computer Applications" },
  { id: "mba", name: "MBA", fullName: "Master of Business Administration" },
  {
    id: "msc-cs",
    name: "M.Sc Computer Science",
    fullName: "Master of Science in Computer Science",
  },
  {
    id: "mtech-cs",
    name: "M.Tech Computer Science",
    fullName: "Master of Technology in Computer Science",
  },
];

/**
 * The applicant's admission application (demo scenario: Hemanth applying
 * for MCA — see master prompt section 38). Keyed by applicantId so the
 * dashboard, documents, status and profile pages all read the same state.
 */
export const mockApplications = {
  "APL-1001": {
    applicationId: "SE20260001",
    applicantId: "APL-1001",
    programmeId: "mca",
    status: "WAITING_FOR_DOCUMENTS",
    progressPercent: 45,
    documentsSubmitted: 4,
    documentsRequired: 6,
    eligibilityStatus: "PENDING",
    unreadNotifications: 3,
    nextAction: "2 documents are still required.",
    currentAction:
      "Smart Enroll is verifying your submitted documents and waiting for the remaining required files.",
    submittedAt: "2026-09-05",
  },
};

/**
 * Required documents for the applicant's current application.
 * Statuses reflect the demo scenario (master prompt section 38):
 * 4 of 6 documents submitted, Transfer Certificate and Government ID
 * still missing. Kept in sync with mockApplications.APL-1001 counts.
 *
 * Three-layer verification principle (master prompt section 28):
 *   1. extraction   — what OCR read off the document (does not imply authenticity)
 *   2. validation   — does the extracted content structurally match the applicant/application
 *   3. authoritative — can the record be confirmed via DigiLocker/NAD or another issuer source
 */
export const mockDocuments = {
  "APL-1001": [
    {
      id: "doc-10th",
      name: "10th Marksheet",
      required: true,
      status: "VERIFIED",
      fileName: "10th_marksheet.pdf",
      uploadedAt: "05 Sep 2026",
      details: {
        extraction: {
          "Candidate Name": "Hemanth M.P.",
          Board: "State Board",
          "Year of Passing": "2017",
          Percentage: "88%",
        },
        validation: {
          "Name Match": "Passed",
          "Academic details": "Passed",
        },
        authoritative: { status: "UNAVAILABLE" },
      },
    },
    {
      id: "doc-12th",
      name: "12th Marksheet",
      required: true,
      status: "VERIFIED",
      fileName: "12th_marksheet.pdf",
      uploadedAt: "05 Sep 2026",
      details: {
        extraction: {
          "Candidate Name": "Hemanth M.P.",
          Board: "State Board",
          "Year of Passing": "2019",
          Percentage: "84%",
        },
        validation: {
          "Name Match": "Passed",
          "Academic details": "Passed",
        },
        authoritative: { status: "UNAVAILABLE" },
      },
    },
    {
      id: "doc-ug-marksheet",
      name: "Undergraduate Marksheet",
      required: true,
      status: "VALIDATED",
      fileName: "ug_marksheet.pdf",
      uploadedAt: "05 Sep 2026",
      details: {
        extraction: {
          "Candidate Name": "Hemanth M.P.",
          "Register Number": "21BCS1042",
          Degree: "B.Sc Computer Science",
          University: "Example University",
          CGPA: "7.8",
        },
        validation: {
          "Name Match": "Passed",
          "Register Number": "Detected",
          Programme: "Passed",
          "Academic details": "Passed",
        },
        authoritative: { status: "UNAVAILABLE" },
      },
    },
    {
      id: "doc-degree",
      name: "Degree / Provisional Certificate",
      required: true,
      status: "PROCESSING",
      fileName: "degree_certificate.pdf",
      uploadedAt: "05 Sep 2026",
      details: {
        extraction: {
          "Candidate Name": "Hemanth M.P.",
          "Register Number": "21BCS1042",
          Degree: "B.Sc Computer Science",
          University: "Example University",
          "Graduation Year": "2025",
          CGPA: "7.8",
        },
        validation: {
          "Name Match": "Passed",
          "Register Number": "Detected",
          Programme: "Passed",
          "Academic details": "Passed",
        },
        authoritative: { status: "PENDING" },
      },
    },
    {
      id: "doc-transfer",
      name: "Transfer Certificate",
      required: true,
      status: "NOT_UPLOADED",
      fileName: null,
      uploadedAt: null,
      details: null,
    },
    {
      id: "doc-govt-id",
      name: "Government ID",
      required: true,
      status: "NOT_UPLOADED",
      fileName: null,
      uploadedAt: null,
      details: null,
    },
  ],
};

/**
 * DigiLocker/NAD simulation records. This is a frontend simulation
 * only — no live DigiLocker or NAD integration exists yet.
 */
export const mockDigiLockerRecords = {
  "APL-1001": [
    {
      id: "dl-degree",
      documentType: "Degree Certificate",
      issuer: "B.S. Abdur Rahman Crescent Institute of Science and Technology",
      year: "2025",
      status: "VERIFIED",
    },
  ],
};

export const mockRecentActivity = [
  { id: "act-1", label: "Application submitted", timestamp: "05 Sep 2026, 10:02 AM" },
  { id: "act-2", label: "10th Marksheet verified", timestamp: "05 Sep 2026, 11:14 AM" },
  { id: "act-3", label: "12th Marksheet verified", timestamp: "05 Sep 2026, 11:16 AM" },
  { id: "act-4", label: "Transfer Certificate requested", timestamp: "05 Sep 2026, 11:20 AM" },
  { id: "act-5", label: "Degree certificate under verification", timestamp: "05 Sep 2026, 11:25 AM" },
];

/**
 * Configured, deterministic programme admission rules (master prompt
 * section 15): "Eligibility criteria are configured system rules. The
 * AI does not invent admission rules." Only MCA is fully configured
 * here since it's the only programme in the current demo application;
 * the remaining programmes are filled in for the Admin increment.
 */
export const mockEligibilityRules = {
  mca: {
    programmeId: "mca",
    minimumQualification: "Bachelor's Degree",
    minimumPercentage: "50%",
    mathematicsRequirement: "Required at 10+2 or Graduation level",
    requiredDocuments: "All 6 programme-required documents",
    entranceRequirement: "Not Applicable",
  },
  mba: {
    programmeId: "mba",
    minimumQualification: "Bachelor's Degree (any discipline)",
    minimumPercentage: "50%",
    mathematicsRequirement: "Not Required",
    requiredDocuments: "All 6 programme-required documents",
    entranceRequirement: "Not Applicable",
  },
  "msc-cs": {
    programmeId: "msc-cs",
    minimumQualification: "Bachelor's Degree",
    minimumPercentage: "55%",
    mathematicsRequirement: "Required at Graduation level",
    requiredDocuments: "All 6 programme-required documents",
    entranceRequirement: "Not Applicable",
  },
  "mtech-cs": {
    programmeId: "mtech-cs",
    minimumQualification: "Bachelor's Degree in Engineering/Technology",
    minimumPercentage: "60%",
    mathematicsRequirement: "Required at Graduation level",
    requiredDocuments: "All 6 programme-required documents",
    entranceRequirement: "Not Applicable",
  },
};

/**
 * Notifications for the applicant's current application. Kept in sync
 * with mockApplications.APL-1001.unreadNotifications (3 unread) and
 * with mockDocuments (Transfer Certificate / Government ID missing,
 * Degree Certificate still processing) so no page contradicts another.
 */
export const mockNotifications = {
  "APL-1001": [
    {
      id: "ntf-1",
      title: "Application submitted successfully",
      description: "Your MCA admission application SE20260001 has been received by Smart Enroll.",
      timestamp: "05 Sep 2026, 10:02 AM",
      read: true,
    },
    {
      id: "ntf-2",
      title: "10th Marksheet verified",
      description: "Your 10th Marksheet has passed content validation and document checks.",
      timestamp: "05 Sep 2026, 11:14 AM",
      read: true,
    },
    {
      id: "ntf-3",
      title: "12th Marksheet verified",
      description: "Your 12th Marksheet has passed content validation and document checks.",
      timestamp: "05 Sep 2026, 11:16 AM",
      read: true,
    },
    {
      id: "ntf-4",
      title: "Degree Certificate verification in progress",
      description:
        "OCR extraction and content validation are complete. Authoritative verification via DigiLocker/NAD is still pending.",
      timestamp: "05 Sep 2026, 11:25 AM",
      read: false,
    },
    {
      id: "ntf-5",
      title: "Transfer Certificate required",
      description: "Please upload your Transfer Certificate to continue processing your application.",
      timestamp: "05 Sep 2026, 11:20 AM",
      read: false,
    },
    {
      id: "ntf-6",
      title: "Government ID required",
      description: "Please upload a valid Government ID to continue processing your application.",
      timestamp: "05 Sep 2026, 11:21 AM",
      read: false,
    },
  ],
};

/**
 * Increment 5 admin data. The first record is derived from the same APL-1001
 * scenario used by the applicant portal; the additional records exist only to
 * make admin monitoring, filtering and dashboard summaries meaningful.
 */
export const mockAdminApplications = [
  {
    applicationId: "SE20260001", applicantId: "APL-1001", applicantName: "Hemanth M.P.",
    email: "hemanth@example.com", programmeId: "mca", submittedAt: "2026-09-05",
    status: "WAITING_FOR_DOCUMENTS", documentStatus: "4 of 6 Submitted", eligibilityStatus: "PENDING",
    currentAction: "Verifying submitted documents and waiting for the remaining required files.",
    academic: { qualification: "B.Sc. Computer Science", institution: "Crescent University", result: "CGPA 6.969" },
  },
  { applicationId: "SE20260002", applicantId: "APL-1002", applicantName: "Aisha Rahman", email: "aisha@example.com", programmeId: "mba", submittedAt: "2026-09-06", status: "VERIFICATION_IN_PROGRESS", documentStatus: "6 of 6 Submitted", eligibilityStatus: "PENDING", currentAction: "Cross-validating submitted academic records.", academic: { qualification: "B.Com", institution: "Madras University", result: "72%" } },
  { applicationId: "SE20260003", applicantId: "APL-1003", applicantName: "Karthik S", email: "karthik@example.com", programmeId: "msc-cs", submittedAt: "2026-09-06", status: "ELIGIBLE", documentStatus: "6 of 6 Verified", eligibilityStatus: "ELIGIBLE", currentAction: "Eligibility checks completed; preparing processing outcome.", academic: { qualification: "B.Sc. Computer Science", institution: "Bharathiar University", result: "81%" } },
  { applicationId: "SE20260004", applicantId: "APL-1004", applicantName: "Priya N", email: "priya@example.com", programmeId: "mtech-cs", submittedAt: "2026-09-07", status: "EXCEPTION", documentStatus: "6 of 6 Submitted", eligibilityStatus: "PENDING", currentAction: "Processing paused at an exception requiring review.", academic: { qualification: "B.E. Computer Science", institution: "Anna University", result: "76%" } },
  { applicationId: "SE20260005", applicantId: "APL-1005", applicantName: "Arun Kumar", email: "arun@example.com", programmeId: "mca", submittedAt: "2026-09-07", status: "PROCESSING_COMPLETE", documentStatus: "6 of 6 Verified", eligibilityStatus: "ELIGIBLE", currentAction: "Autonomous admission processing completed.", academic: { qualification: "BCA", institution: "University of Madras", result: "68%" } },
  { applicationId: "SE20260006", applicantId: "APL-1006", applicantName: "Meera Joseph", email: "meera@example.com", programmeId: "mba", submittedAt: "2026-09-08", status: "INELIGIBLE", documentStatus: "6 of 6 Verified", eligibilityStatus: "INELIGIBLE", currentAction: "Eligibility evaluation completed against configured programme rules.", academic: { qualification: "B.A. Economics", institution: "Kerala University", result: "47%" } },
];

export const mockExceptions = [
  { id: "EXC-001", applicationId: "SE20260001", applicantName: "Hemanth M.P.", type: "MISSING_DOCUMENT", description: "Transfer Certificate and Government ID have not been submitted.", severity: "MEDIUM", createdAt: "05 Sep 2026, 11:21 AM", status: "OPEN" },
  { id: "EXC-002", applicationId: "SE20260004", applicantName: "Priya N", type: "CROSS_DOCUMENT_MISMATCH", description: "Candidate name differs between the degree certificate and application record.", severity: "HIGH", createdAt: "07 Sep 2026, 02:14 PM", status: "OPEN" },
  { id: "EXC-003", applicationId: "SE20260002", applicantName: "Aisha Rahman", type: "VERIFICATION_UNAVAILABLE", description: "Authoritative issuer verification is temporarily unavailable for one academic record.", severity: "LOW", createdAt: "06 Sep 2026, 04:40 PM", status: "MONITORING" },
  { id: "EXC-004", applicationId: "SE20260005", applicantName: "Arun Kumar", type: "UNSUPPORTED_FORMAT", description: "An earlier document upload used an unsupported format; a valid replacement was received.", severity: "LOW", createdAt: "07 Sep 2026, 09:30 AM", status: "RESOLVED" },
];

/**
 * Agent Activity / audit trail (master prompt sections 24 & 27).
 *
 * This is an observable audit log of the OBSERVE → PLAN → ACT → VERIFY →
 * RE-PLAN workflow — tool calls, deterministic decisions, and results
 * only. It never records private reasoning or chain-of-thought, and it
 * is built to match each application's existing status exactly (see
 * mockAdminApplications / mockExceptions above) so this page can't
 * contradict the Dashboard, Applications, or Exceptions views.
 */
export const mockAgentActivity = [
  // SE20260001 — Hemanth M.P. (MCA) — WAITING_FOR_DOCUMENTS
  { id: "log-001", timestamp: "05 Sep 2026, 10:02:14 AM", applicationId: "SE20260001", applicantName: "Hemanth M.P.", stage: "OBSERVE", tool: "get_application", action: "Application received", result: "Application SE20260001 loaded", status: "COMPLETED" },
  { id: "log-002", timestamp: "05 Sep 2026, 10:02:17 AM", applicationId: "SE20260001", applicantName: "Hemanth M.P.", stage: "PLAN", tool: "get_program_requirements", action: "Loaded MCA admission requirements", result: "Configured programme rules retrieved", status: "COMPLETED" },
  { id: "log-003", timestamp: "05 Sep 2026, 10:02:20 AM", applicationId: "SE20260001", applicantName: "Hemanth M.P.", stage: "ACT", tool: "check_document_completeness", action: "Checked required documents", result: "4 of 6 required documents present", status: "COMPLETED" },
  { id: "log-004", timestamp: "05 Sep 2026, 11:14:12 AM", applicationId: "SE20260001", applicantName: "Hemanth M.P.", stage: "ACT", tool: "extract_document_data", action: "OCR extraction requested and completed", result: "Extraction completed for 10th, 12th, UG Marksheet, Degree Certificate", status: "COMPLETED" },
  { id: "log-005", timestamp: "05 Sep 2026, 11:14:18 AM", applicationId: "SE20260001", applicantName: "Hemanth M.P.", stage: "VERIFY", tool: "compare_applicant_details", action: "Content validation performed", result: "Name and academic details matched for submitted documents", status: "COMPLETED" },
  { id: "log-006", timestamp: "05 Sep 2026, 11:14:23 AM", applicationId: "SE20260001", applicantName: "Hemanth M.P.", stage: "ACT", tool: "verify_document", action: "DigiLocker/NAD verification requested for Degree Certificate", result: "Authoritative verification pending", status: "PENDING" },
  { id: "log-007", timestamp: "05 Sep 2026, 11:20:02 AM", applicationId: "SE20260001", applicantName: "Hemanth M.P.", stage: "RE-PLAN", tool: "request_missing_document", action: "Missing document detected", result: "Transfer Certificate and Government ID requested from applicant", status: "COMPLETED" },
  { id: "log-008", timestamp: "05 Sep 2026, 11:20:10 AM", applicationId: "SE20260001", applicantName: "Hemanth M.P.", stage: "ACT", tool: "update_application_status", action: "Updated application status", result: "Status set to WAITING_FOR_DOCUMENTS", status: "COMPLETED" },
  { id: "log-009", timestamp: "05 Sep 2026, 11:20:15 AM", applicationId: "SE20260001", applicantName: "Hemanth M.P.", stage: "ACT", tool: "send_notification", action: "Applicant notification generated", result: "Notifications sent for missing documents", status: "COMPLETED" },
  { id: "log-010", timestamp: "05 Sep 2026, 11:25:00 AM", applicationId: "SE20260001", applicantName: "Hemanth M.P.", stage: "OBSERVE", tool: "get_application", action: "Workflow paused waiting for applicant", result: "No further action until remaining documents are uploaded", status: "PAUSED" },

  // SE20260002 — Aisha Rahman (MBA) — VERIFICATION_IN_PROGRESS
  { id: "log-011", timestamp: "06 Sep 2026, 09:10:04 AM", applicationId: "SE20260002", applicantName: "Aisha Rahman", stage: "OBSERVE", tool: "get_application", action: "Application received", result: "Application SE20260002 loaded", status: "COMPLETED" },
  { id: "log-012", timestamp: "06 Sep 2026, 09:10:08 AM", applicationId: "SE20260002", applicantName: "Aisha Rahman", stage: "PLAN", tool: "get_program_requirements", action: "Loaded MBA admission requirements", result: "Configured programme rules retrieved", status: "COMPLETED" },
  { id: "log-013", timestamp: "06 Sep 2026, 09:10:12 AM", applicationId: "SE20260002", applicantName: "Aisha Rahman", stage: "ACT", tool: "check_document_completeness", action: "Checked required documents", result: "6 of 6 required documents present", status: "COMPLETED" },
  { id: "log-014", timestamp: "06 Sep 2026, 09:25:40 AM", applicationId: "SE20260002", applicantName: "Aisha Rahman", stage: "ACT", tool: "extract_document_data", action: "OCR extraction requested and completed", result: "Extraction completed for all submitted documents", status: "COMPLETED" },
  { id: "log-015", timestamp: "06 Sep 2026, 04:35:00 PM", applicationId: "SE20260002", applicantName: "Aisha Rahman", stage: "VERIFY", tool: "compare_applicant_details", action: "Content validation performed", result: "Academic details cross-validated against application", status: "COMPLETED" },
  { id: "log-016", timestamp: "06 Sep 2026, 04:40:00 PM", applicationId: "SE20260002", applicantName: "Aisha Rahman", stage: "VERIFY", tool: "verify_document", action: "DigiLocker/NAD verification requested", result: "Authoritative verification temporarily unavailable for one record", status: "IN_PROGRESS" },

  // SE20260003 — Karthik S (M.Sc CS) — ELIGIBLE
  { id: "log-017", timestamp: "06 Sep 2026, 08:05:00 AM", applicationId: "SE20260003", applicantName: "Karthik S", stage: "OBSERVE", tool: "get_application", action: "Application received", result: "Application SE20260003 loaded", status: "COMPLETED" },
  { id: "log-018", timestamp: "06 Sep 2026, 08:05:05 AM", applicationId: "SE20260003", applicantName: "Karthik S", stage: "PLAN", tool: "get_program_requirements", action: "Loaded M.Sc Computer Science admission requirements", result: "Configured programme rules retrieved", status: "COMPLETED" },
  { id: "log-019", timestamp: "06 Sep 2026, 08:10:00 AM", applicationId: "SE20260003", applicantName: "Karthik S", stage: "ACT", tool: "check_document_completeness", action: "Checked required documents", result: "6 of 6 required documents present", status: "COMPLETED" },
  { id: "log-020", timestamp: "06 Sep 2026, 08:40:00 AM", applicationId: "SE20260003", applicantName: "Karthik S", stage: "ACT", tool: "extract_document_data", action: "OCR extraction and DigiLocker/NAD verification completed", result: "All submitted documents verified", status: "COMPLETED" },
  { id: "log-021", timestamp: "06 Sep 2026, 09:00:00 AM", applicationId: "SE20260003", applicantName: "Karthik S", stage: "VERIFY", tool: "check_eligibility", action: "Eligibility rules evaluated", result: "All configured M.Sc CS criteria satisfied", status: "COMPLETED" },
  { id: "log-022", timestamp: "06 Sep 2026, 09:02:00 AM", applicationId: "SE20260003", applicantName: "Karthik S", stage: "ACT", tool: "update_application_status", action: "Updated application status", result: "Application marked ELIGIBLE", status: "COMPLETED" },
  { id: "log-023", timestamp: "06 Sep 2026, 09:03:00 AM", applicationId: "SE20260003", applicantName: "Karthik S", stage: "ACT", tool: "send_notification", action: "Applicant notification generated", result: "Applicant notified of eligibility outcome", status: "COMPLETED" },

  // SE20260004 — Priya N (M.Tech CS) — EXCEPTION
  { id: "log-024", timestamp: "07 Sep 2026, 01:00:00 PM", applicationId: "SE20260004", applicantName: "Priya N", stage: "OBSERVE", tool: "get_application", action: "Application received", result: "Application SE20260004 loaded", status: "COMPLETED" },
  { id: "log-025", timestamp: "07 Sep 2026, 01:00:05 PM", applicationId: "SE20260004", applicantName: "Priya N", stage: "PLAN", tool: "get_program_requirements", action: "Loaded M.Tech Computer Science admission requirements", result: "Configured programme rules retrieved", status: "COMPLETED" },
  { id: "log-026", timestamp: "07 Sep 2026, 01:10:00 PM", applicationId: "SE20260004", applicantName: "Priya N", stage: "ACT", tool: "check_document_completeness", action: "Checked required documents", result: "6 of 6 required documents present", status: "COMPLETED" },
  { id: "log-027", timestamp: "07 Sep 2026, 01:40:00 PM", applicationId: "SE20260004", applicantName: "Priya N", stage: "ACT", tool: "extract_document_data", action: "OCR extraction completed", result: "Extraction completed for all submitted documents", status: "COMPLETED" },
  { id: "log-028", timestamp: "07 Sep 2026, 02:10:00 PM", applicationId: "SE20260004", applicantName: "Priya N", stage: "VERIFY", tool: "compare_applicant_details", action: "Content validation performed", result: "Name mismatch detected between Degree Certificate and application record", status: "FLAGGED" },
  { id: "log-029", timestamp: "07 Sep 2026, 02:14:00 PM", applicationId: "SE20260004", applicantName: "Priya N", stage: "RE-PLAN", tool: "create_exception", action: "Exception generated", result: "Cross-document mismatch exception EXC-002 created", status: "COMPLETED" },
  { id: "log-030", timestamp: "07 Sep 2026, 02:16:00 PM", applicationId: "SE20260004", applicantName: "Priya N", stage: "ACT", tool: "send_notification", action: "Applicant notification generated", result: "Supporting evidence requested from applicant", status: "COMPLETED" },
  { id: "log-031", timestamp: "07 Sep 2026, 02:17:00 PM", applicationId: "SE20260004", applicantName: "Priya N", stage: "OBSERVE", tool: "get_application", action: "Workflow paused at exception", result: "Processing paused pending review", status: "PAUSED" },

  // SE20260005 — Arun Kumar (MCA) — PROCESSING_COMPLETE
  { id: "log-032", timestamp: "07 Sep 2026, 08:00:00 AM", applicationId: "SE20260005", applicantName: "Arun Kumar", stage: "OBSERVE", tool: "get_application", action: "Application received", result: "Application SE20260005 loaded", status: "COMPLETED" },
  { id: "log-033", timestamp: "07 Sep 2026, 08:00:05 AM", applicationId: "SE20260005", applicantName: "Arun Kumar", stage: "PLAN", tool: "get_program_requirements", action: "Loaded MCA admission requirements", result: "Configured programme rules retrieved", status: "COMPLETED" },
  { id: "log-034", timestamp: "07 Sep 2026, 08:30:00 AM", applicationId: "SE20260005", applicantName: "Arun Kumar", stage: "ACT", tool: "extract_document_data", action: "OCR extraction and DigiLocker/NAD verification completed", result: "All 6 documents verified", status: "COMPLETED" },
  { id: "log-035", timestamp: "07 Sep 2026, 09:00:00 AM", applicationId: "SE20260005", applicantName: "Arun Kumar", stage: "VERIFY", tool: "check_eligibility", action: "Eligibility rules evaluated", result: "All configured MCA criteria satisfied", status: "COMPLETED" },
  { id: "log-036", timestamp: "07 Sep 2026, 09:02:00 AM", applicationId: "SE20260005", applicantName: "Arun Kumar", stage: "ACT", tool: "update_application_status", action: "Updated application status", result: "Application marked ELIGIBLE", status: "COMPLETED" },
  { id: "log-037", timestamp: "07 Sep 2026, 09:05:00 AM", applicationId: "SE20260005", applicantName: "Arun Kumar", stage: "ACT", tool: "record_audit_event", action: "Admission processing marked complete", result: "Status set to PROCESSING_COMPLETE", status: "COMPLETED" },

  // SE20260006 — Meera Joseph (MBA) — INELIGIBLE
  { id: "log-038", timestamp: "08 Sep 2026, 10:00:00 AM", applicationId: "SE20260006", applicantName: "Meera Joseph", stage: "OBSERVE", tool: "get_application", action: "Application received", result: "Application SE20260006 loaded", status: "COMPLETED" },
  { id: "log-039", timestamp: "08 Sep 2026, 10:00:05 AM", applicationId: "SE20260006", applicantName: "Meera Joseph", stage: "PLAN", tool: "get_program_requirements", action: "Loaded MBA admission requirements", result: "Minimum percentage configured at 50%", status: "COMPLETED" },
  { id: "log-040", timestamp: "08 Sep 2026, 10:30:00 AM", applicationId: "SE20260006", applicantName: "Meera Joseph", stage: "ACT", tool: "extract_document_data", action: "OCR extraction and verification completed", result: "All 6 documents verified", status: "COMPLETED" },
  { id: "log-041", timestamp: "08 Sep 2026, 11:00:00 AM", applicationId: "SE20260006", applicantName: "Meera Joseph", stage: "VERIFY", tool: "check_eligibility", action: "Eligibility rules evaluated", result: "Minimum percentage criterion not met (47% recorded against 50% required)", status: "COMPLETED" },
  { id: "log-042", timestamp: "08 Sep 2026, 11:02:00 AM", applicationId: "SE20260006", applicantName: "Meera Joseph", stage: "ACT", tool: "update_application_status", action: "Updated application status", result: "Application marked INELIGIBLE", status: "COMPLETED" },
  { id: "log-043", timestamp: "08 Sep 2026, 11:03:00 AM", applicationId: "SE20260006", applicantName: "Meera Joseph", stage: "ACT", tool: "send_notification", action: "Applicant notification generated", result: "Applicant notified of ineligibility outcome", status: "COMPLETED" },
];
