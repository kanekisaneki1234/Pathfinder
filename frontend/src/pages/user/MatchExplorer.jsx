import { useState, useEffect } from 'react'
import { useParams, useNavigate, useLocation } from 'react-router-dom'
import { useAuth } from '../../context/AuthContext'
import { api } from '../../lib/api'
import Layout from '../../components/Layout'
import GraphViewer from '../../components/GraphViewer'
import ScoreBar from '../../components/ScoreBar'
import SkillBadge from '../../components/SkillBadge'
import { ArrowLeft, ChevronDown, ChevronRight, Sparkles } from 'lucide-react'

function BonusIndicator({ label, value }) {
  const pct = Math.round(value * 100)
  const color = value >= 0.7 ? '#27ae60' : value > 0 ? '#e67e22' : '#8892a4'
  return (
    <div className="flex items-center justify-between py-2 border-b"
         style={{ borderColor: '#0f3460' }}>
      <span className="text-xs" style={{ color: '#8892a4' }}>{label}</span>
      <span className="text-xs font-semibold" style={{ color }}>{pct}%</span>
    </div>
  )
}

function PathItem({ path, index }) {
  const segments = path.path.split(' → ')
  return (
    <div className="rounded-lg p-3 mb-2" style={{ background: '#16213e' }}>
      <p className="text-xs font-medium mb-1" style={{ color: '#8892a4' }}>Path {index + 1}</p>
      <div className="flex flex-wrap gap-1 items-center">
        {segments.map((seg, i) => (
          <span key={i} className="flex items-center gap-1">
            <span className="px-2 py-0.5 rounded text-xs"
                  style={{ background: '#0f3460', color: '#e0e0e0' }}>
              {seg}
            </span>
            {i < segments.length - 1 && (
              <ChevronRight size={10} color="#8892a4" />
            )}
          </span>
        ))}
      </div>
    </div>
  )
}

export default function MatchExplorer() {
  const { jobId }      = useParams()
  const { session }    = useAuth()
  const navigate       = useNavigate()
  const location       = useLocation()

  // When a recruiter clicks "Explore" on a candidate, viewAs is set to that candidate's userId
  const viewAs  = location.state?.viewAs || null
  const userId  = viewAs || session.userId
  const isProxy = !!viewAs  // recruiter viewing on behalf of a candidate

  const [detail, setDetail]           = useState(null)
  const [paths, setPaths]             = useState([])
  const [pathsOpen, setPathsOpen]     = useState(true)
  const [loading, setLoading]         = useState(true)
  const [error, setError]             = useState(null)
  const [explanation, setExplanation] = useState(null)
  const [explaining, setExplaining]   = useState(false)
  const [explainError, setExplainError] = useState(null)

  useEffect(() => {
    async function load() {
      setLoading(true)
      try {
        const [d, p] = await Promise.all([
          api.getMatchDetail(userId, jobId),
          api.getMatchPaths(userId, jobId, 20),
        ])
        setDetail(d)
        setPaths(p.paths || [])
      } catch (err) {
        setError(err.message)
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [jobId, userId])

  async function handleExplain() {
    setExplaining(true)
    setExplainError(null)
    try {
      const res = await api.explainMatch(userId, jobId)
      setExplanation(res.explanation)
    } catch (e) {
      setExplainError(e.message)
    } finally {
      setExplaining(false)
    }
  }

  const iframeSrc = api.matchVizUrl(userId, jobId)

  return (
    <Layout>
      <div className="flex flex-col h-full overflow-hidden">
        {/* Topbar */}
        <div className="flex items-center gap-4 px-6 py-4 border-b flex-shrink-0"
             style={{ background: '#16213e', borderColor: '#0f3460' }}>
          <button
            onClick={() => navigate(isProxy ? `/recruiter/candidates/${jobId}` : '/user/dashboard')}
            className="flex items-center gap-2 text-sm"
            style={{ color: '#8892a4' }}
            onMouseEnter={e => e.currentTarget.style.color = '#e0e0e0'}
            onMouseLeave={e => e.currentTarget.style.color = '#8892a4'}>
            <ArrowLeft size={16} /> {isProxy ? 'Candidates' : 'Dashboard'}
          </button>
          <div className="flex-1">
            <h1 className="text-base font-semibold" style={{ color: '#e0e0e0' }}>
              {loading ? 'Loading match…' : detail ? `${detail.job_title}` : `Job ${jobId}`}
            </h1>
            {detail?.company && (
              <p className="text-xs" style={{ color: '#8892a4' }}>{detail.company}</p>
            )}
          </div>
          {detail && (
            <div className="text-right">
              <p className="text-2xl font-bold" style={{ color: detail.total_score >= 0.7 ? '#27ae60' : detail.total_score >= 0.4 ? '#e67e22' : '#e74c3c' }}>
                {Math.round(detail.total_score * 100)}%
              </p>
              <p className="text-xs" style={{ color: '#8892a4' }}>match</p>
            </div>
          )}
        </div>

        {error && (
          <div className="m-4 px-4 py-3 rounded-xl text-sm" style={{ background: 'rgba(231,76,60,0.1)', color: '#e74c3c' }}>
            {error}
          </div>
        )}

        {/* Two-panel layout */}
        <div className="flex flex-1 overflow-hidden">
          {/* Left panel — Score breakdown + paths */}
          <div className="w-96 flex-shrink-0 overflow-y-auto p-5 border-r"
               style={{ borderColor: '#0f3460' }}>
            {detail && (
              <>
                {/* Score bars */}
                <div className="space-y-3 mb-6">
                  <ScoreBar label="Overall Match" score={detail.total_score} large />
                  <ScoreBar label="Skills (65%)"  score={detail.skill_score} />
                  <ScoreBar label="Domain (35%)"  score={detail.domain_score} />
                </div>

                {/* Bonus indicators */}
                <div className="mb-6">
                  <BonusIndicator label="Culture fit"  value={detail.culture_bonus} />
                  <BonusIndicator label="Preferences"  value={detail.preference_bonus} />
                </div>

                {/* Matched skills */}
                {detail.matched_skills?.length > 0 && (
                  <div className="mb-4">
                    <p className="text-xs font-semibold uppercase tracking-wider mb-2"
                       style={{ color: '#27ae60' }}>
                      Matched Skills ({detail.matched_skills.length})
                    </p>
                    <div className="flex flex-wrap gap-1.5">
                      {detail.matched_skills.map(s => <SkillBadge key={s} label={s} variant="match" />)}
                    </div>
                  </div>
                )}

                {/* Missing skills */}
                {detail.missing_skills?.length > 0 && (
                  <div className="mb-4">
                    <p className="text-xs font-semibold uppercase tracking-wider mb-2"
                       style={{ color: '#e67e22' }}>
                      Skill Gaps ({detail.missing_skills.length})
                    </p>
                    <div className="flex flex-wrap gap-1.5">
                      {detail.missing_skills.map(s => <SkillBadge key={s} label={s} variant="missing" />)}
                    </div>
                  </div>
                )}

                {/* Matched domains */}
                {detail.matched_domains?.length > 0 && (
                  <div className="mb-4">
                    <p className="text-xs font-semibold uppercase tracking-wider mb-2"
                       style={{ color: '#27ae60' }}>
                      Domain Match
                    </p>
                    <div className="flex flex-wrap gap-1.5">
                      {detail.matched_domains.map(d => <SkillBadge key={d} label={d} variant="match" />)}
                    </div>
                  </div>
                )}

                {/* Missing domains */}
                {detail.missing_domains?.length > 0 && (
                  <div className="mb-4">
                    <p className="text-xs font-semibold uppercase tracking-wider mb-2"
                       style={{ color: '#e67e22' }}>
                      Domain Gaps
                    </p>
                    <div className="flex flex-wrap gap-1.5">
                      {detail.missing_domains.map(d => <SkillBadge key={d} label={d} variant="missing" />)}
                    </div>
                  </div>
                )}

                {/* AI Explanation */}
                <div className="mb-6">
                  <div className="flex items-center justify-between mb-2">
                    <p className="text-xs font-semibold uppercase tracking-wider flex items-center gap-1"
                       style={{ color: '#5dade2' }}>
                      <Sparkles size={12} /> AI Explanation
                    </p>
                    {!explanation && !explaining && (
                      <button
                        onClick={handleExplain}
                        className="text-xs px-2 py-0.5 rounded transition-colors"
                        style={{ background: '#0f3460', color: '#5dade2' }}
                        onMouseEnter={e => e.currentTarget.style.background = '#1a4a80'}
                        onMouseLeave={e => e.currentTarget.style.background = '#0f3460'}>
                        Generate
                      </button>
                    )}
                  </div>
                  {explaining && (
                    <p className="text-xs" style={{ color: '#8892a4' }}>Generating…</p>
                  )}
                  {explanation && (
                    <p className="text-xs leading-relaxed" style={{ color: '#c8d0db' }}>
                      {explanation}
                    </p>
                  )}
                  {explainError && (
                    <p className="text-xs" style={{ color: '#e74c3c' }}>{explainError}</p>
                  )}
                </div>
              </>
            )}

            {/* Graph paths */}
            {paths.length > 0 && (
              <div>
                <button
                  onClick={() => setPathsOpen(o => !o)}
                  className="flex items-center justify-between w-full mb-2">
                  <p className="text-xs font-semibold uppercase tracking-wider"
                     style={{ color: '#5dade2' }}>
                    Graph Paths ({paths.length})
                  </p>
                  {pathsOpen ? <ChevronDown size={14} color="#5dade2" /> : <ChevronRight size={14} color="#5dade2" />}
                </button>
                {pathsOpen && paths.map((p, i) => <PathItem key={i} path={p} index={i} />)}
              </div>
            )}
          </div>

          {/* Right panel — Match graph */}
          <div className="flex-1 p-4">
            <GraphViewer
              generateFn={() => api.generateMatchViz(userId, jobId)}
              iframeSrc={iframeSrc}
              height="100%"
            />
          </div>
        </div>
      </div>
    </Layout>
  )
}
