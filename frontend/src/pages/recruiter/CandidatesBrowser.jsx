import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../../context/AuthContext'
import { api } from '../../lib/api'
import Layout from '../../components/Layout'
import { Users, Briefcase, RefreshCw, ArrowRight, AlertCircle } from 'lucide-react'

const remoteColor = {
  remote: '#27ae60',
  hybrid: '#e67e22',
  onsite: '#5dade2',
}

export default function CandidatesBrowser() {
  const { session } = useAuth()
  const navigate = useNavigate()

  const [jobs, setJobs]       = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError]     = useState(null)

  async function load() {
    setLoading(true)
    setError(null)
    try {
      const data = await api.listJobs(session.userId)
      setJobs(data)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  return (
    <Layout>
      <div className="px-6 py-8">

        {/* Header */}
        <div className="flex items-center justify-between mb-8">
          <div>
            <h1 className="text-2xl font-bold" style={{ color: '#e0e0e0' }}>Find Candidates</h1>
            <p className="text-sm mt-1" style={{ color: '#8892a4' }}>
              Select a job to rank matching candidate profiles
            </p>
          </div>
          <button
            onClick={load}
            disabled={loading}
            className="flex items-center gap-2 px-4 py-2 rounded-xl text-sm disabled:opacity-50"
            style={{ background: '#0f3460', color: '#8892a4' }}
            onMouseEnter={e => e.currentTarget.style.color = '#e0e0e0'}
            onMouseLeave={e => e.currentTarget.style.color = '#8892a4'}>
            <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
            Refresh
          </button>
        </div>

        {/* Error */}
        {error && (
          <div className="flex items-center gap-2 px-4 py-3 rounded-xl mb-6"
               style={{ background: 'rgba(231,76,60,0.1)', border: '1px solid rgba(231,76,60,0.3)' }}>
            <AlertCircle size={16} color="#e74c3c" />
            <p className="text-sm" style={{ color: '#e74c3c' }}>{error}</p>
          </div>
        )}

        {/* Loading */}
        {loading && !jobs && (
          <div className="text-center py-16 text-sm" style={{ color: '#8892a4' }}>Loading jobs…</div>
        )}

        {/* Empty state */}
        {jobs !== null && jobs.length === 0 && (
          <div className="text-center py-20">
            <Briefcase size={44} className="mx-auto mb-4" color="#0f3460" />
            <p className="text-sm mb-1" style={{ color: '#8892a4' }}>No jobs posted yet.</p>
            <p className="text-xs mb-4" style={{ color: '#8892a4' }}>
              Post a job first, then come back here to find matching candidates.
            </p>
            <button
              onClick={() => navigate('/recruiter/post')}
              className="px-4 py-2 rounded-lg text-sm font-semibold"
              style={{ background: '#e94560', color: '#fff' }}
              onMouseEnter={e => e.currentTarget.style.background = '#c73652'}
              onMouseLeave={e => e.currentTarget.style.background = '#e94560'}>
              Post a Job →
            </button>
          </div>
        )}

        {/* Job grid */}
        {jobs !== null && jobs.length > 0 && (
          <>
            <p className="text-xs mb-4" style={{ color: '#8892a4' }}>
              {jobs.length} job{jobs.length !== 1 ? 's' : ''} available — click one to rank candidates
            </p>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
              {jobs.map(job => {
                const rc = remoteColor[job.remote_policy] || '#8892a4'
                return (
                  <button
                    key={job.id}
                    onClick={() => navigate(`/recruiter/candidates/${job.id}`)}
                    className="rounded-xl p-5 text-left transition-all group"
                    style={{ background: '#16213e', border: '1px solid #0f3460' }}
                    onMouseEnter={e => e.currentTarget.style.borderColor = '#e94560'}
                    onMouseLeave={e => e.currentTarget.style.borderColor = '#0f3460'}>

                    <div className="flex items-start justify-between gap-2 mb-3">
                      <div className="w-9 h-9 rounded-lg flex items-center justify-center flex-shrink-0"
                           style={{ background: '#0f3460' }}>
                        <Briefcase size={16} color="#8892a4" />
                      </div>
                      {job.remote_policy && (
                        <span className="text-xs px-2 py-0.5 rounded-full flex-shrink-0"
                              style={{ background: `${rc}18`, color: rc, border: `1px solid ${rc}40` }}>
                          {job.remote_policy}
                        </span>
                      )}
                    </div>

                    <p className="text-sm font-semibold mb-0.5 truncate" style={{ color: '#e0e0e0' }}>
                      {job.title || job.id}
                    </p>
                    {job.company && (
                      <p className="text-xs truncate mb-3" style={{ color: '#8892a4' }}>{job.company}</p>
                    )}

                    <div className="flex items-center gap-1 text-xs"
                         style={{ color: '#8892a4' }}>
                      <Users size={12} />
                      <span>Find candidates</span>
                      <ArrowRight size={11} className="ml-auto opacity-0 group-hover:opacity-100 transition-opacity"
                                  color="#e94560" />
                    </div>
                  </button>
                )
              })}
            </div>
          </>
        )}

      </div>
    </Layout>
  )
}
