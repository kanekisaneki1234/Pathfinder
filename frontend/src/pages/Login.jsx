import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { Network, Briefcase, User, Shield } from 'lucide-react'

export default function Login() {
  const [role, setRole]     = useState(null)
  const [userId, setUserId] = useState('')
  const [error, setError]   = useState('')
  const { login }           = useAuth()
  const navigate            = useNavigate()

  function handleEnter() {
    const id = userId.trim()
    if (!role)  return setError('Please select a role.')
    if (!id)    return setError('Please enter your ID.')
    if (!/^[a-zA-Z0-9_-]+$/.test(id)) return setError('ID may only contain letters, numbers, _ and -')
    login(id, role)
    navigate(role === 'recruiter' ? '/recruiter/post' : role === 'admin' ? '/admin' : '/user/upload')
  }

  const RoleCard = ({ value, icon: Icon, title, desc }) => (
    <button
      onClick={() => { setRole(value); setError('') }}
      className="flex-1 rounded-xl p-6 text-left transition-all"
      style={{
        background: role === value ? 'rgba(233,69,96,0.1)' : '#16213e',
        border: role === value ? '2px solid #e94560' : '2px solid #0f3460',
      }}>
      <div className="w-12 h-12 rounded-xl flex items-center justify-center mb-3"
           style={{ background: role === value ? '#e94560' : '#0f3460' }}>
        <Icon size={22} color="white" />
      </div>
      <h3 className="font-semibold mb-1" style={{ color: '#e0e0e0' }}>{title}</h3>
      <p className="text-sm" style={{ color: '#8892a4' }}>{desc}</p>
    </button>
  )

  return (
    <div className="min-h-screen flex items-center justify-center px-4"
         style={{ background: '#1a1a2e' }}>
      <div className="w-full max-w-md">
        {/* Logo */}
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center w-14 h-14 rounded-2xl mb-4"
               style={{ background: '#e94560' }}>
            <Network size={28} color="white" />
          </div>
          <h1 className="text-2xl font-bold" style={{ color: '#e0e0e0' }}>Adaptive Matching</h1>
          <p className="text-sm mt-1" style={{ color: '#8892a4' }}>Graph-based transparent job matching</p>
        </div>

        <div className="rounded-2xl p-8" style={{ background: '#16213e', border: '1px solid #0f3460' }}>
          <h2 className="text-lg font-semibold mb-5" style={{ color: '#e0e0e0' }}>
            Select your role
          </h2>

          {/* Role selection */}
          <div className="flex gap-3 mb-3">
            <RoleCard value="seeker"    icon={User}     title="Job Seeker"   desc="Upload your resume and find matching jobs." />
            <RoleCard value="recruiter" icon={Briefcase} title="Recruiter"    desc="Post jobs and find matching candidates." />
          </div>
          <div className="mb-6">
            <button
              onClick={() => { setRole('admin'); setError('') }}
              className="w-full rounded-xl px-4 py-3 text-left flex items-center gap-3 transition-all"
              style={{
                background: role === 'admin' ? 'rgba(233,69,96,0.08)' : 'transparent',
                border: role === 'admin' ? '1px solid #e94560' : '1px solid #0f3460',
              }}>
              <div className="w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0"
                   style={{ background: role === 'admin' ? '#e94560' : '#0f3460' }}>
                <Shield size={16} color="white" />
              </div>
              <div>
                <p className="text-sm font-medium" style={{ color: '#e0e0e0' }}>Admin</p>
                <p className="text-xs" style={{ color: '#8892a4' }}>Manage users and jobs in the system.</p>
              </div>
            </button>
          </div>

          {/* User ID */}
          <div className="mb-4">
            <label className="block text-sm font-medium mb-2" style={{ color: '#8892a4' }}>
              Your ID (e.g. alice, rec-001)
            </label>
            <input
              type="text"
              value={userId}
              onChange={e => { setUserId(e.target.value); setError('') }}
              onKeyDown={e => e.key === 'Enter' && handleEnter()}
              placeholder="Enter your ID..."
              className="w-full px-4 py-3 rounded-lg text-sm outline-none transition-colors"
              style={{
                background: '#1a1a2e',
                border: '1px solid #0f3460',
                color: '#e0e0e0',
              }}
              onFocus={e => e.target.style.borderColor = '#e94560'}
              onBlur={e => e.target.style.borderColor = '#0f3460'}
            />
          </div>

          {error && (
            <p className="text-xs mb-3" style={{ color: '#e74c3c' }}>{error}</p>
          )}

          <button
            onClick={handleEnter}
            className="w-full py-3 rounded-lg font-semibold text-sm transition-colors"
            style={{ background: '#e94560', color: '#fff' }}
            onMouseEnter={e => e.currentTarget.style.background = '#c73652'}
            onMouseLeave={e => e.currentTarget.style.background = '#e94560'}>
            Enter Portal →
          </button>
        </div>
      </div>
    </div>
  )
}
