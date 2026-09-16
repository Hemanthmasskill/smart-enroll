import { Routes, Route } from "react-router-dom";
import Landing from "./pages/Landing/Landing";
import Login from "./pages/Auth/Login";
import Register from "./pages/Auth/Register";
import NotFound from "./pages/NotFound";
import ProtectedRoute from "./components/ProtectedRoute";
import ComingSoon from "./components/ComingSoon";
import ApplicantLayout from "./layouts/ApplicantLayout";
import AdminLayout from "./layouts/AdminLayout";
import Dashboard from "./pages/Applicant/Dashboard";
import ApplicationForm from "./pages/Applicant/ApplicationForm";
import Documents from "./pages/Applicant/Documents";
import DigiLocker from "./pages/Applicant/DigiLocker";
import Eligibility from "./pages/Applicant/Eligibility";
import ApplicationStatus from "./pages/Applicant/ApplicationStatus";
import Notifications from "./pages/Applicant/Notifications";
import Profile from "./pages/Applicant/Profile";
import AdminDashboard from "./pages/Admin/AdminDashboard";
import Applications from "./pages/Admin/Applications";
import ApplicationDetails from "./pages/Admin/ApplicationDetails";
import Exceptions from "./pages/Admin/Exceptions";
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
                  <Eligibility />
                </ApplicantLayout>
              </ProtectedRoute>
            }
          />
          <Route
            path="/status"
            element={
              <ProtectedRoute allowedRole="user">
                <ApplicantLayout>
                  <ApplicationStatus />
                </ApplicantLayout>
              </ProtectedRoute>
            }
          />
          <Route
            path="/notifications"
            element={
              <ProtectedRoute allowedRole="user">
                <ApplicantLayout>
                  <Notifications />
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

          {/* Admin (protected) */}
          <Route path="/admin" element={<ProtectedRoute allowedRole="admin"><AdminLayout><AdminDashboard /></AdminLayout></ProtectedRoute>} />
          <Route path="/admin/applications" element={<ProtectedRoute allowedRole="admin"><AdminLayout><Applications /></AdminLayout></ProtectedRoute>} />
          <Route path="/admin/applications/:id" element={<ProtectedRoute allowedRole="admin"><AdminLayout><ApplicationDetails /></AdminLayout></ProtectedRoute>} />
          <Route path="/admin/exceptions" element={<ProtectedRoute allowedRole="admin"><AdminLayout><Exceptions /></AdminLayout></ProtectedRoute>} />
          <Route path="/admin/analytics" element={<ProtectedRoute allowedRole="admin"><AdminLayout><ComingSoon title="Admission Analytics" /></AdminLayout></ProtectedRoute>} />
          <Route path="/admin/programs" element={<ProtectedRoute allowedRole="admin"><AdminLayout><ComingSoon title="Programme & Eligibility Rules" /></AdminLayout></ProtectedRoute>} />
          <Route path="/admin/agent-activity" element={<ProtectedRoute allowedRole="admin"><AdminLayout><ComingSoon title="Agent Activity Logs" /></AdminLayout></ProtectedRoute>} />

          <Route path="*" element={<NotFound />} />
        </Routes>
      </div>
    </div>
  );
}
