import { Navigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";

/**
 * Wrap applicant or admin routes with this to enforce mock role-based
 * access. `allowedRole` is "user" or "admin". Real authorization will
 * later be enforced by FastAPI — this only protects the demo UI.
 */
export default function ProtectedRoute({ allowedRole, children }) {
  const { isAuthenticated, role, isLoading } = useAuth();

  if (isLoading) return null;

  if (!isAuthenticated) {
    return <Navigate to="/login" replace />;
  }

  if (role !== allowedRole) {
    return <Navigate to={role === "admin" ? "/admin" : "/dashboard"} replace />;
  }

  return children;
}
