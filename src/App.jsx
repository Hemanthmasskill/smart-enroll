import { Routes, Route } from "react-router-dom";
import Landing from "./pages/Landing/Landing";
import Login from "./pages/Auth/Login";
import Register from "./pages/Auth/Register";
import NotFound from "./pages/NotFound";
import ProtectedRoute from "./components/ProtectedRoute";
import ComingSoon from "./components/ComingSoon";
import "./App.css";

export default function App() {
  return (
    <div className="app-shell">
      <div className="app-main">
        <Routes>
          {/* Public */}
          <Route path="/" element={<Landing />} />
          <Route path="/login" element={<Login />} />
          <Route path="/register" element={<Register />} />

          {/* Applicant (protected — built in Increment 2 onward) */}
          <Route
            path="/dashboard"
            element={
              <ProtectedRoute allowedRole="user">
                <ComingSoon title="Applicant Dashboard" />
              </ProtectedRoute>
            }
          />
          <Route
            path="/application"
            element={
              <ProtectedRoute allowedRole="user">
                <ComingSoon title="Admission Application Form" />
              </ProtectedRoute>
            }
          />
          <Route
            path="/documents"
            element={
              <ProtectedRoute allowedRole="user">
                <ComingSoon title="Document Upload & Verification" />
              </ProtectedRoute>
            }
          />
          <Route
            path="/digilocker"
            element={
              <ProtectedRoute allowedRole="user">
                <ComingSoon title="DigiLocker Verification" />
              </ProtectedRoute>
            }
          />
          <Route
            path="/eligibility"
            element={
              <ProtectedRoute allowedRole="user">
                <ComingSoon title="Eligibility Status" />
              </ProtectedRoute>
            }
          />
          <Route
            path="/status"
            element={<ComingSoon title="Application Status" />}
          />
          <Route
            path="/notifications"
            element={
              <ProtectedRoute allowedRole="user">
                <ComingSoon title="Notifications" />
              </ProtectedRoute>
            }
          />
          <Route
            path="/profile"
            element={
              <ProtectedRoute allowedRole="user">
                <ComingSoon title="Applicant Profile" />
              </ProtectedRoute>
            }
          />

          {/* Admin (protected — built in later increments) */}
          <Route
            path="/admin"
            element={
              <ProtectedRoute allowedRole="admin">
                <ComingSoon title="Admin Dashboard" />
              </ProtectedRoute>
            }
          />
          <Route
            path="/admin/applications"
            element={
              <ProtectedRoute allowedRole="admin">
                <ComingSoon title="Applications Management" />
              </ProtectedRoute>
            }
          />
          <Route
            path="/admin/applications/:id"
            element={
              <ProtectedRoute allowedRole="admin">
                <ComingSoon title="Application Details" />
              </ProtectedRoute>
            }
          />
          <Route
            path="/admin/exceptions"
            element={
              <ProtectedRoute allowedRole="admin">
                <ComingSoon title="Exceptions Management" />
              </ProtectedRoute>
            }
          />
          <Route
            path="/admin/analytics"
            element={
              <ProtectedRoute allowedRole="admin">
                <ComingSoon title="Admission Analytics" />
              </ProtectedRoute>
            }
          />
          <Route
            path="/admin/programs"
            element={
              <ProtectedRoute allowedRole="admin">
                <ComingSoon title="Programme & Eligibility Rules" />
              </ProtectedRoute>
            }
          />
          <Route
            path="/admin/agent-activity"
            element={
              <ProtectedRoute allowedRole="admin">
                <ComingSoon title="Agent Activity Logs" />
              </ProtectedRoute>
            }
          />

          <Route path="*" element={<NotFound />} />
        </Routes>
      </div>
    </div>
  );
}
