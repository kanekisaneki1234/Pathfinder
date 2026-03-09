import { useState, useEffect, useCallback } from 'react'
import { api } from '../../lib/api'
import Layout from '../../components/Layout'
import { Users, Briefcase, Trash2, AlertTriangle, RefreshCw } from 'lucide-react'

function DeleteButton({ onConfirm, disabled }) {
  const [confirming, setConfirming] = useState(false)

  if (confirming) {
    return (
      <span className="flex items-center gap-1">
        <button
          onClick={() => { setConfirming(false); onConfirm() }}
          disabled={disabled}
          className="px-2 py-1 rounded text-xs font-semibold"
          style={{ background: '#e74c3c', color: '#fff' }}>
          Confirm
        </button>
        <button
          onClick={() => setConfirming(false)}
          className="px-2 py-1 rounded text-xs"
          style={{ color: '#8892a4' }}>
          Cancel
        </button>
      </span>
    )
  }

  return (
    <button
      onClick={() => setConfirming(true)}
      disabled={disabled}
      className="flex items-center gap-1 px-2 py-1 rounded text-xs"
      style={{ color: '#e74c3c' }}
      onMouseEnter={e => e.currentTarget.style.background = 'rgba(231,76,60,0.1)'}
      onMouseLeave={e => e.currentTarget.style.background = 'transparent'}>
      <Trash2 size={13} />
      Delete
    </button>
  )
}

function UserRow({ user, onDeleted }) {
  const [deleting, setDeleting] = useState(false)
  const [error, setError]       = useState(null)

  async function handleDelete() {
    setDeleting(true)
    setError(null)
    try {
      await api.deleteUser(user.id)
      onDeleted(user.id)
    } catch (e) {
      setError(e.message)
      setDeleting(false)
    }
  }

  return (
    <div className="flex items-center justify-between px-4 py-3 rounded-lg"
         style={{ background: '#16213e', border: '1px solid #0f3460' }}>
      <div className="flex items-center gap-3">
        <div className="w-8 h-8 rounded-full flex items-center justify-center text-sm font-bold flex-shrink-0"
             style={{ background: '#0f3460', color: '#e94560' }}>
          {user.id[0]?.toUpperCase()}
        </div>
        <span className="text-sm font-medium" style={{ color: '#e0e0e0' }}>{user.id}</span>
      </div>
      <div className="flex items-center gap-3">
        {error && <span className="text-xs" style={{ color: '#e74c3c' }}>{error}</span>}
        <DeleteButton onConfirm={handleDelete} disabled={deleting} />
      </div>
    </div>
  )
}

function JobRow({ job, onDeleted }) {
  const [deleting, setDeleting] = useState(false)
  const [error, setError]       = useState(null)

  const remoteColor = {
    remote: '#27ae60',
    hybrid: '#e67e22',
    onsite: '#5dade2',
  }[job.remote_policy] || '#8892a4'

  async function handleDelete() {
    setDeleting(true)
    setError(null)
    try {
      await api.deleteJob(job.id)
      onDeleted(job.id)
    } catch (e) {
      setError(e.message)
      setDeleting(false)
    }
  }

  return (
    <div className="flex items-center justify-between px-4 py-3 rounded-lg"
         style={{ background: '#16213e', border: '1px solid #0f3460' }}>
      <div className="flex items-center gap-3 min-w-0">
        <div className="w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0"
             style={{ background: '#0f3460' }}>
          <Briefcase size={14} color="#8892a4" />
        </div>
        <div className="min-w-0">
          <p className="text-sm font-medium truncate" style={{ color: '#e0e0e0' }}>
            {job.title || job.id}
          </p>
          {job.company && (
            <p className="text-xs truncate" style={{ color: '#8892a4' }}>{job.company}</p>
          )}
        </div>
        {job.remote_policy && (
          <span className="text-xs px-2 py-0.5 rounded-full flex-shrink-0 ml-2"
                style={{ background: `${remoteColor}18`, color: remoteColor, border: `1px solid ${remoteColor}40` }}>
            {job.remote_policy}
          </span>
        )}
      </div>
      <div className="flex items-center gap-3 flex-shrink-0 ml-3">
        {error && <span className="text-xs" style={{ color: '#e74c3c' }}>{error}</span>}
        <DeleteButton onConfirm={handleDelete} disabled={deleting} />
      </div>
    </div>
  )
}

export default function AdminDashboard() {
  const [tab, setTab]       = useState('users')
  const [users, setUsers]   = useState(null)
  const [jobs, setJobs]     = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError]   = useState(null)

  const loadUsers = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await api.listUsers()
      setUsers(data)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [])

  const loadJobs = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await api.listJobs()
      setJobs(data)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    if (tab === 'users' && users === null) loadUsers()
    if (tab === 'jobs'  && jobs  === null) loadJobs()
  }, [tab, users, jobs, loadUsers, loadJobs])

  function handleUserDeleted(id) {
    setUsers(prev => prev.filter(u => u.id !== id))
  }

  function handleJobDeleted(id) {
    setJobs(prev => prev.filter(j => j.id !== id))
  }

  const tabStyle = (t) => ({
    padding: '8px 20px',
    borderRadius: 8,
    fontSize: 13,
    fontWeight: 500,
    cursor: 'pointer',
    background: tab === t ? '#e94560' : 'transparent',
    color: tab === t ? '#fff' : '#8892a4',
    border: 'none',
  })

  return (
    <Layout>
      <div className="px-6 py-8">
        {/* Header */}
        <div className="flex items-center justify-between mb-8">
          <div>
            <h1 className="text-2xl font-bold" style={{ color: '#e0e0e0' }}>Admin Dashboard</h1>
            <p className="text-sm mt-1" style={{ color: '#8892a4' }}>
              Manage users and jobs in the system
            </p>
          </div>
          <button
            onClick={() => { tab === 'users' ? loadUsers() : loadJobs() }}
            disabled={loading}
            className="flex items-center gap-2 px-4 py-2 rounded-xl text-sm disabled:opacity-50"
            style={{ background: '#0f3460', color: '#8892a4' }}
            onMouseEnter={e => e.currentTarget.style.color = '#e0e0e0'}
            onMouseLeave={e => e.currentTarget.style.color = '#8892a4'}>
            <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
            Refresh
          </button>
        </div>

        {/* Tabs */}
        <div className="flex gap-1 p-1 rounded-xl mb-6 inline-flex"
             style={{ background: '#16213e', border: '1px solid #0f3460' }}>
          <button style={tabStyle('users')} onClick={() => setTab('users')}>
            <span className="flex items-center gap-1.5">
              <Users size={14} /> Users {users !== null && `(${users.length})`}
            </span>
          </button>
          <button style={tabStyle('jobs')} onClick={() => setTab('jobs')}>
            <span className="flex items-center gap-1.5">
              <Briefcase size={14} /> Jobs {jobs !== null && `(${jobs.length})`}
            </span>
          </button>
        </div>

        {/* Warning banner */}
        <div className="flex items-start gap-2 px-4 py-3 rounded-xl mb-6"
             style={{ background: 'rgba(231,76,60,0.06)', border: '1px solid rgba(231,76,60,0.2)' }}>
          <AlertTriangle size={15} color="#e74c3c" className="flex-shrink-0 mt-0.5" />
          <p className="text-xs" style={{ color: '#e0a0a0' }}>
            Deletion is permanent and cannot be undone. All associated graph data, match edges,
            and cached visualizations will be removed.
          </p>
        </div>

        {/* Error */}
        {error && (
          <div className="px-4 py-3 rounded-xl mb-4 text-sm" style={{ color: '#e74c3c', background: 'rgba(231,76,60,0.1)' }}>
            {error}
          </div>
        )}

        {/* Content */}
        {loading && !users && !jobs && (
          <div className="text-center py-16 text-sm" style={{ color: '#8892a4' }}>Loading…</div>
        )}

        {tab === 'users' && users !== null && (
          <div className="space-y-2">
            {users.length === 0 ? (
              <div className="text-center py-16">
                <Users size={40} className="mx-auto mb-3" color="#0f3460" />
                <p className="text-sm" style={{ color: '#8892a4' }}>No users in the system.</p>
              </div>
            ) : (
              users.map(u => (
                <UserRow key={u.id} user={u} onDeleted={handleUserDeleted} />
              ))
            )}
          </div>
        )}

        {tab === 'jobs' && jobs !== null && (
          <div className="space-y-2">
            {jobs.length === 0 ? (
              <div className="text-center py-16">
                <Briefcase size={40} className="mx-auto mb-3" color="#0f3460" />
                <p className="text-sm" style={{ color: '#8892a4' }}>No jobs in the system.</p>
              </div>
            ) : (
              jobs.map(j => (
                <JobRow key={j.id} job={j} onDeleted={handleJobDeleted} />
              ))
            )}
          </div>
        )}
      </div>
    </Layout>
  )
}
