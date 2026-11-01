import apiClient, { USE_MOCKS } from "./apiClient";
import { mockExceptions } from "../data/mockData";

export function shouldUseMock(token) {
  if (!USE_MOCKS) return false;
  if (token && token !== "test-auth-token" && token !== "mock-jwt-token") {
    return false;
  }
  return true;
}

/**
 * Retrieve exceptions with optional status, severity, and type filters.
 * Seamlessly supports both mock mode and live backend.
 */
export async function getAdminExceptions(filters = {}, token) {
  if (shouldUseMock(token)) {
    let list = [...mockExceptions];
    if (filters.status && filters.status !== "ALL") {
      list = list.filter((e) => e.status === filters.status);
    }
    if (filters.severity && filters.severity !== "ALL") {
      list = list.filter((e) => e.severity === filters.severity);
    }
    if (filters.type && filters.type !== "ALL") {
      list = list.filter((e) => e.type === filters.type);
    }
    return list;
  }

  const query = new URLSearchParams();
  if (filters.status && filters.status !== "ALL") query.set("status", filters.status);
  if (filters.severity && filters.severity !== "ALL") query.set("severity", filters.severity);
  if (filters.type && filters.type !== "ALL") query.set("type", filters.type);
  if (filters.applicationId) query.set("applicationId", filters.applicationId);

  const qs = query.toString();
  const endpoint = `/exceptions${qs ? `?${qs}` : ""}`;
  const headers = token ? { Authorization: `Bearer ${token}` } : {};

  return await apiClient.get(endpoint, { headers });
}

/**
 * Retrieve a single exception by ID.
 */
export async function getExceptionById(exceptionId, token) {
  if (shouldUseMock(token)) {
    const found = mockExceptions.find(
      (e) => (e.id || e.exceptionId) === exceptionId
    );
    if (!found) throw new Error(`Exception '${exceptionId}' not found`);
    return found;
  }

  const headers = token ? { Authorization: `Bearer ${token}` } : {};
  return await apiClient.get(`/exceptions/${exceptionId}`, { headers });
}

/**
 * Resolve an exception as an administrator with mandatory justification reason.
 */
export async function resolveException(exceptionId, resolutionReason, token) {
  if (shouldUseMock(token)) {
    const found = mockExceptions.find(
      (e) => (e.id || e.exceptionId) === exceptionId
    );
    if (found) {
      found.status = "RESOLVED";
      found.resolutionReason = resolutionReason;
      found.resolvedAt = new Date().toISOString();
      return found;
    }
    throw new Error(`Exception '${exceptionId}' not found`);
  }

  const headers = token ? { Authorization: `Bearer ${token}` } : {};
  return await apiClient.post(
    `/exceptions/${exceptionId}/resolve`,
    { resolutionReason },
    { headers }
  );
}

