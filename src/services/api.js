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
