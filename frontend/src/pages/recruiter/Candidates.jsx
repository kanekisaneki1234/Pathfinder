import { useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { api } from '../../lib/api'
import Layout from '../../components/Layout'
import LoadingOverlay from '../../components/LoadingOverlay'
import ScoreBar from '../../components/ScoreBar'
import SkillBadge from '../../components/SkillBadge'
import { ArrowLeft, Users, ArrowRight, AlertCircle, Sparkles } from 'lucide-react'

function BonusBadge({ label, value }) {
  const pct = Math.round(value * 100)
  const color = value >= 0.7 ? '#27ae60' : value > 0 ? '#e67e22' : '#8892a4'
  return (
    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs"
          style={{ background: `${color}18`, color, border: `1px solid ${color}40` }}>
      {label}: {pct}%
    </span>
  )
}

function CandidateCard({ result, rank, jobId, navigate }) {
  return (
    <div className="rounded-xl p-5 fade-in"
         style={{ background: '#16213e', border: '1px solid #0f3460' }}>
      <div className="flex items-start justify-between gap-3 mb-4">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-full flex items-center justify-center text-sm font-bold flex-shrink-0"
               style={{ background: rank <= 3 ? '#e94560' : '#0f3460', color: '#fff' }}>
            {rank}
          </div>
          <div>
            <h3 className="font-semibold text-sm" style={{ color: '#e0e0e0' }}>
              {result.user_id}
            </h3>
            <p className="text-xs mt-0.5" style={{ color: '#8892a4' }}>Candidate</p>
          </div>
        </div>
        <button
          onClick={() => navigate(`/user/match/${jobId}`, { state: { viewAs: result.user_id } })}
          className="flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs font-medium flex-shrink-0"
          style={{ background: '#e94560', color: '#fff' }}
          onMouseEnter={e => e.currentTarget.style.background = '#c73652'}
          onMouseLeave={e => e.currentTarget.style.background = '#e94560'}>
          Explore <ArrowRight size={12} />
        </button>
      </div>

      <div className="space-y-2 mb-4">
        <ScoreBar label="Overall Match" score={result.total_score} large />
        <div className="grid grid-cols-2 gap-3 mt-2">
          <ScoreBar label="Skills (65%)"  score={result.skill_score} />
          <ScoreBar label="Domain (35%)"  score={result.domain_score} />
        </div>
      </div>

      <div className="flex gap-2 mb-3 flex-wrap">
        <BonusBadge label="Culture fit"  value={result.culture_bonus} />
        <BonusBadge label="Preferences"  value={result.preference_bonus} />
      </div>

      {result.matched_skills?.length > 0 && (
        <div className="flex flex-wrap gap-1 mb-1">
          {result.matched_skills.slice(0, 6).map(s => <SkillBadge key={s} label={s} variant="match" />)}
          {result.matched_skills.length > 6 && (
            <SkillBadge label={`+${result.matched_skills.length - 6} more`} variant="neutral" />
          )}
        </div>
      )}
      {result.missing_skills?.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {result.missing_skills.slice(0, 4).map(s => <SkillBadge key={s} label={s} variant="missing" />)}
        </div>
      )}

      {result.explanation && (
        <p className="mt-3 text-xs italic" style={{ color: '#8892a4' }}>{result.explanation}</p>
      )}
    </div>
  )
}

export default function Candidates() {
  const { jobId } = useParams()
  const navigate  = useNavigate()

  const [candidates, setCandidates] = useState(null)
  const [loading, setLoading]       = useState(false)
  const [error, setError]           = useState(null)

  async function handleFind() {
    setError(null)
    setLoading(true)
    try {
      const data = await api.getCandidates(jobId)
      setCandidates(data.results)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <Layout>
      {loading && <LoadingOverlay message="Finding matching candidates…" />}

      <div className="px-6 py-8">
        {/* Header */}
        <div className="flex items-center justify-between mb-8">
          <div className="flex items-center gap-4">
            <button
              onClick={() => navigate('/recruiter/post')}
              className="flex items-center gap-2 text-sm"
              style={{ color: '#8892a4' }}
              onMouseEnter={e => e.currentTarget.style.color = '#e0e0e0'}
              onMouseLeave={e => e.currentTarget.style.color = '#8892a4'}>
              <ArrowLeft size={16} />
            </button>
            <div>
              <h1 className="text-2xl font-bold" style={{ color: '#e0e0e0' }}>
                Candidates for {jobId}
              </h1>
              <p className="text-sm mt-1" style={{ color: '#8892a4' }}>
                {candidates
                  ? `${candidates.length} candidate${candidates.length !== 1 ? 's' : ''} ranked`
                  : 'Click to find matching candidates'}
              </p>
            </div>
          </div>

          <div className="flex gap-2">
            <button
              onClick={() => navigate(`/recruiter/model/${jobId}`)}
              className="flex items-center gap-2 px-4 py-2.5 rounded-xl text-sm font-medium"
              style={{ background: '#0f3460', color: '#e0e0e0' }}
              onMouseEnter={e => e.currentTarget.style.background = '#1a3a7a'}
              onMouseLeave={e => e.currentTarget.style.background = '#0f3460'}>
              View Job Model
            </button>
            <button
              onClick={handleFind}
              className="flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-semibold"
              style={{ background: '#e94560', color: '#fff' }}
              onMouseEnter={e => e.currentTarget.style.background = '#c73652'}
              onMouseLeave={e => e.currentTarget.style.background = '#e94560'}>
              <Sparkles size={16} /> Find Matching Candidates
            </button>
          </div>
        </div>

        {error && (
          <div className="flex items-center gap-2 px-4 py-3 rounded-xl mb-6"
               style={{ background: 'rgba(231,76,60,0.1)', border: '1px solid rgba(231,76,60,0.3)' }}>
            <AlertCircle size={16} color="#e74c3c" />
            <p className="text-sm" style={{ color: '#e74c3c' }}>{error}</p>
          </div>
        )}

        {candidates && (
          <div className="space-y-4">
            {candidates.length === 0 ? (
              <div className="text-center py-16">
                <Users size={40} className="mx-auto mb-3" color="#0f3460" />
                <p className="text-sm" style={{ color: '#8892a4' }}>No candidate profiles in the system yet.</p>
              </div>
            ) : (
              candidates.map((c, i) => (
                <CandidateCard key={c.user_id} result={c} rank={i + 1} jobId={jobId} navigate={navigate} />
              ))
            )}
          </div>
        )}

        {!candidates && !loading && (
          <div className="text-center py-20">
            <Users size={48} className="mx-auto mb-4" color="#0f3460" />
            <p className="text-sm mb-2" style={{ color: '#8892a4' }}>
              Click "Find Matching Candidates" to rank all profiles against this job.
            </p>
            <p className="text-xs" style={{ color: '#8892a4' }}>
              Each candidate is scored using skills (65%) and domain (35%) graph analysis.
            </p>
          </div>
        )}
      </div>
    </Layout>
  )
}
