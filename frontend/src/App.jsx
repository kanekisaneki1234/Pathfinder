import { Routes, Route, Navigate } from 'react-router-dom'
import Login from './pages/Login'
import Upload from './pages/user/Upload'
import Guidelines from './pages/user/Guidelines'
import UserModel from './pages/user/UserModel'
import Dashboard from './pages/user/Dashboard'
import MatchExplorer from './pages/user/MatchExplorer'
import PostJob from './pages/recruiter/PostJob'
import JobModel from './pages/recruiter/JobModel'
import CandidatesBrowser from './pages/recruiter/CandidatesBrowser'
import Candidates from './pages/recruiter/Candidates'
import AdminDashboard from './pages/admin/AdminDashboard'
import ProtectedRoute from './components/ProtectedRoute'

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />

      {/* Job Seeker routes */}
      <Route path="/user/upload"        element={<ProtectedRoute role="seeker"><Upload /></ProtectedRoute>} />
      <Route path="/user/guidelines"    element={<ProtectedRoute role="seeker"><Guidelines /></ProtectedRoute>} />
      <Route path="/user/model"         element={<ProtectedRoute role="seeker"><UserModel /></ProtectedRoute>} />
      <Route path="/user/dashboard"     element={<ProtectedRoute role="seeker"><Dashboard /></ProtectedRoute>} />
      <Route path="/user/match/:jobId"  element={<ProtectedRoute role={['seeker', 'recruiter']}><MatchExplorer /></ProtectedRoute>} />

      {/* Recruiter routes — parameterless path BEFORE parameterized */}
      <Route path="/recruiter/post"               element={<ProtectedRoute role="recruiter"><PostJob /></ProtectedRoute>} />
      <Route path="/recruiter/model/:jobId"        element={<ProtectedRoute role="recruiter"><JobModel /></ProtectedRoute>} />
      <Route path="/recruiter/candidates"          element={<ProtectedRoute role="recruiter"><CandidatesBrowser /></ProtectedRoute>} />
      <Route path="/recruiter/candidates/:jobId"   element={<ProtectedRoute role="recruiter"><Candidates /></ProtectedRoute>} />

      {/* Admin routes */}
      <Route path="/admin" element={<ProtectedRoute role="admin"><AdminDashboard /></ProtectedRoute>} />

      {/* Default redirect */}
      <Route path="*" element={<Navigate to="/login" replace />} />
    </Routes>
  )
}
