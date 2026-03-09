export default function SkillBadge({ label, variant = 'match' }) {
  const styles = {
    match:   { background: 'rgba(39,174,96,0.15)',  color: '#27ae60',  border: '1px solid rgba(39,174,96,0.3)' },
    missing: { background: 'rgba(230,126,34,0.15)', color: '#e67e22',  border: '1px solid rgba(230,126,34,0.3)' },
    neutral: { background: 'rgba(136,146,164,0.1)', color: '#8892a4',  border: '1px solid rgba(136,146,164,0.2)' },
    info:    { background: 'rgba(93,173,226,0.12)', color: '#5dade2',  border: '1px solid rgba(93,173,226,0.25)' },
  }
  return (
    <span className="inline-block px-2 py-0.5 rounded-full text-xs font-medium"
          style={styles[variant] || styles.neutral}>
      {label}
    </span>
  )
}
