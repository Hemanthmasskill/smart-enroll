const AUTH_KEY = "smartenroll_auth";

const env =
  typeof import.meta !== "undefined" && import.meta && import.meta.env
    ? import.meta.env
    : typeof process !== "undefined" && process && process.env
    ? process.env
    : {};

export const API_BASE_URL =
  env.VITE_API_BASE_URL || "http://localhost:8000/api/v1";

export const USE_MOCKS = env.VITE_USE_MOCKS === "true";

if (USE_MOCKS) {
  console.warn(
    "[SmartEnroll] Running in mock-data mode. Backend is not connected."
  );
}

export function getStoredSession() {
  try {
    const raw = localStorage.getItem(AUTH_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

export function clearSession() {
  try {
    localStorage.removeItem(AUTH_KEY);
  } catch {
    // ignore
  }
}

/**
 * Custom ApiError containing status and parsed error details.
 */
export class ApiError extends Error {
  constructor(message, status, data = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.data = data;
  }
}

/**
 * Central fetch wrapper for Smart Enroll backend API.
 * - Injects Bearer token automatically if not passed in headers.
 * - Handles JSON serialization/deserialization.
 * - On HTTP 401, clears stored session and redirects to /login.
 * - Rejects with ApiError on non-2xx responses (no silent fallback).
 */
export async function apiClient(endpoint, options = {}) {
  const url = endpoint.startsWith("http")
    ? endpoint
    : `${API_BASE_URL}${endpoint.startsWith("/") ? "" : "/"}${endpoint}`;

  const headers = new Headers(options.headers || {});

  // Inject Authorization if not already provided
  if (!headers.has("Authorization")) {
    const session = getStoredSession();
    if (session?.token) {
      headers.set("Authorization", `Bearer ${session.token}`);
    }
  }

  // Set Content-Type for JSON unless body is FormData or already set
  if (
    options.body &&
    !(options.body instanceof FormData) &&
    !headers.has("Content-Type")
  ) {
    headers.set("Content-Type", "application/json");
  }

  let response;
  try {
    response = await fetch(url, {
      ...options,
      headers,
    });
  } catch (err) {
    throw new ApiError(
      `Network connection error: unable to connect to backend at ${API_BASE_URL}.`,
      0,
      { originalError: err }
    );
  }

  if (response.status === 401) {
    clearSession();
    if (
      typeof window !== "undefined" &&
      window.location &&
      !window.location.pathname.startsWith("/login") &&
      !window.location.pathname.startsWith("/register")
    ) {
      window.location.href = "/login";
    }
  }

  if (!response.ok) {
    let errorData = null;
    let errorMessage = `HTTP ${response.status} ${response.statusText}`;
    try {
      errorData = await response.json();
      if (typeof errorData === "string") {
        errorMessage = errorData;
      } else if (errorData?.detail) {
        errorMessage =
          typeof errorData.detail === "string"
            ? errorData.detail
            : JSON.stringify(errorData.detail);
      } else if (errorData?.message) {
        errorMessage = errorData.message;
      }
    } catch {
      // response body is not JSON
    }
    throw new ApiError(errorMessage, response.status, errorData);
  }

  // For 204 No Content
  if (response.status === 204) {
    return null;
  }

  // Parse JSON response
  try {
    return await response.json();
  } catch {
    return null;
  }
}

apiClient.get = (endpoint, options = {}) =>
  apiClient(endpoint, { ...options, method: "GET" });

apiClient.post = (endpoint, body, options = {}) =>
  apiClient(endpoint, {
    ...options,
    method: "POST",
    body: body instanceof FormData ? body : JSON.stringify(body),
  });

apiClient.put = (endpoint, body, options = {}) =>
  apiClient(endpoint, {
    ...options,
    method: "PUT",
    body: body instanceof FormData ? body : JSON.stringify(body),
  });

apiClient.patch = (endpoint, body, options = {}) =>
  apiClient(endpoint, {
    ...options,
    method: "PATCH",
    body: body instanceof FormData ? body : JSON.stringify(body),
  });

apiClient.delete = (endpoint, options = {}) =>
  apiClient(endpoint, { ...options, method: "DELETE" });

export default apiClient;
