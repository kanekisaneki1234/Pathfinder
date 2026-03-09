function scoreColor(score) {
  if (score >= 0.7) return '#27ae60'
  if (score >= 0.4) return '#e67e22'
  return '#e74c3c'
}

export default function ScoreBar({ label, score, large = false }) {
  const pct = Math.round(score * 100)
  const color = scoreColor(score)
  const height = large ? 'h-4' : 'h-2'

  return (
    <div className="w-full">
      <div className="flex justify-between items-center mb-1">
        <span className={`${large ? 'text-sm font-semibold' : 'text-xs'}`}
              style={{ color: '#8892a4' }}>
          {label}
        </span>
        <span className={`font-bold tabular-nums ${large ? 'text-base' : 'text-xs'}`}
              style={{ color }}>
          {pct}%
        </span>
      </div>
      <div className={`w-full ${height} rounded-full overflow-hidden`}
           style={{ background: '#0f3460' }}>
        <div
          className={`${height} rounded-full score-fill`}
          style={{ '--fill': `${pct}%`, width: `${pct}%`, background: color }}
        />
      </div>
    </div>
  )
}
