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
