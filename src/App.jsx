import { Routes, Route } from "react-router-dom";
import Landing from "./pages/Landing/Landing";
import Login from "./pages/Auth/Login";
import Register from "./pages/Auth/Register";
import NotFound from "./pages/NotFound";
import ProtectedRoute from "./components/ProtectedRoute";
import ComingSoon from "./components/ComingSoon";
import ApplicantLayout from "./layouts/ApplicantLayout";
import Dashboard from "./pages/Applicant/Dashboard";
import ApplicationForm from "./pages/Applicant/ApplicationForm";
import Documents from "./pages/Applicant/Documents";
import DigiLocker from "./pages/Applicant/DigiLocker";
import Profile from "./pages/Applicant/Profile";
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

          {/* Applicant (protected) */}
          <Route
            path="/dashboard"
            element={
              <ProtectedRoute allowedRole="user">
                <ApplicantLayout>
                  <Dashboard />
                </ApplicantLayout>
              </ProtectedRoute>
            }
          />
          <Route
            path="/application"
            element={
              <ProtectedRoute allowedRole="user">
                <ApplicantLayout>
                  <ApplicationForm />
                </ApplicantLayout>
              </ProtectedRoute>
            }
          />
          <Route
            path="/documents"
            element={
              <ProtectedRoute allowedRole="user">
                <ApplicantLayout>
                  <Documents />
                </ApplicantLayout>
              </ProtectedRoute>
            }
          />
          <Route
            path="/digilocker"
            element={
              <ProtectedRoute allowedRole="user">
                <ApplicantLayout>
                  <DigiLocker />
                </ApplicantLayout>
              </ProtectedRoute>
            }
          />
          <Route
            path="/eligibility"
            element={
              <ProtectedRoute allowedRole="user">
                <ApplicantLayout>
                  <ComingSoon title="Eligibility Status" />
                </ApplicantLayout>
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
                <ApplicantLayout>
                  <ComingSoon title="Notifications" />
                </ApplicantLayout>
              </ProtectedRoute>
            }
          />
          <Route
            path="/profile"
            element={
              <ProtectedRoute allowedRole="user">
                <ApplicantLayout>
                  <Profile />
                </ApplicantLayout>
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
