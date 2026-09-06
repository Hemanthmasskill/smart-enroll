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
    submittedAt: "2026-09-05",
  },
};

export const mockRecentActivity = [
  { id: "act-1", label: "Application submitted", timestamp: "05 Sep 2026, 10:02 AM" },
  { id: "act-2", label: "10th Marksheet verified", timestamp: "05 Sep 2026, 11:14 AM" },
  { id: "act-3", label: "12th Marksheet verified", timestamp: "05 Sep 2026, 11:16 AM" },
  { id: "act-4", label: "Transfer Certificate requested", timestamp: "05 Sep 2026, 11:20 AM" },
  { id: "act-5", label: "Degree certificate under verification", timestamp: "05 Sep 2026, 11:25 AM" },
];
