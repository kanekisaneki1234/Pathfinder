import { Navigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'

export default function ProtectedRoute({ children, role }) {
  const { session } = useAuth()

  if (!session) return <Navigate to="/login" replace />
  const allowed = Array.isArray(role) ? role : [role]
  if (role && !allowed.includes(session.role)) {
    const redirect =
      session.role === 'recruiter' ? '/recruiter/post'
      : session.role === 'admin'   ? '/admin'
      : '/user/upload'
    return <Navigate to={redirect} replace />
  }

  return children
}
