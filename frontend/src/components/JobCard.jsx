import { useNavigate } from 'react-router-dom'
import ScoreBar from './ScoreBar'
import SkillBadge from './SkillBadge'
import { ArrowRight, Globe, Building2 } from 'lucide-react'

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

export default function JobCard({ result, rank, userIdOrJobId, mode = 'seeker' }) {
  const navigate = useNavigate()

  const handleExplore = () => {
    if (mode === 'seeker') {
      navigate(`/user/match/${result.job_id}`)
    } else {
      // Recruiter viewing candidates: navigate to user match from recruiter side
      navigate(`/user/match/${result.job_id}`, { state: { viewAs: result.user_id } })
    }
  }

  const title   = mode === 'seeker' ? result.job_title : result.user_id
  const subtitle = mode === 'seeker'
    ? [result.company, result.remote_policy].filter(Boolean).join(' · ')
    : `Match score`

  return (
    <div className="rounded-xl p-5 fade-in"
         style={{ background: '#16213e', border: '1px solid #0f3460' }}>
      {/* Header */}
      <div className="flex items-start justify-between gap-3 mb-4">
        <div className="flex items-center gap-3">
          {/* Rank circle */}
          <div className="w-9 h-9 rounded-full flex items-center justify-center text-sm font-bold flex-shrink-0"
               style={{ background: rank <= 3 ? '#e94560' : '#0f3460', color: '#fff' }}>
            {rank}
          </div>
          <div>
            <h3 className="font-semibold text-sm" style={{ color: '#e0e0e0' }}>{title}</h3>
            {subtitle && (
              <p className="text-xs mt-0.5" style={{ color: '#8892a4' }}>{subtitle}</p>
            )}
          </div>
        </div>
        <button
          onClick={handleExplore}
          className="flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs font-medium flex-shrink-0 transition-colors"
          style={{ background: '#e94560', color: '#fff' }}
          onMouseEnter={e => e.currentTarget.style.background = '#c73652'}
          onMouseLeave={e => e.currentTarget.style.background = '#e94560'}>
          Explore <ArrowRight size={12} />
        </button>
      </div>

      {/* Score bars */}
      <div className="space-y-2 mb-4">
        <ScoreBar label="Overall Match" score={result.total_score} large />
        <div className="grid grid-cols-2 gap-3 mt-2">
          <ScoreBar label="Skills (65%)" score={result.skill_score} />
          <ScoreBar label="Domain (35%)" score={result.domain_score} />
        </div>
      </div>

      {/* Bonus badges */}
      <div className="flex gap-2 mb-3 flex-wrap">
        <BonusBadge label="Culture fit"   value={result.culture_bonus} />
        <BonusBadge label="Preferences"   value={result.preference_bonus} />
      </div>

      {/* Skill badges */}
      <div className="space-y-2">
        {result.matched_skills?.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {result.matched_skills.slice(0, 6).map(s => (
              <SkillBadge key={s} label={s} variant="match" />
            ))}
            {result.matched_skills.length > 6 && (
              <SkillBadge label={`+${result.matched_skills.length - 6} more`} variant="neutral" />
            )}
          </div>
        )}
        {result.missing_skills?.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {result.missing_skills.slice(0, 4).map(s => (
              <SkillBadge key={s} label={s} variant="missing" />
            ))}
            {result.missing_skills.length > 4 && (
              <SkillBadge label={`+${result.missing_skills.length - 4} gaps`} variant="neutral" />
            )}
          </div>
        )}
      </div>

      {/* Explanation */}
      {result.explanation && (
        <p className="mt-3 text-xs italic" style={{ color: '#8892a4' }}>
          {result.explanation}
        </p>
      )}
    </div>
  )
}
