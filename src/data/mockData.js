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
