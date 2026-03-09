import { useState, useEffect } from 'react'
import { useAuth } from '../../context/AuthContext'
import { api } from '../../lib/api'
import Layout from '../../components/Layout'
import LoadingOverlay from '../../components/LoadingOverlay'
import JobCard from '../../components/JobCard'
import { Sparkles, Briefcase, AlertCircle } from 'lucide-react'

function SimpleJobCard({ job }) {
  const remoteColor = {
    remote: '#27ae60',
    hybrid: '#e67e22',
    onsite: '#5dade2',
  }[job.remote_policy] || '#8892a4'

  return (
    <div className="rounded-xl p-4" style={{ background: '#16213e', border: '1px solid #0f3460' }}>
      <div className="flex items-start justify-between gap-2">
        <div>
          <h3 className="text-sm font-medium" style={{ color: '#e0e0e0' }}>{job.title || job.id}</h3>
          {job.company && (
            <p className="text-xs mt-0.5" style={{ color: '#8892a4' }}>{job.company}</p>
          )}
        </div>
        {job.remote_policy && (
          <span className="text-xs px-2 py-0.5 rounded-full flex-shrink-0"
                style={{ background: `${remoteColor}18`, color: remoteColor, border: `1px solid ${remoteColor}40` }}>
            {job.remote_policy}
          </span>
        )}
      </div>
    </div>
  )
}

export default function Dashboard() {
  const { session } = useAuth()
  const [jobs, setJobs]           = useState([])
  const [matches, setMatches]     = useState(null)
  const [loading, setLoading]     = useState(false)
  const [loadingMsg, setLoadMsg]  = useState('')
  const [error, setError]         = useState(null)

  useEffect(() => {
    api.listJobs()
       .then(data => setJobs(data))
       .catch(() => {})
  }, [])

  async function handleRecommend() {
    setError(null)
    setLoading(true)
    setLoadMsg('Computing your matches…')
    try {
      const data = await api.getMatches(session.userId)
      setMatches(data.results)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <Layout>
      {loading && <LoadingOverlay message={loadingMsg} />}

      <div className="px-6 py-8">
        {/* Header */}
        <div className="flex items-center justify-between mb-8">
          <div>
            <h1 className="text-2xl font-bold" style={{ color: '#e0e0e0' }}>
              Hello, {session.userId}
            </h1>
            <p className="text-sm mt-1" style={{ color: '#8892a4' }}>
              {matches
                ? `${matches.length} jobs ranked for you`
                : `${jobs.length} available position${jobs.length !== 1 ? 's' : ''}`}
            </p>
          </div>

          <button
            onClick={handleRecommend}
            className="flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-semibold transition-colors"
            style={{ background: '#e94560', color: '#fff' }}
            onMouseEnter={e => e.currentTarget.style.background = '#c73652'}
            onMouseLeave={e => e.currentTarget.style.background = '#e94560'}>
            <Sparkles size={16} /> Recommend Jobs
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

        {/* Matched results */}
        {matches && (
          <div className="space-y-4">
            <h2 className="text-sm font-semibold uppercase tracking-wider mb-3"
                style={{ color: '#8892a4' }}>
              Ranked Recommendations
            </h2>
            {matches.length === 0 ? (
              <p className="text-sm" style={{ color: '#8892a4' }}>No jobs found in the database yet.</p>
            ) : (
              matches.map((r, i) => (
                <JobCard key={r.job_id} result={r} rank={i + 1} userIdOrJobId={session.userId} mode="seeker" />
              ))
            )}
          </div>
        )}

        {/* Default job listing */}
        {!matches && (
          <div>
            <h2 className="text-sm font-semibold uppercase tracking-wider mb-3"
                style={{ color: '#8892a4' }}>
              Available Positions
            </h2>
            {jobs.length === 0 ? (
              <div className="text-center py-16">
                <Briefcase size={40} className="mx-auto mb-3" color="#0f3460" />
                <p className="text-sm" style={{ color: '#8892a4' }}>No jobs yet.</p>
              </div>
            ) : (
              <div className="grid grid-cols-2 gap-3">
                {jobs.map(j => <SimpleJobCard key={j.id} job={j} />)}
              </div>
            )}

            <p className="text-xs text-center mt-6" style={{ color: '#8892a4' }}>
              Click "Recommend Jobs" to see personalised matches ranked by your skill and domain profile.
            </p>
          </div>
        )}
      </div>
    </Layout>
  )
}
