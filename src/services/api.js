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

import { mockApplicants } from "../data/mockData";

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
