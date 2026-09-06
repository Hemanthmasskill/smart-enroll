import { createContext, useContext, useEffect, useState } from "react";
import { loginRequest, registerRequest } from "../services/api";

const AuthContext = createContext(null);

const STORAGE_KEY = "smartenroll_auth";

/**
 * AuthProvider
 * Mock authentication only. Stores { role, name, email, token } in
 * localStorage so a refresh keeps the session during the demo.
 *
 * When FastAPI + JWT auth is ready, only services/api.js and the
 * shape of `session` need to change — components consuming this
 * context (useAuth) will not need to change.
 */
export function AuthProvider({ children }) {
  const [session, setSession] = useState(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored) {
      try {
        setSession(JSON.parse(stored));
      } catch {
        localStorage.removeItem(STORAGE_KEY);
      }
    }
    setIsLoading(false);
  }, []);

  const persist = (nextSession) => {
    setSession(nextSession);
    if (nextSession) {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(nextSession));
    } else {
      localStorage.removeItem(STORAGE_KEY);
    }
  };

  const login = async ({ email, password, role }) => {
    const result = await loginRequest({ email, password, role });
    persist(result);
    return result;
  };

  const register = async (formData) => {
    const result = await registerRequest(formData);
    persist(result);
    return result;
  };

  const logout = () => {
    persist(null);
  };

  const value = {
    session,
    isAuthenticated: Boolean(session),
    role: session?.role ?? null,
    isLoading,
    login,
    register,
    logout,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return ctx;
}
